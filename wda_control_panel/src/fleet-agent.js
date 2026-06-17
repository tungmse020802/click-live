"use strict";

const { spawn } = require("node:child_process");
const { WdaLauncher, STATE: LAUNCHER_STATE } = require("./wda-launcher");
const { MacosLauncher } = require("./macos-launcher");
const {
  AutomationWorker,
  STATE: WORKER_STATE,
  DEFAULT_CONTROLLER_DIR,
  readEnvFile,
} = require("./automation-worker");
const {
  checkAppleMobileDeviceService,
  openDriverDownload,
  checkGoIos,
  checkBundledIpa,
  installWdaIpa,
  listInstalledApps,
  hasWdaInstalled,
  checkXcode,
  checkWdaProject,
  detectSigningIdentities,
  buildWdaIpa,
  scanCoreDevices,
  installViaDevicectl,
} = require("./setup-helper");
const {
  resolveGoIosPath,
  resolveIpaPath,
  resolveWdaProjectPath,
  resolveDerivedDataPath,
  pathExists,
} = require("./paths");

function nowLabel() {
  return new Date().toLocaleTimeString("sv-SE", { hour12: false });
}

function trimSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseJson(text, fallback) {
  try {
    return JSON.parse(text);
  } catch {
    return fallback;
  }
}

function run(command, args, options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env,
      shell: process.platform === "win32",
    });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk) => { stdout += chunk; });
    child.stderr?.on("data", (chunk) => { stderr += chunk; });
    child.on("error", (error) => resolve({ ok: false, stdout, stderr: error.message, code: -1 }));
    child.on("close", (code) => resolve({ ok: code === 0, stdout, stderr, code }));
  });
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  const body = text ? parseJson(text, { raw: text }) : {};
  if (!response.ok) {
    throw new Error(`${response.status} ${body.error || body.value?.message || body.raw || response.statusText}`);
  }
  return body;
}

class FleetAgent {
  constructor({ store, onState, onLog }) {
    this.store = store;
    this.onState = onState || (() => {});
    this.onLog = onLog || (() => {});
    this.launchers = new Map();
    this.workers = new Map();
    this.manualCommandQueues = new Map();
    this.detectedDevices = [];
    this.lastScanAt = null;
    this.queueItems = new Map();
    this.refreshFromStore();
  }

  log(message) {
    this.onLog(`[${nowLabel()}] ${message}`);
  }

  runtimeSettings(config) {
    return {
      ...config,
      wdaProjectPath: resolveWdaProjectPath(config),
      derivedDataPath: resolveDerivedDataPath(config),
    };
  }

  refreshFromStore() {
    const config = this.store.get();
    const runtimeSettings = this.runtimeSettings(config);
    for (const device of config.devices) {
      if (!device.enabled) {
        if (this.launchers.has(device.deviceId)) {
          this.launchers.get(device.deviceId).setDevice(device);
          this.launchers.get(device.deviceId).setSettings(runtimeSettings);
        }
        continue;
      }
      const existing = this.launchers.get(device.deviceId);
      if (existing) {
        existing.setDevice(device);
        existing.setSettings(runtimeSettings);
      } else {
        this.launchers.set(device.deviceId, this.makeLauncher(device, config));
      }
    }
    // Drop launchers whose device row was disabled or removed.
    for (const [deviceId, launcher] of this.launchers) {
      const match = config.devices.find((device) => device.deviceId === deviceId);
      if (!match || !match.enabled) {
        launcher.stop().catch(() => {});
        this.stopAutomationWorker(deviceId).catch(() => {});
        this.launchers.delete(deviceId);
      }
    }
    this.emit();
  }

  makeLauncher(device, config) {
    const tool = config.launcherTool;
    const Launcher = tool === "macos" && process.platform === "darwin" ? MacosLauncher : WdaLauncher;
    return new Launcher({
      device,
      settings: this.runtimeSettings(config),
      onState: () => this.emit(),
      onLog: (line) => this.onLog(line),
    });
  }

  emit() {
    this.onState(this.snapshot());
  }

  snapshot() {
    const config = this.store.get();
    const devices = config.devices.map((device) => {
      const launcher = this.launchers.get(device.deviceId);
      const worker = this.workers.get(device.deviceId);
      return {
        ...device,
        wdaUrl: launcher?.wdaUrl() || `http://127.0.0.1:${device.port}`,
        runtime: launcher
          ? launcher.snapshot()
          : { state: LAUNCHER_STATE.IDLE, runPid: null, forwardPid: null, lastError: "", startedAt: null },
        automation: worker
          ? worker.snapshot()
          : { state: WORKER_STATE.IDLE, pid: null, lastError: "", startedAt: null },
      };
    });
    return {
      config,
      devices,
      detected: this.detectedDevices,
      lastScanAt: this.lastScanAt,
    };
  }

