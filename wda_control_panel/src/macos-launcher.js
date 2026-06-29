"use strict";

// macOS-only launcher that drives WDA via `xcodebuild test-without-building`,
// matching what `ios_wda_controller/run.sh` already does. Used when the
// panel runs on macOS and the user wants Mac to host WDA itself, without
// needing go-ios at all.
//
// One MacosLauncher instance manages exactly one iPhone:
//   1. Spawns `xcodebuild ... test-without-building` against the WDA project
//      pinned to that device's UDID.
//   2. Waits for the WDA HTTP endpoint to come up. xcodebuild prints
//      `ServerURLHere->http://...:8100<-ServerURLHere` once WDA is ready.
//   3. Stop() sends SIGTERM/SIGKILL.
//
// xcodebuild starts WDA on the device; go-ios forwards that device port to the
// per-slot localhost port used by the rest of the panel.

const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { spawn, spawnSync } = require("node:child_process");
const { resolveDerivedDataPath, resolveGoIosPath } = require("./paths");

const STATE = Object.freeze({
  IDLE: "idle",
  STARTING: "starting",
  RUNNING: "running",
  STOPPING: "stopping",
  ERROR: "error",
});

const READY_TIMEOUT_MS = 180_000;
const READY_POLL_INTERVAL_MS = 500;
const FORWARD_READY_GRACE_MS = 700;
const HEALTH_INTERVAL_MS = 5_000;
const HEALTH_FAILS_BEFORE_RESTART = 3;
const URL_REGEX = /ServerURLHere->(http:\/\/[^<\s]+)<-ServerURLHere/;
const IMPORTANT_LOG_PATTERNS = [
  /ServerURLHere/i,
  /Running tests/i,
  /Test Suite .*started/i,
  /Test Case .*started/i,
  /error:/i,
  /failed/i,
  /Unable to find a destination/i,
  /ApplicationVerificationFailed/i,
];

const DESTINATION_NOT_READY_MESSAGE = [
  "iPhone is not available to Xcode yet.",
  "Unplug/replug USB, unlock the phone, tap Trust This Computer if prompted, then Scan USB again.",
].join(" ");

function nowLabel() {
  return new Date().toLocaleTimeString("sv-SE", { hour12: false });
}

function trimSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}

function xctraceDeviceState(output, udid) {
  const target = String(udid || "").trim();
  if (!target) return "missing";
  let section = "";
  for (const rawLine of String(output || "").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    if (line.startsWith("== Devices Offline ==")) {
      section = "offline";
      continue;
    }
    if (line.startsWith("== Devices ==")) {
      section = "online";
      continue;
    }
    if (line.startsWith("== Simulators ==")) {
      section = "simulator";
      continue;
    }
    if (!line.includes(target)) continue;
    return section === "offline" ? "offline" : "online";
  }
  return "missing";
}

class MacosLauncher {
  constructor({ device, settings, onState, onLog }) {
    this.device = device;
    this.settings = settings || {};
    this.onState = onState || (() => {});
    this.onLog = onLog || (() => {});
    this.process = null;
    this.forwardProcess = null;
    this.state = STATE.IDLE;
    this.lastError = "";
    this.startedAt = null;
    this.tool = "macos";
    this.discoveredUrl = "";
    this.derivedDataPath = this.resolveDerivedDataDir();
    this.logBuffer = "";
    this.wdaUrlOverride = "";
    this.healthTimer = null;
    this.unhealthyCount = 0;
    this.recovering = false;
  }

  resolveDerivedDataDir() {
    const shared = resolveDerivedDataPath(this.settings || {});
    return path.join(shared, this.device.deviceId || "default");
  }

  setSettings(settings) {
    this.settings = settings || {};
    this.derivedDataPath = this.resolveDerivedDataDir();
  }

  setDevice(device) {
    this.device = { ...this.device, ...device };
    this.derivedDataPath = this.resolveDerivedDataDir();
  }

  log(message) {
    this.onLog(`[${nowLabel()}] [${this.device.deviceId || this.device.udid}] ${message}`);
  }

  emit() {
    this.onState(this.snapshot());
  }

