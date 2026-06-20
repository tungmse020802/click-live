"use strict";

// Per-iPhone WebDriverAgent launcher for Windows/macOS hosts.
//
// For each device the launcher spawns two processes:
//   1. `ios runwda ...`    - keeps the XCUITest runner alive on the iPhone
//   2. `ios forward ...`   - exposes WDA on a unique localhost port
//
// Both processes are tied to a single device. When either dies, the launcher
// flips into ERROR state and emits via onState so the UI can react.
//
// go-ios (https://github.com/danielpaulus/go-ios) is the default toolchain
// because it is the only Windows-friendly tool that supports iOS 17/18.
// pymobiledevice3 can be selected via `launcherTool: "pymobiledevice3"`.

const { spawn } = require("node:child_process");
const { resolveGoIosPath } = require("./paths");

const STATE = Object.freeze({
  IDLE: "idle",
  STARTING: "starting",
  RUNNING: "running",
  STOPPING: "stopping",
  ERROR: "error",
});

const DEFAULT_BUNDLE_ID = "com.tungld.clicklive.WebDriverAgentRunner.xctrunner";
const DEFAULT_WDA_DEVICE_PORT = 8100;
const READY_TIMEOUT_MS = 90_000;
const READY_POLL_INTERVAL_MS = 1_500;

function nowLabel() {
  return new Date().toLocaleTimeString("sv-SE", { hour12: false });
}

function trimSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}

function buildRunWdaCommand(tool, device, settings) {
  const bundleId = settings.wdaBundleId || DEFAULT_BUNDLE_ID;
  const remotePort = Number(settings.wdaDevicePort) || DEFAULT_WDA_DEVICE_PORT;

  if (tool === "pymobiledevice3") {
    return {
      command: settings.pymobiledevice3Path || "pymobiledevice3",
      args: [
        "developer",
        "dvt",
        "run-xctest",
        "--bundle-id",
        bundleId,
        "--udid",
        device.udid,
        "--port",
        String(remotePort),
      ],
    };
  }

  // go-ios (default) — auto-resolve bundled binary when goIosPath is empty
  return {
    command: resolveGoIosPath(settings),
    args: [
      "runwda",
      `--bundleid=${bundleId}`,
      `--testrunnerbundleid=${bundleId}`,
      "--xctestconfig=WebDriverAgentRunner.xctest",
      `--udid=${device.udid}`,
      `--env=USE_PORT=${remotePort}`,
    ],
  };
}

function buildPortForwardCommand(tool, device, settings) {
  const remotePort = Number(settings.wdaDevicePort) || DEFAULT_WDA_DEVICE_PORT;
  if (tool === "pymobiledevice3") {
    // pymobiledevice3 forwards via `usbmux forward`
    return {
      command: settings.pymobiledevice3Path || "pymobiledevice3",
      args: [
        "usbmux",
        "forward",
        String(device.port),
        String(remotePort),
        "--udid",
        device.udid,
      ],
    };
  }
  // go-ios
  return {
    command: resolveGoIosPath(settings),
    args: [
      "forward",
      String(device.port),
      String(remotePort),
      `--udid=${device.udid}`,
    ],
  };
}

class WdaLauncher {
  constructor({ device, settings, onState, onLog }) {
    this.device = device;
    this.settings = settings || {};
    this.onState = onState || (() => {});
    this.onLog = onLog || (() => {});
    this.runProcess = null;
    this.forwardProcess = null;
    this.state = STATE.IDLE;
    this.lastError = "";
    this.startedAt = null;
    this.tool = this.settings.launcherTool === "pymobiledevice3" ? "pymobiledevice3" : "go-ios";
  }

  setSettings(settings) {
    this.settings = settings || {};
    this.tool = this.settings.launcherTool === "pymobiledevice3" ? "pymobiledevice3" : "go-ios";
  }