  async scanDetected() {
    const settings = this.store.get();
    const tool = settings.launcherTool;
    if (tool === "macos" && process.platform === "darwin") {
      this.log("Scanning iPhones via xcrun devicectl list devices");
      const result = await scanCoreDevices();
      this.detectedDevices = result.ok ? result.devices : [];
      this.lastScanAt = new Date().toISOString();
      this.emit();
      if (!result.ok) {
        this.log(`Scan failed: ${result.detail}`);
        return [];
      }
      this.log(`Detected ${this.detectedDevices.length} iPhone(s) via devicectl`);
      return this.detectedDevices;
    }
    let command;
    let args;
    if (tool === "pymobiledevice3") {
      command = settings.pymobiledevice3Path || "pymobiledevice3";
      args = ["usbmux", "list"];
    } else {
      command = resolveGoIosPath(settings);
      args = ["list", "--details"];
    }
    this.log(`Scanning USB devices via ${command} ${args.join(" ")}`);
    const result = await run(command, args);
    if (!result.ok) {
      this.detectedDevices = [];
      this.lastScanAt = new Date().toISOString();
      this.emit();
      this.log(`Scan failed: ${result.stderr || result.stdout}`);
      return [];
    }
    this.detectedDevices = parseDeviceList(tool, result.stdout);
    this.lastScanAt = new Date().toISOString();
    this.emit();
    this.log(`Detected ${this.detectedDevices.length} device(s)`);
    return this.detectedDevices;
  }

  async setupStatus() {
    const settings = this.store.get();
    const [driver, goIos, ipa] = await Promise.all([
      checkAppleMobileDeviceService(),
      checkGoIos(settings),
      checkBundledIpa(settings),
    ]);
    return { driver, goIos, ipa };
  }

  async macSetupStatus() {
    if (process.platform !== "darwin") {
      return { supported: false, detail: "macOS-only setup" };
    }
    const settings = this.store.get();
    const [xcode, wdaProject, signing, ipa] = await Promise.all([
      checkXcode(),
      checkWdaProject(settings),
      detectSigningIdentities(),
      checkBundledIpa(settings),
    ]);
    return { supported: true, xcode, wdaProject, signing, ipa };
  }

  async detectSigning() {
    return detectSigningIdentities();
  }

  async buildIpa(options = {}) {
    if (process.platform !== "darwin") throw new Error("Build IPA chỉ chạy trên macOS");
    const settings = this.store.get();
    const teamId = options.appleTeamId || settings.appleTeamId;
    if (!teamId) throw new Error("Cần Apple Team ID. Chọn signing identity ở Setup → Mac.");
    this.log(`Building WDA IPA for team ${teamId}...`);
    const result = await buildWdaIpa({
      ...settings,
      appleTeamId: teamId,
      onProgress: (stage, line) => this.log(`build ${stage}: ${String(line).slice(0, 240)}`),
    });
    this.store.save({ ...settings, appleTeamId: teamId, wdaIpaPath: result.ipaPath });
    this.refreshFromStore();
    this.log(`WDA IPA built at ${result.ipaPath}`);
    return result;
  }

  async openDriverDownload() {
    return openDriverDownload();
  }

  async installWda(deviceId) {
    const config = this.store.get();
    const device = config.devices.find((row) => row.deviceId === deviceId);
    if (!device) throw new Error(`Unknown deviceId ${deviceId}`);
    if (!device.udid) throw new Error(`Device ${deviceId} has no UDID`);
    this.log(`[${deviceId}] Installing WDA IPA...`);
    if (config.launcherTool === "macos" && process.platform === "darwin") {
      const ipaPath = resolveIpaPath(config);
      if (!pathExists(ipaPath)) {
        throw new Error(`WDA IPA missing at ${ipaPath}. Build & sign IPA first.`);
      }
      const result = await installViaDevicectl(device, ipaPath, {
        onProgress: (_command, line) => this.log(`[${deviceId}] devicectl: ${String(line).slice(0, 240)}`),
      });
      this.log(`[${deviceId}] WDA install ok via devicectl`);
      return result;
    }
    const result = await installWdaIpa(device, config);
    this.log(`[${deviceId}] WDA install ok`);
    return result;
  }

  async installWdaAll() {
    const config = this.store.get();
    const targets = config.devices.filter((device) => device.enabled && device.udid);
    this.log(`Installing WDA on ${targets.length} device(s)`);
    const results = await Promise.allSettled(
      targets.map((device) => this.installWda(device.deviceId)),
    );
    return results.map((result, index) => ({
      deviceId: targets[index].deviceId,
      ok: result.status === "fulfilled",
      error: result.status === "rejected" ? result.reason.message : "",
    }));
  }