  snapshot() {
    return {
      udid: this.device.udid,
      deviceId: this.device.deviceId,
      port: this.device.port,
      wdaUrl: this.wdaUrl(),
      state: this.state,
      runPid: this.process?.pid || null,
      forwardPid: this.forwardProcess?.pid || null,
      lastError: this.lastError,
      startedAt: this.startedAt,
      tool: this.tool,
      derivedDataPath: this.derivedDataPath,
    };
  }

  wdaUrl() {
    if (this.wdaUrlOverride) return this.wdaUrlOverride;
    return this.device.port ? `http://127.0.0.1:${this.device.port}` : "";
  }

  async isWdaHealthy(url, timeoutMs = 1200) {
    try {
      const response = await fetch(`${trimSlash(url)}/status`, { signal: AbortSignal.timeout(timeoutMs) });
      return response.ok;
    } catch {
      return false;
    }
  }

  isRunning() {
    return this.state === STATE.RUNNING || this.state === STATE.STARTING;
  }

  async start() {
    if (this.isRunning()) return this.snapshot();
    if (process.platform !== "darwin") {
      throw new Error("MacosLauncher only runs on macOS");
    }
    if (!this.device.udid) throw new Error("device.udid is required");
    if (!this.settings.wdaProjectPath) {
      throw new Error("wdaProjectPath is empty. Settings → set WDA project path or run setup.");
    }
    if (!fs.existsSync(this.settings.wdaProjectPath)) {
      throw new Error(`WDA project not found: ${this.settings.wdaProjectPath}`);
    }

    this.state = STATE.STARTING;
    this.lastError = "";
    this.discoveredUrl = "";
    this.wdaUrlOverride = "";
    this.logBuffer = "";
    this.emit();

    try {
      const warmUrl = this.wdaUrl();
      if (warmUrl && await this.isWdaHealthy(warmUrl, 700)) {
        this.startedAt = new Date().toISOString();
        this.state = STATE.RUNNING;
        this.emit();
        this.log(`WDA already healthy on ${warmUrl}`);
        this.startHealthWatchdog();
        return this.snapshot();
      }
      this.ensureDeviceReadyForXcode();
      await this.ensureBuilt();
      this.spawnXcodebuild();
      await this.waitForDiscoveredUrl();
      try {
        await this.spawnPortForwardWithRetry();
      } catch (error) {
        if (!String(error.message || "").includes("Device not found")) throw error;
        const directUrl = this.discoverCoreDeviceWdaUrl();
        if (!directUrl) throw error;
        this.log(`forward: go-ios cannot see device; trying CoreDevice tunnel ${directUrl}`);
        if (!await this.isWdaHealthy(directUrl, 2500)) throw error;
        this.wdaUrlOverride = directUrl;
        this.log(`forward: using CoreDevice tunnel URL ${directUrl}`);
      }
      await this.waitUntilWdaReady();
      this.startedAt = new Date().toISOString();
      this.state = STATE.RUNNING;
      this.emit();
      this.log(`WDA ready on ${this.wdaUrl()}`);
      this.startHealthWatchdog();
      return this.snapshot();
    } catch (error) {
      this.lastError = error.message;
      this.state = STATE.ERROR;
      this.emit();
      this.log(`Start failed: ${error.message}`);
      await this.stop().catch(() => {});
      throw error;
    }
  }

  startHealthWatchdog() {
    this.stopHealthWatchdog();
    const tick = async () => {
      if (this.state !== STATE.RUNNING || this.recovering) return;
      const healthy = await this.isWdaHealthy(this.wdaUrl(), 1500);
      if (healthy) {
        this.unhealthyCount = 0;
      } else {
        this.unhealthyCount += 1;
        this.log(`health: WDA not reachable (${this.unhealthyCount}/${HEALTH_FAILS_BEFORE_RESTART})`);
        if (this.unhealthyCount >= HEALTH_FAILS_BEFORE_RESTART) {
          await this.recover("WDA health check failed");
          return;
        }
      }
      if (this.state === STATE.RUNNING) {
        this.healthTimer = setTimeout(tick, HEALTH_INTERVAL_MS);
      }
    };
    this.healthTimer = setTimeout(tick, HEALTH_INTERVAL_MS);
  }

