"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");

const STATE = Object.freeze({
  IDLE: "idle",
  STARTING: "starting",
  RUNNING: "running",
  ERROR: "error",
});

const DEFAULT_CONTROLLER_DIR = path.resolve(__dirname, "..", "..", "ios_wda_controller");

function readEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return {};
  const result = {};
  for (const rawLine of fs.readFileSync(filePath, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator <= 0) continue;
    const key = line.slice(0, separator).trim();
    let value = line.slice(separator + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"'))
      || (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    result[key] = value;
  }
  return result;
}

class AutomationWorker {
  constructor({ device, settings, wdaUrl, onState, onLog }) {
    this.device = device;
    this.settings = settings || {};
    this.wdaUrl = wdaUrl;
    this.onState = onState || (() => {});
    this.onLog = onLog || (() => {});
    this.process = null;
    this.state = STATE.IDLE;
    this.lastError = "";
    this.startedAt = null;
  }

  snapshot() {
    return {
      state: this.state,
      pid: this.process?.pid || null,
      lastError: this.lastError,
      startedAt: this.startedAt,
    };
  }

  emit() {
    this.onState(this.snapshot());
  }

  log(message) {
    this.onLog(`[${this.device.deviceId}] worker: ${message}`);
  }

  controllerDir() {
    return this.settings.automationControllerPath || DEFAULT_CONTROLLER_DIR;
  }

  async start() {
    if (this.process) return this.snapshot();
    const controllerDir = this.controllerDir();
    const workerPath = path.join(controllerDir, "worker.js");
    if (!fs.existsSync(workerPath)) {
      throw new Error(`Automation worker not found: ${workerPath}`);
    }
    if (!this.wdaUrl) throw new Error("WDA URL is empty");
    const controllerEnv = readEnvFile(path.join(controllerDir, "config.env"));
    const captureDir = path.resolve(controllerDir, controllerEnv.CAPTURE_DIR || "captures");
    const treasureDebugDir = path.resolve(controllerDir, controllerEnv.TREASURE_DEBUG_DIR || "debug_crops");

    this.state = STATE.STARTING;
    this.lastError = "";
    this.emit();

    const env = {
      ...process.env,
      ...controllerEnv,
      WDA_URL: this.wdaUrl,
      APPIUM_URL: this.wdaUrl,
      QUEUE_SERVER_URL: this.settings.queueUrl,
      DEVICE_UDID: this.device.udid,
      DEVICE_NAME: this.device.name || this.device.deviceId,
      DEVICE_ID: this.device.deviceId,
      PLATFORM_VERSION: this.device.version || this.settings.platformVersion || "",
      TIKTOK_BUNDLE_ID: controllerEnv.TIKTOK_BUNDLE_ID || "com.ss.iphone.ugc.Ame",
      WDA_SESSION_BUNDLE_ID: controllerEnv.WDA_SESSION_BUNDLE_ID || "com.apple.mobilesafari",
      DEEPLINK_OPEN_MODE: controllerEnv.DEEPLINK_OPEN_MODE || "safari",
      DEEPLINK_FALLBACK_TO_URL: controllerEnv.DEEPLINK_FALLBACK_TO_URL || "false",
      DEEPLINK_REQUIRE_TIKTOK_FOREGROUND: controllerEnv.DEEPLINK_REQUIRE_TIKTOK_FOREGROUND || "true",
      RUN_ONCE: "false",
      POLL_WAIT_SECONDS: String(this.settings.queuePollWaitSeconds || 25),
      LIVE_TIME_MIN_SECONDS: String(this.settings.liveTimeMinSeconds ?? 20),
      LIVE_TIME_MAX_SECONDS: String(this.settings.liveTimeMaxSeconds ?? 30),
      FILTER_MAX_VIEWS: String(this.settings.filterMaxViews ?? 0),
      FILTER_MIN_BOX1: String(this.settings.filterMinBox1 ?? 0),
      FILTER_MIN_BOX2: String(this.settings.filterMinBox2 ?? 0),
      FILTER_MIN_RATE: String(this.settings.filterMinRate ?? 0),
      OPEN_TAP_REQUEST_LEAD_MS: String(this.settings.openTapRequestLeadMs ?? 2500),
      OPEN_TAP_TRANSPORT_COMPENSATION_MS: String(this.settings.openTapTransportCompensationMs ?? 200),
      OPEN_MAX_LATENESS_MS: String(this.settings.openMaxLatenessMs ?? 1500),
      PYTHON_PATH: this.settings.pythonPath || controllerEnv.PYTHON_PATH || "python3",
      ELECTRON_RUN_AS_NODE: "1",
    };

    this.log(`starting with WDA ${this.wdaUrl}`);
    this.log(`controller dir: ${controllerDir}`);
    this.log(`capture dir: ${captureDir}`);
    this.log(`treasure debug dir: ${treasureDebugDir}`);
    this.log(
      "runtime settings: "
      + `deeplinkMode=${env.DEEPLINK_OPEN_MODE} `
      + `fallbackToUrl=${env.DEEPLINK_FALLBACK_TO_URL} `
      + `requireTikTok=${env.DEEPLINK_REQUIRE_TIKTOK_FOREGROUND} `
      + `timeWindow=${env.LIVE_TIME_MIN_SECONDS}-${env.LIVE_TIME_MAX_SECONDS}s `
      + `openLead=${env.OPEN_TAP_REQUEST_LEAD_MS}ms `
      + `transport=${env.OPEN_TAP_TRANSPORT_COMPENSATION_MS}ms `
      + `treasureDebug=${env.TREASURE_DEBUG_MODE || "off"}`,
    );
    const child = spawn(process.execPath, [workerPath], {
      cwd: controllerDir,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.process = child;

    const handleOutput = (chunk) => {
      for (const line of String(chunk).split(/\r?\n/).filter(Boolean)) {
        this.log(line);
        if (line.includes("Appium session ready:")) {
          this.state = STATE.RUNNING;
          this.startedAt = new Date().toISOString();
          this.emit();
        }
      }
    };
    child.stdout.on("data", handleOutput);
    child.stderr.on("data", handleOutput);
    child.on("error", (error) => {
      this.lastError = error.message;
      this.state = STATE.ERROR;
      this.emit();
    });
    child.on("close", (code, signal) => {
      this.process = null;
      if (this.state !== STATE.IDLE) {
        this.state = code === 0 ? STATE.IDLE : STATE.ERROR;
        this.lastError = code === 0 ? "" : `worker exited code=${code} signal=${signal || ""}`.trim();
        this.emit();
      }
      this.log(`exited code=${code} signal=${signal || ""}`);
    });
    return this.snapshot();
  }

  async stop() {
    const child = this.process;
    this.state = STATE.IDLE;
    this.lastError = "";
    this.startedAt = null;
    this.emit();
    if (!child) return this.snapshot();
    try { child.kill("SIGTERM"); } catch {}
    await new Promise((resolve) => setTimeout(resolve, 1200));
    try { if (this.process) child.kill("SIGKILL"); } catch {}
    this.process = null;
    this.log("stopped");
    return this.snapshot();
  }
}

module.exports = { AutomationWorker, STATE, DEFAULT_CONTROLLER_DIR, readEnvFile };