  async checkWdaInstalled(deviceId) {
    const config = this.store.get();
    const device = config.devices.find((row) => row.deviceId === deviceId);
    if (!device || !device.udid) return { ok: false, installed: false, detail: "no UDID" };
    try {
      const result = await listInstalledApps(device, config);
      return {
        ok: result.ok,
        installed: hasWdaInstalled(result.apps, config.wdaBundleId),
        detail: result.detail,
      };
    } catch (error) {
      return { ok: false, installed: false, detail: error.message };
    }
  }

  async checkWdaInstalledAll() {
    const config = this.store.get();
    const targets = config.devices.filter((device) => device.enabled && device.udid);
    return Promise.all(targets.map(async (device) => ({
      deviceId: device.deviceId,
      ...(await this.checkWdaInstalled(device.deviceId)),
    })));
  }

  async assignDetectedToSlots() {
    const config = this.store.get();
    const detected = this.detectedDevices.filter((entry) => entry.udid);
    let assignedCount = 0;
    const taken = new Set(config.devices.filter((device) => device.udid).map((device) => device.udid));
    const updates = config.devices.map((device) => {
      if (device.udid) return device;
      const next = detected.find((entry) => !taken.has(entry.udid));
      if (!next) return device;
      taken.add(next.udid);
      assignedCount += 1;
      return {
        ...device,
        udid: next.udid,
        enabled: true,
        name: next.name || device.name,
        version: next.version || device.version || "",
      };
    });
    this.store.save({ ...config, devices: updates });
    this.refreshFromStore();
    this.log(`Auto-assigned ${assignedCount} device(s) to empty slots`);
    return { assignedCount };
  }

  buildUdidExports() {
    const detected = (this.detectedDevices || []).filter((entry) => entry.udid);
    const internalRows = [
      ["device_name", "udid", "ios_version", "product_type"],
      ...detected.map((device, index) => [
        device.name || `iPhone ${index + 1}`,
        device.udid,
        device.version || "",
        device.productType || device.productVersion || "",
      ]),
    ];
    const developerRows = [
      ["Device Name", "Device ID"],
      ...detected.map((device, index) => [device.name || `iPhone ${index + 1}`, device.udid]),
    ];
    const internalCsv = internalRows.map((row) => row.map(csvEscape).join(",")).join("\r\n");
    const developerCsv = developerRows.map((row) => row.map(csvEscape).join(",")).join("\r\n");
    const udidsTxt = detected.map((device) => device.udid).join("\n");
    return {
      count: detected.length,
      generatedAt: new Date().toISOString(),
      internalCsv,
      developerCsv,
      udidsTxt,
    };
  }

  async startDevice(deviceId) {
    let config = this.store.get();
    const device = config.devices.find((row) => row.deviceId === deviceId);
    if (!device) throw new Error(`Unknown deviceId ${deviceId}`);
    if (!device.enabled) throw new Error(`Device ${deviceId} is disabled`);
    if (!device.udid) throw new Error(`Device ${deviceId} has no UDID`);
    if (config.launcherTool === "macos" && process.platform === "darwin") {
      const controllerDir = config.automationControllerPath || DEFAULT_CONTROLLER_DIR;
      const controllerEnv = readEnvFile(`${controllerDir}/config.env`);
      let teamId = controllerEnv.DEVELOPMENT_TEAM || "";
      if (!teamId && !config.appleTeamId) {
        const signing = await detectSigningIdentities();
        teamId = signing.identities?.find((identity) => identity.teamId)?.teamId || "";
      }
      teamId ||= config.appleTeamId;
      if (!teamId) throw new Error("No Apple Development signing identity with Team ID found");
      if (teamId !== config.appleTeamId) {
        config = this.store.save({ ...config, appleTeamId: teamId });
        this.log(`Using Apple Team ID ${teamId} from controller config`);
      }
    }
    let launcher = this.launchers.get(deviceId);
    if (!launcher) {
      launcher = this.makeLauncher(device, config);
      this.launchers.set(deviceId, launcher);
    } else {
      launcher.setDevice(device);
      launcher.setSettings(this.runtimeSettings(config));
    }
    const result = await launcher.start();
    if (config.automationEnabled) {
      await this.startAutomationWorker(device, config, launcher.wdaUrl());
    }
    return { ...result, automation: this.workers.get(deviceId)?.snapshot() || null };
  }

