/**
 * Persistent PowerShell click helper — fallback khi koffi không có (~10ms/click).
 */

const { spawn } = require("child_process");
const { windowsClickHelperPath } = require("./paths");
const { clickLog, clickLogWarn, clickLogError } = require("./click-log");
const {
  parseHelperOkLine,
  parseHelperPongLine,
  parseHelperErrLine,
} = require("./windows-click-protocol");
const { isDoubleClickEnabled } = require("./windows-sendinput");

let winClickHelper = null;
let winClickReady = null;
let helperClickSeq = 0;
let helperSpawnGen = 0;
let helperSuccessfulClicks = 0;
let lastHelperPingAt = 0;
let helperStdoutBuffer = "";

const HELPER_STARTUP_TIMEOUT_MS = 12000;
const HELPER_CLICK_TIMEOUT_MS = 3000;
const HELPER_PING_TIMEOUT_MS = 1500;
const HELPER_MAX_CLICKS = Math.max(
  20,
  Number(process.env.DESKTOP_CLICK_HELPER_MAX_CLICKS) || 120
);

function helperScriptPath() {
  return windowsClickHelperPath();
}

function killHelperProcess(child) {
  if (!child || child.killed) return;
  try {
    if (process.platform === "win32" && child.pid) {
      spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
        windowsHide: true,
        stdio: "ignore",
      });
    } else {
      child.kill("SIGKILL");
    }
  } catch {
    try { child.kill(); } catch { /* ignore */ }
  }
}

function attachHelperStdoutPump() {
  if (!winClickHelper || winClickHelper._clickLivePumpAttached) return;
  winClickHelper._clickLivePumpAttached = true;
  winClickHelper.stdout.on("data", (chunk) => {
    helperStdoutBuffer += chunk.toString();
    const parts = helperStdoutBuffer.split(/\r?\n/);
    helperStdoutBuffer = parts.pop() || "";
    for (const line of parts) {
      if (line === "ready" || !line.trim()) continue;
      winClickHelper.emit("helper-line", line);
    }
  });
}

function writeHelperLine(text) {
  return new Promise((resolve, reject) => {
    if (!winClickHelper || winClickHelper.killed) {
      reject(new Error("Windows click helper not running"));
      return;
    }
    const payload = `${text}\n`;
    const ok = winClickHelper.stdin.write(payload, (err) => {
      if (err) reject(err);
    });
    if (ok) {
      resolve();
      return;
    }
    winClickHelper.stdin.once("drain", resolve);
    winClickHelper.stdin.once("error", reject);
  });
}

function waitHelperLine({ match, timeoutMs, label }) {
  return new Promise((resolve, reject) => {
    if (!winClickHelper || winClickHelper.killed) {
      reject(new Error("Windows click helper not running"));
      return;
    }

    const sentAt = Date.now();
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error(`${label || "helper"} timeout`));
    }, timeoutMs);

    const onLine = (line) => {
      if (match(line)) {
        cleanup();
        resolve(Date.now() - sentAt);
      }
    };

    const cleanup = () => {
      clearTimeout(timer);
      winClickHelper?.off("helper-line", onLine);
    };

    winClickHelper.on("helper-line", onLine);
  });
}

function waitHelperClickLine(clickId, px, py, timeoutMs) {
  return new Promise((resolve, reject) => {
    if (!winClickHelper || winClickHelper.killed) {
      reject(new Error("Windows click helper not running"));
      return;
    }

    const sentAt = Date.now();
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("Windows click helper click timeout"));
    }, timeoutMs);

    const onLine = (line) => {
      if (parseHelperOkLine(line, clickId, px, py)) {
        cleanup();
        resolve(Date.now() - sentAt);
        return;
      }
      const errDetail = parseHelperErrLine(line, clickId);
      if (errDetail != null) {
        cleanup();
        reject(new Error(`Windows click helper rejected: ${errDetail}`));
      }
    };

    const cleanup = () => {
      clearTimeout(timer);
      winClickHelper?.off("helper-line", onLine);
    };

    winClickHelper.on("helper-line", onLine);
  });
}