  stopHealthWatchdog() {
    if (this.healthTimer) clearTimeout(this.healthTimer);
    this.healthTimer = null;
    this.unhealthyCount = 0;
  }

  async recover(reason) {
    if (this.recovering) return;
    this.recovering = true;
    this.log(`health: restarting WDA (${reason})`);
    try {
      await this.stop();
      await new Promise((resolve) => setTimeout(resolve, 1200));
      this.recovering = false;
      await this.start();
    } catch (error) {
      this.recovering = false;
      this.state = STATE.ERROR;
      this.lastError = `Auto-restart failed: ${error.message}`;
      this.emit();
      this.log(this.lastError);
    }
  }

  buildBundleId() {
    return String(this.settings.wdaBundleId || "com.clicklive.WebDriverAgentRunner.xctrunner")
      .replace(/\.xctrunner$/, "");
  }

  ensureDeviceReadyForXcode() {
    const result = spawnSync("xcrun", ["xctrace", "list", "devices"], {
      encoding: "utf8",
      timeout: 15_000,
    });
    const output = `${result.stdout || ""}\n${result.stderr || ""}`;
    if (result.status !== 0) {
      this.log(`device check: xctrace failed; continuing to xcodebuild (${String(result.stderr || "").trim()})`);
      return;
    }
    const state = xctraceDeviceState(output, this.device.udid);
    if (state === "offline") {
      throw new Error(`${DESTINATION_NOT_READY_MESSAGE} (${this.device.udid} is listed under Devices Offline)`);
    }
    if (state === "missing") {
      throw new Error(`${DESTINATION_NOT_READY_MESSAGE} (${this.device.udid} is not listed by xctrace)`);
    }
  }

  discoverCoreDeviceWdaUrl() {
    const outputPath = path.join(os.tmpdir(), `wda-devicectl-${process.pid}-${Date.now()}.json`);
    try {
      const result = spawnSync("xcrun", ["devicectl", "list", "devices", "--json-output", outputPath], {
        encoding: "utf8",
        timeout: 10_000,
      });
      if (result.status !== 0) return "";
      const payload = JSON.parse(fs.readFileSync(outputPath, "utf8"));
      const devices = payload?.result?.devices || [];
      const found = devices.find((entry) => (
        entry?.hardwareProperties?.udid === this.device.udid
        || entry?.identifier === this.device.udid
        || (entry?.connectionProperties?.localHostnames || []).some((name) => String(name).startsWith(`${this.device.udid}.`))
      ));
      const address = found?.connectionProperties?.tunnelIPAddress;
      const devicePort = this.discoveredDevicePort();
      if (!address || !devicePort) return "";
      return `http://[${address}]:${devicePort}`;
    } catch {
      return "";
    } finally {
      try { fs.unlinkSync(outputPath); } catch {}
    }
  }

  buildFingerprint() {
    return JSON.stringify({
      udid: this.device.udid,
      teamId: this.settings.appleTeamId,
      bundleId: this.buildBundleId(),
      projectPath: path.resolve(this.settings.wdaProjectPath),
    });
  }

  buildMetadataPath() {
    return path.join(this.derivedDataPath, ".wda-build-fingerprint.json");
  }

  hasBuildProducts(fingerprint) {
    const products = path.join(this.derivedDataPath, "Build", "Products");
    if (!fs.existsSync(products)) return false;
    const hasXctestrun = fs.readdirSync(products).some((name) => name.endsWith(".xctestrun"));
    if (!hasXctestrun) return false;
    try {
      return fs.readFileSync(this.buildMetadataPath(), "utf8") === fingerprint;
    } catch {
      return false;
    }
  }