  async stopDevice(deviceId) {
    const launcher = this.launchers.get(deviceId);
    await this.stopAutomationWorker(deviceId);
    if (!launcher) return null;
    return launcher.stop();
  }

  async startAutomationWorker(device, config, wdaUrl) {
    await this.stopAutomationWorker(device.deviceId);
    const worker = new AutomationWorker({
      device,
      settings: config,
      wdaUrl,
      onState: () => this.emit(),
      onLog: (line) => this.onLog(`[${nowLabel()}] ${line}`),
    });
    this.workers.set(device.deviceId, worker);
    try {
      await worker.start();
    } catch (error) {
      this.workers.delete(device.deviceId);
      throw error;
    }
    return worker.snapshot();
  }

  async stopAutomationWorker(deviceId) {
    const worker = this.workers.get(deviceId);
    if (!worker) return null;
    await worker.stop();
    this.workers.delete(deviceId);
    this.emit();
    return null;
  }

  async startAllEnabled() {
    const config = this.store.get();
    const targets = config.devices.filter((device) => device.enabled && device.udid);
    this.log(`Starting WDA on ${targets.length} device(s)`);
    const results = await Promise.allSettled(targets.map((device) => this.startDevice(device.deviceId)));
    return results.map((result, index) => ({
      deviceId: targets[index].deviceId,
      ok: result.status === "fulfilled",
      error: result.status === "rejected" ? result.reason.message : "",
    }));
  }

  async stopAll() {
    this.log(`Stopping all launchers (${this.launchers.size})`);
    await Promise.allSettled([...this.workers.keys()].map((deviceId) => this.stopAutomationWorker(deviceId)));
    const launchers = [...this.launchers.values()];
    await Promise.allSettled(launchers.map((launcher) => launcher.stop()));
  }

  async withManualPriority(deviceId, label, action) {
    const previous = this.manualCommandQueues.get(deviceId) || Promise.resolve();
    const run = previous.catch(() => {}).then(async () => {
      const configBefore = this.store.get();
      const deviceBefore = configBefore.devices.find((row) => row.deviceId === deviceId);
      const launcher = this.launchers.get(deviceId);
      const worker = this.workers.get(deviceId);
      const workerState = worker?.snapshot?.().state;
      const shouldResumeAutomation = Boolean(
        worker
        && configBefore.automationEnabled
        && deviceBefore?.enabled
        && launcher?.state === LAUNCHER_STATE.RUNNING
        && [WORKER_STATE.STARTING, WORKER_STATE.RUNNING].includes(workerState),
      );

      if (worker) {
        this.log(`[${deviceId}] Manual priority: pausing queue automation for ${label}`);
        await this.stopAutomationWorker(deviceId);
      }

      try {
        this.log(`[${deviceId}] Manual priority: running ${label}`);
        return await action();
      } finally {
        const configAfter = this.store.get();
        const deviceAfter = configAfter.devices.find((row) => row.deviceId === deviceId);
        const currentLauncher = this.launchers.get(deviceId);
        if (
          shouldResumeAutomation
          && configAfter.automationEnabled
          && deviceAfter?.enabled
          && currentLauncher?.state === LAUNCHER_STATE.RUNNING
          && !this.workers.has(deviceId)
        ) {
          try {
            this.log(`[${deviceId}] Manual priority: resuming queue automation`);
            await this.startAutomationWorker(deviceAfter, configAfter, currentLauncher.wdaUrl());
          } catch (error) {
            this.log(`[${deviceId}] Manual priority: resume automation failed: ${error.message}`);
          }
        }
      }
    });
    this.manualCommandQueues.set(deviceId, run);
    run.finally(() => {
      if (this.manualCommandQueues.get(deviceId) === run) {
        this.manualCommandQueues.delete(deviceId);
      }
    }).catch(() => {});
    return run;
  }

  async openUrlOnDevice(deviceId, url) {
    return this.withManualPriority(deviceId, "Open URL", () => this.openUrlOnDeviceDirect(deviceId, url));
  }

  async openUrlOnDeviceDirect(deviceId, url) {
    if (!url) throw new Error("URL is required");
    const launcher = this.launchers.get(deviceId);
    if (!launcher || launcher.state !== LAUNCHER_STATE.RUNNING) {
      throw new Error(`Device ${deviceId} is not running. Start it first.`);
    }
    const wdaUrl = trimSlash(launcher.wdaUrl());
    const session = await fetchJson(`${wdaUrl}/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        capabilities: {
          alwaysMatch: {
            "appium:bundleId": "com.apple.mobilesafari",
            "appium:noReset": true,
            "appium:waitForIdleTimeout": 0,
          },
        },
      }),
    });
    const sessionId = session.value?.sessionId;
    if (!sessionId) throw new Error("WDA did not return a session id");
    try {
      await this.dismissFloatingVideoIfNeeded(wdaUrl, sessionId, deviceId);
      await fetchJson(`${wdaUrl}/session/${sessionId}/url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      await this.acceptOpenInTikTokPrompt(wdaUrl, sessionId, deviceId);
      this.log(`[${deviceId}] Opened ${url}`);
    } finally {
      await fetchJson(`${wdaUrl}/session/${sessionId}`, { method: "DELETE" }).catch(() => {});
    }
  }

