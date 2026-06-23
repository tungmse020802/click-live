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
// Unlike WdaLauncher (go-ios + forward), the WDA URL exposed by xcodebuild is
// already routable on the Mac LAN; we still record device.port locally so the
// fleet UI keeps the same per-slot port abstraction.

const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { spawn } = require("node:child_process");
const { resolveDerivedDataPath } = require("./paths");

const STATE = Object.freeze({
  IDLE: "idle",
  STARTING: "starting",
  RUNNING: "running",
  STOPPING: "stopping",
  ERROR: "error",
});

const READY_TIMEOUT_MS = 180_000;
const READY_POLL_INTERVAL_MS = 1_500;
const URL_REGEX = /ServerURLHere->(http:\/\/[^<\s]+)<-ServerURLHere/;

function nowLabel() {
  return new Date().toLocaleTimeString("sv-SE", { hour12: false });
}

function trimSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}

class MacosLauncher {
  constructor({ device, settings, onState, onLog }) {
    this.device = device;
    this.settings = settings || {};
    this.onState = onState || (() => {});
    this.onLog = onLog || (() => {});
    this.process = null;
    this.state = STATE.IDLE;
    this.lastError = "";
    this.startedAt = null;
    this.tool = "macos";
    this.discoveredUrl = "";
    this.derivedDataPath = this.resolveDerivedDataDir();
    this.logBuffer = "";
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
      forwardPid: null,
      lastError: this.lastError,
      startedAt: this.startedAt,
      tool: this.tool,
      derivedDataPath: this.derivedDataPath,
    };
  }

  wdaUrl() {
    return this.discoveredUrl || (this.device.port ? `http://127.0.0.1:${this.device.port}` : "");
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
    this.logBuffer = "";
    this.emit();

    try {
      await this.ensureBuilt();
      this.spawnXcodebuild();
      await this.waitUntilWdaReady();
      this.startedAt = new Date().toISOString();
      this.state = STATE.RUNNING;
      this.emit();
      this.log(`WDA ready on ${this.wdaUrl()}`);
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

  buildBundleId() {
    return String(this.settings.wdaBundleId || "com.tungld.clicklive.WebDriverAgentRunner.xctrunner")
      .replace(/\.xctrunner$/, "");
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
      // Throttle: emit non-empty lines but skip xcodebuild noise like timestamps.
      const lines = text.split(/\r?\n/).filter((line) => line.trim());
      for (const line of lines.slice(-5)) {
        this.log(`xcodebuild: ${line.trimEnd()}`);
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

  async waitUntilWdaReady() {
    const deadline = Date.now() + READY_TIMEOUT_MS;
    while (Date.now() < deadline) {
      if (!this.process && this.state !== STATE.STARTING) {
        throw new Error(this.lastError || "xcodebuild exited before WDA was ready");
      }
      const url = trimSlash(this.discoveredUrl);
      if (url) {
        try {
          const response = await fetch(`${url}/status`, { signal: AbortSignal.timeout(2000) });
          if (response.ok) return;
        } catch {}
      }
      await new Promise((resolve) => setTimeout(resolve, READY_POLL_INTERVAL_MS));
    }
    throw new Error(`WDA did not respond within ${READY_TIMEOUT_MS}ms`);
  }

  async stop() {
    if (this.state === STATE.IDLE && !this.process) return this.snapshot();
    this.state = STATE.STOPPING;
    this.emit();
    const child = this.process;
    if (child) {
      try { child.kill("SIGTERM"); } catch {}
      await new Promise((resolve) => setTimeout(resolve, 1500));
      try { if (this.process === child && !child.killed) child.kill("SIGKILL"); } catch {}
      if (this.process === child) this.process = null;
    }
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