  async ensureBuilt() {
    if (!this.settings.appleTeamId) {
      throw new Error("WDA is not built for this slot. Select Apple Team ID in Setup first.");
    }
    const fingerprint = this.buildFingerprint();
    if (this.hasBuildProducts(fingerprint)) return;
    if (fs.existsSync(this.derivedDataPath)) {
      this.log("WDA signing cache is stale; removing DerivedData before rebuild...");
      fs.rmSync(this.derivedDataPath, { recursive: true, force: true });
    }
    const bundleId = this.buildBundleId();
    const args = [
      "-project", this.settings.wdaProjectPath,
      "-scheme", "WebDriverAgentRunner",
      "-destination", `id=${this.device.udid}`,
      "-derivedDataPath", this.derivedDataPath,
      "-allowProvisioningUpdates",
      "CODE_SIGN_STYLE=Automatic",
      `DEVELOPMENT_TEAM=${this.settings.appleTeamId}`,
      `PRODUCT_BUNDLE_IDENTIFIER=${bundleId}`,
      "build-for-testing",
    ];
    this.log("WDA build products missing; building and signing now...");
    await new Promise((resolve, reject) => {
      const child = spawn("xcodebuild", args, { stdio: ["ignore", "pipe", "pipe"] });
      let tail = "";
      const handle = (chunk) => {
        tail = (tail + String(chunk)).slice(-8000);
        const lines = String(chunk).split(/\r?\n/).filter((line) => line.trim());
        for (const line of lines.slice(-2)) this.log(`build: ${line.trimEnd()}`);
      };
      child.stdout.on("data", handle);
      child.stderr.on("data", handle);
      child.on("error", reject);
      child.on("close", (code) => {
        if (code === 0) resolve();
        else reject(new Error(`WDA build failed with code ${code}: ${tail.slice(-1200)}`));
      });
    });
    fs.writeFileSync(this.buildMetadataPath(), fingerprint, "utf8");
    this.log("WDA build-for-testing succeeded");
  }

  spawnXcodebuild() {
    const args = [
      "-project", this.settings.wdaProjectPath,
      "-scheme", "WebDriverAgentRunner",
      "-destination", `id=${this.device.udid}`,
      "-derivedDataPath", this.derivedDataPath,
      "test-without-building",
    ];
    if (this.settings.appleTeamId) {
      args.push(`DEVELOPMENT_TEAM=${this.settings.appleTeamId}`);
    }
    this.log(`spawn xcodebuild ${args.slice(0, 6).join(" ")} ...`);
    const child = spawn("xcodebuild", args, { stdio: ["ignore", "pipe", "pipe"] });
    this.process = child;

    const handleChunk = (chunk) => {
      const text = String(chunk);
      this.logBuffer += text;
      const lines = text.split(/\r?\n/).filter((line) => line.trim());
      for (const line of lines) {
        if (IMPORTANT_LOG_PATTERNS.some((pattern) => pattern.test(line))) {
          this.log(`xcodebuild: ${line.trimEnd()}`);
        }
      }
      const match = this.logBuffer.match(URL_REGEX);
      if (match && !this.discoveredUrl) {
        this.discoveredUrl = match[1].replace(/\/$/, "");
        this.log(`xcodebuild reported WDA url: ${this.discoveredUrl}`);
        this.emit();
      }
    };

    child.stdout.on("data", handleChunk);
    child.stderr.on("data", handleChunk);
    child.on("error", (error) => {
      this.lastError = error.message;
      this.state = STATE.ERROR;
      this.emit();
    });
    child.on("close", (code) => {
      this.log(`xcodebuild exited code=${code}`);
      if (this.process !== child) return;
      this.process = null;
      if (this.state === STATE.RUNNING || this.state === STATE.STARTING) {
        this.state = STATE.ERROR;
        this.lastError = `xcodebuild exited unexpectedly with code ${code}`;
        this.emit();
      }
    });
  }

  discoveredDevicePort() {
    try {
      const url = new URL(this.discoveredUrl);
      return Number(url.port) || 8100;
    } catch {
      return 8100;
    }
  }

  async waitForDiscoveredUrl() {
    const deadline = Date.now() + READY_TIMEOUT_MS;
    while (Date.now() < deadline) {
      if (!this.process && this.state !== STATE.STARTING) {
        throw new Error(this.lastError || "xcodebuild exited before WDA printed URL");
      }
      if (this.discoveredUrl) return;
      await new Promise((resolve) => setTimeout(resolve, READY_POLL_INTERVAL_MS));
    }
    throw new Error(`WDA did not print ServerURLHere within ${READY_TIMEOUT_MS}ms`);
  }

  buildPortForwardCommand() {
    return {
      command: resolveGoIosPath(this.settings),
      args: [
        "forward",
        String(this.device.port),
        String(this.discoveredDevicePort()),
        `--udid=${this.device.udid}`,
      ],
    };
  }