  async acceptOpenInTikTokPrompt(wdaUrl, sessionId, deviceId) {
    const deadline = Date.now() + 3500;
    const selectors = [
      { using: "accessibility id", value: "Mở trang này trong TikTok" },
      { using: "accessibility id", value: "Mở trang này trong \"TikTok\"" },
      { using: "accessibility id", value: "Mở trong TikTok" },
      { using: "accessibility id", value: "Mở" },
      { using: "accessibility id", value: "Open" },
      { using: "accessibility id", value: "Open in TikTok" },
      { using: "-ios class chain", value: "**/XCUIElementTypeButton[`label CONTAINS[c] 'Mở trang này' OR name CONTAINS[c] 'Mở trang này' OR label CONTAINS[c] 'TikTok' OR name CONTAINS[c] 'TikTok' OR label CONTAINS[c] 'Open' OR name CONTAINS[c] 'Open' OR label CONTAINS[c] 'Mở' OR name CONTAINS[c] 'Mở'`]" },
    ];

    while (Date.now() < deadline) {
      try {
        const alertText = await fetchJson(`${wdaUrl}/session/${sessionId}/alert/text`);
        if (String(alertText.value || "").includes("TikTok")) {
          this.log(`[${deviceId}] Open in TikTok native alert visible`);
        }
      } catch {}

      for (const selector of selectors) {
        try {
          const found = await fetchJson(`${wdaUrl}/session/${sessionId}/element`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(selector),
          });
          const elementId = found.value?.ELEMENT || found.value?.["element-6066-11e4-a52e-4f735466cecf"];
          if (elementId) {
            await fetchJson(`${wdaUrl}/session/${sessionId}/element/${elementId}/click`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: "{}",
            });
            this.log(`[${deviceId}] Accepted Open in TikTok prompt via ${selector.using}`);
            await sleep(350);
            return true;
          }
        } catch {}
      }

      try {
        await fetchJson(`${wdaUrl}/session/${sessionId}/alert/accept`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        this.log(`[${deviceId}] Accepted Open in TikTok alert fallback`);
        await sleep(350);
        return true;
      } catch {}
      await sleep(150);
    }