function ensureWinClickHelper() {
  if (winClickHelper && !winClickHelper.killed) {
    return Promise.resolve();
  }
  if (winClickReady && winClickHelper && !winClickHelper.killed) {
    return winClickReady;
  }
  winClickReady = null;

  const spawnGen = ++helperSpawnGen;
  winClickReady = new Promise((resolve, reject) => {
    const ps1 = helperScriptPath();
    const fs = require("fs");
    if (!fs.existsSync(ps1)) {
      winClickReady = null;
      reject(new Error("windows-click-helper.ps1 not found"));
      return;
    }

    const startedAt = Date.now();
    clickLog("helper", "starting PowerShell click helper", { script: ps1, spawnGen });

    const child = spawn("powershell.exe", [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-Sta",
      "-NoLogo",
      "-NonInteractive",
      "-File",
      ps1,
    ], {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });

    let buffer = "";
    let settled = false;
    const finish = (fn, value) => {
      if (settled || spawnGen !== helperSpawnGen) return;
      settled = true;
      clearTimeout(timer);
      fn(value);
    };

    const timer = setTimeout(() => {
      clickLogError("helper", "PowerShell click helper startup timeout", {
        spawnGen,
        waitedMs: HELPER_STARTUP_TIMEOUT_MS,
      });
      killHelperProcess(child);
      winClickReady = null;
      winClickHelper = null;
      finish(reject, new Error("PowerShell click helper startup timeout"));
    }, HELPER_STARTUP_TIMEOUT_MS);

    const fail = (err) => {
      winClickReady = null;
      winClickHelper = null;
      finish(reject, err);
    };

    const onStartupData = (chunk) => {
      if (spawnGen !== helperSpawnGen) return;
      buffer += chunk.toString();
      if (buffer.includes("ready")) {
        if (settled) return;
        child.stdout.off("data", onStartupData);
        winClickHelper = child;
        helperStdoutBuffer = "";
        attachHelperStdoutPump();
        clickLog("helper", "PowerShell click helper ready", {
          startupMs: Date.now() - startedAt,
          spawnGen,
        });
        finish(resolve);
      }
    };

    child.stdout.on("data", onStartupData);

    child.stderr.on("data", (chunk) => {
      const msg = chunk.toString().trim();
      if (msg) {
        console.warn("win-click-helper:", msg);
        clickLogWarn("helper", "PowerShell click helper stderr", { detail: msg });
      }
    });

    child.on("error", (err) => {
      clickLogError("helper", "PowerShell click helper spawn failed", { error: String(err.message || err) });
      fail(err);
    });
    child.on("exit", (code) => {
      if (spawnGen !== helperSpawnGen) return;
      clickLogWarn("helper", "PowerShell click helper exited", { code, spawnGen });
      winClickHelper = null;
      winClickReady = null;
    });
  });

  return winClickReady;
}

async function restartWinClickHelper(reason) {
  clickLog("helper", "restarting PowerShell click helper", {
    reason,
    successfulClicks: helperSuccessfulClicks,
  });
  helperSuccessfulClicks = 0;
  shutdownWinClickHelper();
  helperStdoutBuffer = "";
  await ensureWinClickHelper();
}

function clickViaHelper(px, py) {
  const clickId = ++helperClickSeq;
  const sentAt = Date.now();

  return writeHelperLine(`${clickId},${px},${py}`)
    .then(() => waitHelperClickLine(clickId, px, py, HELPER_CLICK_TIMEOUT_MS))
    .then((roundTripMs) => {
      lastHelperPingAt = Date.now();
      return {
        method: isDoubleClickEnabled() ? "powershell-helper-double" : "powershell-helper",
        x: px,
        y: py,
        durationMs: Date.now() - sentAt,
        roundTripMs,
        invokedAt: sentAt,
        clickId,
      };
    });
}

function pingHelperProcess() {
  const pingId = ++helperClickSeq;
  return writeHelperLine(`ping:${pingId}`)
    .then(() => waitHelperLine({
      match: (line) => parseHelperPongLine(line, pingId),
      timeoutMs: HELPER_PING_TIMEOUT_MS,
      label: "PowerShell click helper ping",
    }))
    .then((latencyMs) => {
      lastHelperPingAt = Date.now();
      return latencyMs;
    });
}

async function clickViaPersistentHelper(px, py) {
  if (!isWinClickHelperReady()) {
    await ensureWinClickHelper();
  }
  const result = await clickViaHelper(px, py);
  helperSuccessfulClicks += 1;
  if (helperSuccessfulClicks >= HELPER_MAX_CLICKS) {
    await restartWinClickHelper("max-clicks");
  }
  return result;
}

function shutdownWinClickHelper() {
  if (winClickHelper && !winClickHelper.killed) {
    try {
      winClickHelper.stdin.write("quit\n");
    } catch {
      /* ignore */
    }
    try {
      winClickHelper.kill();
    } catch {
      /* ignore */
    }
  }
  winClickHelper = null;
  winClickReady = null;
}

function isWinClickHelperReady() {
  return Boolean(winClickHelper && !winClickHelper.killed);
}

function getLastHelperPingAt() {
  return lastHelperPingAt;
}

module.exports = {
  ensureWinClickHelper,
  clickViaPersistentHelper,
  pingHelperProcess,
  shutdownWinClickHelper,
  isWinClickHelperReady,
  getLastHelperPingAt,
};