  async spawnPortForwardWithRetry(maxAttempts = 3, retryDelayMs = 700) {
    if (!this.device.port) throw new Error("device.port is required");
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      if (await this.isWdaHealthy(this.wdaUrl(), 500)) {
        this.log(`forward: existing listener is healthy on ${this.wdaUrl()}`);
        return;
      }
      const result = await new Promise((resolve) => {
        const { command, args } = this.buildPortForwardCommand();
        if (attempt === 1) this.log(`spawn ${command} ${args.join(" ")}`);
        else this.log(`forward: retry attempt ${attempt}/${maxAttempts}`);
        const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] });
        let outputBuf = "";
        let settled = false;
        const settle = (value) => {
          if (!settled) {
            settled = true;
            resolve(value);
          }
        };
        const onData = (chunk) => {
          const text = String(chunk);
          outputBuf += text;
          const lines = text.split(/\r?\n/).filter((line) => line.trim());
          for (const line of lines.slice(-2)) this.log(`forward: ${line.trimEnd()}`);
        };
        child.stdout.on("data", onData);
        child.stderr.on("data", onData);
        child.on("error", (error) => {
          this.log(`forward: error ${error.message}`);
          settle(null);
        });
        child.on("close", (code) => {
          this.log(`forward exited code=${code}`);
          if (outputBuf.includes("Device not found") || outputBuf.includes("not found")) {
            settle({ error: `Device not found: ${this.device.udid}` });
            return;
          }
          if (outputBuf.includes("address already in use")) {
            settle({ portBusy: true });
            return;
          }
          settle(code === 0 ? { child } : null);
        });
        setTimeout(() => {
          if (!settled && child.exitCode == null) settle({ child });
        }, FORWARD_READY_GRACE_MS);
      });

      if (result?.error) throw new Error(result.error);
      if (result?.portBusy && await this.isWdaHealthy(this.wdaUrl(), 800)) {
        this.log(`forward: port ${this.device.port} is already healthy`);
        return;
      }
      if (result?.child) {
        this.forwardProcess = result.child;
        result.child.on("close", (code) => {
          if (this.forwardProcess !== result.child) return;
          this.forwardProcess = null;
          if (this.state === STATE.RUNNING || this.state === STATE.STARTING) {
            this.state = STATE.ERROR;
            this.lastError = `port forward exited with code ${code}`;
            this.emit();
          }
        });
        return;
      }
      if (attempt < maxAttempts) {
        this.log(`forward: waiting ${retryDelayMs}ms before retry...`);
        await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
      }
    }
    throw new Error(`Failed to forward port ${this.device.port} after ${maxAttempts} attempts`);
  }

  async waitUntilWdaReady() {
    const deadline = Date.now() + READY_TIMEOUT_MS;
    while (Date.now() < deadline) {
      if (!this.process && this.state !== STATE.STARTING) {
        throw new Error(this.lastError || "xcodebuild exited before WDA was ready");
      }
      const url = trimSlash(this.wdaUrl());
      if (url) {
        if (await this.isWdaHealthy(url, 1000)) return;
      }
      await new Promise((resolve) => setTimeout(resolve, READY_POLL_INTERVAL_MS));
    }
    throw new Error(`WDA did not respond within ${READY_TIMEOUT_MS}ms`);
  }

  async stop() {
    this.stopHealthWatchdog();
    if (this.state === STATE.IDLE && !this.process) return this.snapshot();
    this.state = STATE.STOPPING;
    this.emit();
    const procs = [this.forwardProcess, this.process].filter(Boolean);
    for (const child of procs) {
      try { child.kill("SIGTERM"); } catch {}
    }
    for (const child of procs) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      try { if (!child.killed) child.kill("SIGKILL"); } catch {}
    }
    this.process = null;
    this.forwardProcess = null;
    this.wdaUrlOverride = "";
    this.state = STATE.IDLE;
    this.startedAt = null;
    this.lastError = "";
    this.discoveredUrl = "";
    this.emit();
    this.log("stopped");
    return this.snapshot();
  }
}

module.exports = { MacosLauncher, STATE };