    const rect = await this.sessionRect(wdaUrl, sessionId);
    if (rect.width && rect.height) {
      const x = Math.round(Number(rect.width) * 0.72);
      const y = Math.round(Number(rect.height) * 0.76);
      await this.tapSessionPoint(wdaUrl, sessionId, x, y);
      this.log(`[${deviceId}] Tapped estimated Open in TikTok prompt at ${x},${y}`);
      await sleep(350);
      return true;
    }
    return false;
  }

  async dismissFloatingVideoIfNeeded(wdaUrl, sessionId, deviceId) {
    const selectors = [
      { using: "accessibility id", value: "Close" },
      { using: "accessibility id", value: "Đóng" },
      { using: "accessibility id", value: "Stop Picture in Picture" },
      { using: "accessibility id", value: "Close Picture in Picture" },
      { using: "-ios class chain", value: "**/XCUIElementTypeButton[`label CONTAINS[c] 'Close' OR name CONTAINS[c] 'Close' OR label CONTAINS[c] 'Đóng' OR name CONTAINS[c] 'Đóng' OR label CONTAINS[c] 'Picture' OR name CONTAINS[c] 'Picture' OR label CONTAINS[c] 'PiP' OR name CONTAINS[c] 'PiP'`]" },
    ];

    for (const selector of selectors) {
      try {
        const found = await fetchJson(`${wdaUrl}/session/${sessionId}/element`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(selector),
        });
        const elementId = found.value?.ELEMENT || found.value?.["element-6066-11e4-a52e-4f735466cecf"];
        if (elementId) {
          await fetchJson(`${wdaUrl}/session/${sessionId}/element/${elementId}/click`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}",
          });
          this.log(`[${deviceId}] Closed floating video via ${selector.using}`);
          await sleep(250);
          return true;
        }
      } catch {}
    }

    const rect = await this.sessionRect(wdaUrl, sessionId);
    if (!rect.width || !rect.height) return false;
    const w = Number(rect.width);
    const h = Number(rect.height);
    const probes = [
      { reveal: [0.18, 0.18], close: [0.07, 0.10] },
      { reveal: [0.82, 0.18], close: [0.93, 0.10] },
      { reveal: [0.18, 0.78], close: [0.07, 0.70] },
      { reveal: [0.82, 0.78], close: [0.93, 0.70] },
    ];

    for (const probe of probes) {
      await this.tapSessionPoint(wdaUrl, sessionId, Math.round(w * probe.reveal[0]), Math.round(h * probe.reveal[1]));
      await sleep(120);
      for (const selector of selectors.slice(0, 4)) {
        try {
          const found = await fetchJson(`${wdaUrl}/session/${sessionId}/element`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(selector),
          });
          const elementId = found.value?.ELEMENT || found.value?.["element-6066-11e4-a52e-4f735466cecf"];
          if (elementId) {
            await fetchJson(`${wdaUrl}/session/${sessionId}/element/${elementId}/click`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: "{}",
            });
            this.log(`[${deviceId}] Closed floating video after corner probe`);
            await sleep(250);
            return true;
          }
        } catch {}
      }
      await this.tapSessionPoint(wdaUrl, sessionId, Math.round(w * probe.close[0]), Math.round(h * probe.close[1]));
      await sleep(120);
    }
    return false;
  }

  async sessionRect(wdaUrl, sessionId) {
    try {
      const response = await fetchJson(`${wdaUrl}/session/${sessionId}/window/rect`);
      return response.value || {};
    } catch {
      return {};
    }
  }

  async tapSessionPoint(wdaUrl, sessionId, x, y) {
    await fetchJson(`${wdaUrl}/session/${sessionId}/actions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        actions: [
          {
            type: "pointer",
            id: `finger-${Date.now()}`,
            parameters: { pointerType: "touch" },
            actions: [
              { type: "pointerMove", duration: 0, x, y },
              { type: "pointerDown", button: 0 },
              { type: "pause", duration: 60 },
              { type: "pointerUp", button: 0 },
            ],
          },
        ],
      }),
    });
  }

  async fetchQueue(options = {}) {
    const config = this.store.get();
    const queueUrl = trimSlash(config.queueUrl);
    if (!queueUrl) throw new Error("Queue server URL is empty");
    const limit = Math.max(1, Math.min(Number(options.limit) || 50, 500));
    const statuses = String(options.statuses || "").trim();
    const url = new URL(`${queueUrl}/api/queue`);
    url.searchParams.set("limit", String(limit));
    if (statuses) url.searchParams.set("statuses", statuses);
    const snapshot = await fetchJson(url.toString(), {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10_000),
    });
    this.queueItems = new Map(
      (snapshot.items || []).map((item) => [Number(item.id), item]),
    );
    return snapshot;
  }

  async dispatchQueueItem(jobId, deviceId) {
    const id = Number(jobId);
    if (!Number.isInteger(id) || id <= 0) throw new Error("Invalid queue job ID");
    const item = this.queueItems.get(id);
    if (!item) throw new Error(`Queue job #${id} is not loaded. Refresh Queue first.`);
    const url = extractQueueUrl(item);
    if (!url) throw new Error(`Queue job #${id} has no supported URL`);
    await this.withManualPriority(deviceId, `Queue #${id}`, () => this.runQueueItemWorker(item, deviceId, url));
    this.log(`[${deviceId}] Completed queue job #${id}`);
    return { ok: true, jobId: id, deviceId, url };
  }

  async runQueueItemWorker(item, deviceId, url) {
    const config = this.store.get();
    const launcher = this.launchers.get(deviceId);
    if (!launcher || launcher.state !== LAUNCHER_STATE.RUNNING) {
      throw new Error(`Device ${deviceId} is not running. Start it first.`);
    }
    const device = config.devices.find((entry) => entry.deviceId === deviceId);
    if (!device) throw new Error(`Device ${deviceId} is not configured`);
    const controllerDir = config.automationControllerPath || DEFAULT_CONTROLLER_DIR;
    const workerPath = require("node:path").join(controllerDir, "worker.js");
    const controllerEnv = readEnvFile(require("node:path").join(controllerDir, "config.env"));
    const text = String(item?.message?.text || "");
    const payload = item?.payload || {};
    const timeMeta = extractTimeMeta(item);
    const job = {
      id: Number(item.id),
      url,
      time: timeMeta.label,
      message: text,
      click_after_ms: timeMeta.click_after_ms,
      payload,
      received_at_ms: Date.now(),
      server_generated_at: new Date().toISOString(),
    };

    const wdaUrl = trimSlash(launcher.wdaUrl());
    const env = {
      ...process.env,
      ...controllerEnv,
      WDA_URL: wdaUrl,
      APPIUM_URL: wdaUrl,
      QUEUE_SERVER_URL: config.queueUrl,
      DEVICE_UDID: device.udid,
      DEVICE_NAME: device.name || device.deviceId,
      DEVICE_ID: device.deviceId,
      PLATFORM_VERSION: device.version || config.platformVersion || "",
      TIKTOK_BUNDLE_ID: controllerEnv.TIKTOK_BUNDLE_ID || "com.ss.iphone.ugc.Ame",
      WDA_SESSION_BUNDLE_ID: controllerEnv.WDA_SESSION_BUNDLE_ID || "com.apple.mobilesafari",
      DEEPLINK_OPEN_MODE: controllerEnv.DEEPLINK_OPEN_MODE || "safari",
      DEEPLINK_FALLBACK_TO_URL: controllerEnv.DEEPLINK_FALLBACK_TO_URL || "false",
      DEEPLINK_REQUIRE_TIKTOK_FOREGROUND: controllerEnv.DEEPLINK_REQUIRE_TIKTOK_FOREGROUND || "true",
      LIVE_TIME_MIN_SECONDS: String(config.liveTimeMinSeconds ?? 20),
      LIVE_TIME_MAX_SECONDS: String(config.liveTimeMaxSeconds ?? 30),
      FILTER_MAX_VIEWS: String(config.filterMaxViews ?? 0),
      FILTER_MIN_BOX1: String(config.filterMinBox1 ?? 0),
      FILTER_MIN_BOX2: String(config.filterMinBox2 ?? 0),
      FILTER_MIN_RATE: String(config.filterMinRate ?? 0),
      OPEN_TAP_REQUEST_LEAD_MS: String(config.openTapRequestLeadMs ?? 2500),
      OPEN_TAP_TRANSPORT_COMPENSATION_MS: String(config.openTapTransportCompensationMs ?? 200),
      OPEN_MAX_LATENESS_MS: String(config.openMaxLatenessMs ?? 1500),
      RUN_ONCE: "true",
      MANUAL_QUEUE_JOB_JSON: JSON.stringify(job),
      PYTHON_PATH: config.pythonPath || controllerEnv.PYTHON_PATH || "python3",
      ELECTRON_RUN_AS_NODE: "1",
    };

    await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [workerPath], {
        cwd: controllerDir,
        env,
        stdio: ["ignore", "pipe", "pipe"],
      });
      let stderr = "";
      child.stdout.on("data", (chunk) => {
        for (const line of String(chunk).split(/\r?\n/).filter(Boolean)) {
          this.log(`[${deviceId}] queue #${item.id}: ${line}`);
        }
      });
      child.stderr.on("data", (chunk) => {
        stderr += String(chunk);
        for (const line of String(chunk).split(/\r?\n/).filter(Boolean)) {
          this.log(`[${deviceId}] queue #${item.id}: ${line}`);
        }
      });
      child.on("error", reject);
      child.on("close", (code) => {
        if (code === 0) resolve();
        else reject(new Error(stderr || `queue worker exited code=${code}`));
      });
    });
  }

  async markQueueItemDone(jobId, note = "WDA Control Panel") {
    const id = Number(jobId);
    if (!Number.isInteger(id) || id <= 0) throw new Error("Invalid queue job ID");
    const config = this.store.get();
    const queueUrl = trimSlash(config.queueUrl);
    if (!queueUrl) throw new Error("Queue server URL is empty");
    const result = await fetchJson(`${queueUrl}/api/queue/mark-done`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ job_id: id, note: String(note || "WDA Control Panel") }),
      signal: AbortSignal.timeout(10_000),
    });
    this.log(`Marked queue job #${id} done`);
    return result;
  }

  async healthCheck(deviceId) {
    const launcher = this.launchers.get(deviceId);
    const url = launcher?.wdaUrl();
    if (!url) return { ok: false, detail: "no launcher" };
    try {
      const body = await fetchJson(`${url}/status`, { signal: AbortSignal.timeout(2500) });
      return { ok: true, detail: body.value?.message || body.value?.state || "ok", body };
    } catch (error) {
      return { ok: false, detail: error.message };
    }
  }

  async healthCheckAll() {
    const config = this.store.get();
    const targets = config.devices.filter((device) => device.enabled);
    const results = await Promise.all(targets.map(async (device) => ({
      deviceId: device.deviceId,
      ...(await this.healthCheck(device.deviceId)),
    })));
    return results;
  }
}