  setDevice(device) {
    this.device = { ...this.device, ...device };
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
      runPid: this.runProcess?.pid || null,
      forwardPid: this.forwardProcess?.pid || null,
      lastError: this.lastError,
      startedAt: this.startedAt,
      tool: this.tool,
    };
  }

  wdaUrl() {
    if (!this.device.port) return "";
    return `http://127.0.0.1:${this.device.port}`;
  }

  isRunning() {
    return this.state === STATE.RUNNING || this.state === STATE.STARTING;
  }

  async start() {
    if (this.isRunning()) return this.snapshot();
    if (!this.device.udid) throw new Error("device.udid is required");
    if (!this.device.port) throw new Error("device.port is required");

    this.state = STATE.STARTING;
    this.lastError = "";
    this.emit();

    try {
      this.spawnRunWda();
      // Give runwda a moment to attach to the device before forwarding the port.
      await new Promise((resolve) => setTimeout(resolve, 800));
      await this.spawnPortForwardWithRetry();
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

  spawnRunWda() {
    const { command, args } = buildRunWdaCommand(this.tool, this.device, this.settings);
    this.log(`spawn ${command} ${args.join(" ")}`);
    const child = spawn(command, args, {
      shell: process.platform === "win32",
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.runProcess = child;
    child.stdout.on("data", (chunk) => this.log(`runwda: ${String(chunk).trimEnd()}`));
    child.stderr.on("data", (chunk) => this.log(`runwda: ${String(chunk).trimEnd()}`));
    child.on("error", (error) => {
      this.lastError = error.message;
      this.state = STATE.ERROR;
      this.emit();
    });
    child.on("close", (code) => {
      this.log(`runwda exited code=${code}`);
      if (this.runProcess !== child) return;
      this.runProcess = null;
      if (this.state === STATE.RUNNING) {
        this.state = STATE.ERROR;
        this.lastError = `runwda exited unexpectedly with code ${code}`;
        this.emit();
      }
    });
  }

  spawnPortForward() {
    const { command, args } = buildPortForwardCommand(this.tool, this.device, this.settings);
    this.log(`spawn ${command} ${args.join(" ")}`);
    const child = spawn(command, args, {
      shell: process.platform === "win32",
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.forwardProcess = child;
    child.stdout.on("data", (chunk) => this.log(`forward: ${String(chunk).trimEnd()}`));
    child.stderr.on("data", (chunk) => this.log(`forward: ${String(chunk).trimEnd()}`));
    child.on("error", (error) => {
      this.lastError = error.message;
      this.state = STATE.ERROR;
      this.emit();
    });
    child.on("close", (code) => {
      this.log(`forward exited code=${code}`);
      if (this.forwardProcess !== child) return;
      this.forwardProcess = null;
      if (this.state === STATE.RUNNING) {
        this.state = STATE.ERROR;
        this.lastError = `port forward exited with code ${code}`;
        this.emit();
      }
    });
  }

  async spawnPortForwardWithRetry(maxAttempts = 5, retryDelayMs = 2000) {
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      const result = await new Promise((resolve) => {
        const { command, args } = buildPortForwardCommand(this.tool, this.device, this.settings);
        if (attempt === 1) this.log(`spawn ${command} ${args.join(" ")}`);
        else this.log(`forward: retry attempt ${attempt}/${maxAttempts}`);
        const child = spawn(command, args, {
          shell: process.platform === "win32",
          stdio: ["ignore", "pipe", "pipe"],
        });
        let outputBuf = "";
        let settled = false;
        // resolve({ child }) on success, resolve({ error }) on fatal, resolve(null) on retryable fail
        const settle = (val) => { if (!settled) { settled = true; resolve(val); } };

        const onData = (chunk) => {
          const text = String(chunk).trimEnd();
          this.log(`forward: ${text}`);
          outputBuf += text;
        };
        child.stdout.on("data", onData);
        child.stderr.on("data", onData);
        child.on("error", (error) => {
          this.log(`forward: error ${error.message}`);
          settle(null);
        });
        child.on("close", (code) => {
          this.log(`forward exited code=${code}`);
          if (code !== 0) {
            // Device not found — no point retrying
            if (outputBuf.includes("Device not found") || outputBuf.includes("not found")) {
              settle({ error: `Device not found: ${this.device.udid}` });
            } else {
              settle(null);
            }
            return;
          }
          settle({ child });
        });

        // Still running after 1.5s → forward is listening successfully
        setTimeout(() => {
          if (!settled && child.exitCode == null) settle({ child });
        }, 1500);
      });

      if (result && result.error) {
        throw new Error(result.error);
      }

      if (result && result.child) {
        this.forwardProcess = result.child;
        result.child.on("close", (code) => {
          if (this.forwardProcess !== result.child) return;
          this.forwardProcess = null;
          if (this.state === STATE.RUNNING) {
            this.state = STATE.ERROR;
            this.lastError = `port forward exited with code ${code}`;
            this.emit();
          }
        });
        return;
      }

      if (attempt < maxAttempts) {
        this.log(`forward: port busy, waiting ${retryDelayMs}ms before retry...`);
        await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
      }
    }
    throw new Error(`Failed to forward port ${this.device.port} after ${maxAttempts} attempts`);
  }

  async waitUntilWdaReady() {
    const url = `${trimSlash(this.wdaUrl())}/status`;
    const deadline = Date.now() + READY_TIMEOUT_MS;
    while (Date.now() < deadline) {
      if (!this.runProcess && this.state !== STATE.STARTING) {
        throw new Error(this.lastError || "runwda process exited before WDA was ready");
      }
      try {
        const response = await fetch(url, { signal: AbortSignal.timeout(2000) });
        if (response.ok) return;
      } catch {}
      await new Promise((resolve) => setTimeout(resolve, READY_POLL_INTERVAL_MS));
    }
    throw new Error(`WDA on ${this.wdaUrl()} did not respond within ${READY_TIMEOUT_MS}ms`);
  }

  async stop() {
    if (this.state === STATE.IDLE && !this.runProcess && !this.forwardProcess) {
      return this.snapshot();
    }
    this.state = STATE.STOPPING;
    this.emit();
    const procs = [this.forwardProcess, this.runProcess].filter(Boolean);
    if (process.platform === "win32") {
      for (const proc of procs) {
        try {
          if (proc.pid) spawn("taskkill", ["/F", "/T", "/PID", String(proc.pid)], { shell: false, stdio: "ignore" });
        } catch {}
      }
      // Kill any orphan ios.exe processes for this device's port
      try {
        spawn("taskkill", ["/F", "/IM", "ios.exe"], { shell: false, stdio: "ignore" });
      } catch {}
      await new Promise((resolve) => setTimeout(resolve, 2000));
    } else {
      for (const proc of procs) {
        try { proc.kill("SIGTERM"); } catch {}
      }
      await new Promise((resolve) => setTimeout(resolve, 1200));
      for (const proc of procs) {
        try { if (!proc.killed) proc.kill("SIGKILL"); } catch {}
      }
      // Kill orphan xcodebuild processes for this device
      if (this.device.udid) {
        try {
          spawn("pkill", ["-f", `xcodebuild.*${this.device.udid}`], { stdio: "ignore" });
        } catch {}
      }
    }
    this.runProcess = null;
    this.forwardProcess = null;
    this.state = STATE.IDLE;
    this.startedAt = null;
    this.lastError = "";
    this.emit();
    this.log("stopped");
    return this.snapshot();
  }
}

// Kill all tracked WdaLauncher processes on app exit (SIGINT, SIGTERM, uncaught crash)
const _globalLaunchers = new Set();

const _exitHandler = () => {
  for (const launcher of _globalLaunchers) {
    const procs = [launcher.forwardProcess, launcher.runProcess].filter(Boolean);
    if (process.platform === "win32") {
      for (const proc of procs) {
        try { if (proc.pid) spawn("taskkill", ["/F", "/T", "/PID", String(proc.pid)], { shell: false, stdio: "ignore" }); } catch {}
      }
    } else {
      for (const proc of procs) {
        try { proc.kill("SIGKILL"); } catch {}
      }
      // Kill all xcodebuild/WebDriverAgentRunner orphans on exit
      try { spawn("pkill", ["-f", "xcodebuild.*WebDriverAgentRunner"], { stdio: "ignore" }); } catch {}
    }
  }
};

process.once("exit", _exitHandler);
process.once("SIGINT", () => { _exitHandler(); process.exit(0); });
process.once("SIGTERM", () => { _exitHandler(); process.exit(0); });

WdaLauncher._register = function (launcher) { _globalLaunchers.add(launcher); };
WdaLauncher._unregister = function (launcher) { _globalLaunchers.delete(launcher); };

module.exports = {
  WdaLauncher,
  STATE,
  DEFAULT_BUNDLE_ID,
  DEFAULT_WDA_DEVICE_PORT,
  buildRunWdaCommand,
  buildPortForwardCommand,
};