function csvEscape(value) {
  const text = String(value ?? "");
  if (!/[",\r\n]/.test(text)) return text;
  return `"${text.replace(/"/g, '""')}"`;
}

function parseDeviceList(tool, output) {
  if (tool === "macos") {
    return parseXcrunDevices(output);
  }
  if (tool === "pymobiledevice3") {
    return parsePymobiledeviceList(output);
  }
  return parseGoIosList(output);
}

function parseXcrunDevices(output) {
  const lines = String(output).split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  let inDevices = false;
  const devices = [];
  for (const line of lines) {
    if (line.startsWith("== Devices ==")) { inDevices = true; continue; }
    if (line.startsWith("== Devices Offline ==")) { inDevices = true; continue; }
    if (line.startsWith("== Simulators ==")) { inDevices = false; continue; }
    if (!inDevices) continue;
    if (/Mac/i.test(line) && !/iPhone|iPad/i.test(line)) continue;
    const match = line.match(/^(.*?)\s+\(([^()]+)\)\s+\(([0-9A-Fa-f-]{20,}|[0-9a-f-]{36})\)\s*$/);
    if (!match) continue;
    devices.push({
      name: match[1].trim(),
      version: match[2].trim(),
      udid: match[3],
      productType: "",
      status: "connected",
    });
  }
  return devices;
}

function parseGoIosList(output) {
  const lines = String(output).split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const json = lines.find((line) => line.startsWith("{") || line.startsWith("["));
  if (json) {
    const data = parseJson(json, null);
    if (data?.deviceList) {
      return data.deviceList.map((entry) => ({
        udid: entry.Udid || entry.udid,
        name: entry.ProductType || entry.productType || "iPhone",
        version: entry.ProductVersion || entry.productVersion || "",
        status: "connected",
      }));
    }
    if (Array.isArray(data)) {
      return data.map((entry) => ({
        udid: entry.Udid || entry.udid,
        name: entry.ProductType || entry.productType || "iPhone",
        version: entry.ProductVersion || entry.productVersion || "",
        status: "connected",
      }));
    }
  }
  return lines
    .filter((line) => /^[0-9A-Fa-f-]{20,}$/.test(line))
    .map((udid) => ({ udid, name: "iPhone", version: "", status: "connected" }));
}

function parsePymobiledeviceList(output) {
  return String(output).split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.toLowerCase().startsWith("identifier"))
    .map((line) => {
      const fields = line.split(/\s+/);
      const udid = fields.find((field) => /^[0-9A-Fa-f-]{20,}$/.test(field));
      if (!udid) return null;
      return { udid, name: fields[0] || "iPhone", version: "", status: "connected" };
    })
    .filter(Boolean);
}

function extractTimeMeta(item) {
  const payload = item?.payload || {};
  const text = String(item?.message?.text || "");
  const candidates = [
    payload.TIME, payload.time, payload.Time,
    payload.click_time, payload.open_time,
    text,
  ];
  for (const value of candidates) {
    const raw = String(value || "");
    const match = raw.match(/TIME\s*[:：]\s*([^\n\r]+)/i)
      || raw.match(/(\d{1,2}:\d{2}\s*s?\s*-\s*\d{1,2}:\d{2}:\d{2})/i)
      || raw.match(/(\d{1,2}:\d{2}\s*s?)/i);
    if (match) {
      let label = match[1].trim().split(/\s+(?:https?|tiktok):\/\//i)[0].trim();
      // Truncate after "MM:SS - HH:MM:SS" pattern so trailing BOX/Rate/text is excluded
      const tsEnd = label.match(/^(\d{1,2}:\d{2}\s*s?\s*-\s*\d{1,2}:\d{2}:\d{2})/i)
        || label.match(/^(\d{1,2}:\d{2}:\d{2})/i);
      if (tsEnd) label = tsEnd[1].trim();
      const delayMatch = label.match(/(\d{1,2}):(\d{2})\s*s?/i);
      const click_after_ms = delayMatch
        ? (Number(delayMatch[1]) * 60 + Number(delayMatch[2])) * 1000
        : 0;
      return { label, click_after_ms };
    }
  }
  return { label: "", click_after_ms: Number(payload.click_after_ms || item?.click_after_ms || 0) };
}

function extractQueueUrl(item) {
  const payload = item?.payload || {};
  const message = item?.message || {};
  const candidates = [
    payload.url,
    payload.link,
    payload.deeplink,
    payload.deep_link,
    payload.live_url,
    payload.room_url,
    message.text,
  ];
  for (const value of candidates) {
    const match = String(value || "").match(/(?:https?:\/\/|tiktok:\/\/)[^\s<>'"]+/i);
    if (match) return match[0];
  }
  return "";
}

module.exports = { FleetAgent, parseDeviceList, extractQueueUrl };
