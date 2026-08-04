/**
 * Persistent Windows click helper — PowerShell (mac dinh) hoac native exe (tuy chon).
 * Protocol stdin/stdout: ready | id,x,y | ping:id | quit → ok:/err:/pong:
 */

const { spawn } = require("child_process");
const fs = require("fs");
const {
  windowsClickNativeHelperPath,
  windowsClickHelperPath,
} = require("./paths");
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
let activeHelperKind = null;

const HELPER_STARTUP_TIMEOUT_MS = 12000;
const HELPER_CLICK_TIMEOUT_MS = 3000;
const HELPER_PING_TIMEOUT_MS = 1500;
const HELPER_MAX_CLICKS = Math.max(
  20,
  Number(process.env.DESKTOP_CLICK_HELPER_MAX_CLICKS) || 500
);

function resolveHelperBackend() {
  const pref = String(process.env.DESKTOP_CLICK_HELPER || "powershell").trim().toLowerCase();
  const nativePath = windowsClickNativeHelperPath();
  const psPath = windowsClickHelperPath();
  const nativeExists = fs.existsSync(nativePath);
  const psExists = fs.existsSync(psPath);

  if (pref === "powershell" || pref === "ps") {
    return psExists ? { kind: "powershell", cmd: "powershell.exe", args: psArgs(psPath) } : null;
  }
  if (pref === "native" || pref === "exe") {
    return nativeExists ? { kind: "native", cmd: nativePath, args: [] } : null;
  }
  // auto: PowerShell truoc (delay thap hon), native exe fallback
  if (psExists) {
    return { kind: "powershell", cmd: "powershell.exe", args: psArgs(psPath) };
  }
  if (nativeExists) {
    return { kind: "native", cmd: nativePath, args: [] };
  }
  return null;
}

function psArgs(psPath) {
  return [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-Sta",
    "-NoLogo",
    "-NonInteractive",
    "-File",
    psPath,
  ];
}

function helperMethodSuffix() {
  const double = isDoubleClickEnabled() ? "-double" : "";
  const mode = String(process.env.DESKTOP_CLICK_MODE || "absolute").trim().toLowerCase();
  const modeTag = mode && mode !== "auto" ? `-${mode}` : "";
  if (activeHelperKind === "native") {
    return `native-helper${double}`;
  }
  return `powershell-helper${modeTag}${double}`;
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

  const backend = resolveHelperBackend();
  if (!backend) {
    return Promise.reject(new Error("No Windows click helper found (native exe or .ps1)"));
  }

  const spawnGen = ++helperSpawnGen;
  winClickReady = new Promise((resolve, reject) => {
    const startedAt = Date.now();
    clickLog("helper", "starting click helper process", {
      kind: backend.kind,
      cmd: backend.cmd,
      spawnGen,
    });

    const child = spawn(backend.cmd, backend.args, {
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
      clickLogError("helper", "click helper startup timeout", {
        kind: backend.kind,
        spawnGen,
        waitedMs: HELPER_STARTUP_TIMEOUT_MS,
      });
      killHelperProcess(child);
      winClickReady = null;
      winClickHelper = null;
      activeHelperKind = null;
      finish(reject, new Error("Windows click helper startup timeout"));
    }, HELPER_STARTUP_TIMEOUT_MS);

    const fail = (err) => {
      winClickReady = null;
      winClickHelper = null;
      activeHelperKind = null;
      finish(reject, err);
    };

    const onStartupData = (chunk) => {
      if (spawnGen !== helperSpawnGen) return;
      buffer += chunk.toString();
      if (buffer.includes("ready")) {
        if (settled) return;
        child.stdout.off("data", onStartupData);
        winClickHelper = child;
        activeHelperKind = backend.kind;
        helperStdoutBuffer = "";
        attachHelperStdoutPump();
        clickLog("helper", "click helper ready", {
          kind: backend.kind,
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
        clickLogWarn("helper", "click helper stderr", { kind: backend.kind, detail: msg });
      }
    });

    child.on("error", (err) => {
      clickLogError("helper", "click helper spawn failed", {
        kind: backend.kind,
        error: String(err.message || err),
      });
      fail(err);
    });
    child.on("exit", (code) => {
      if (spawnGen !== helperSpawnGen) return;
      clickLogWarn("helper", "click helper exited", { kind: activeHelperKind, code, spawnGen });
      winClickHelper = null;
      winClickReady = null;
      activeHelperKind = null;
    });
  });

  return winClickReady;
}

async function restartWinClickHelper(reason) {
  clickLog("helper", "restarting click helper", {
    kind: activeHelperKind,
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
        method: helperMethodSuffix(),
        x: px,
        y: py,
        durationMs: Date.now() - sentAt,
        roundTripMs,
        invokedAt: sentAt,
        clickId,
        helperKind: activeHelperKind,
      };
    });
}

function pingHelperProcess() {
  const pingId = ++helperClickSeq;
  return writeHelperLine(`ping:${pingId}`)
    .then(() => waitHelperLine({
      match: (line) => parseHelperPongLine(line, pingId),
      timeoutMs: HELPER_PING_TIMEOUT_MS,
      label: "click helper ping",
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
  activeHelperKind = null;
}

function isWinClickHelperReady() {
  return Boolean(winClickHelper && !winClickHelper.killed);
}

function getLastHelperPingAt() {
  return lastHelperPingAt;
}

function getActiveHelperKind() {
  return activeHelperKind;
}

module.exports = {
  ensureWinClickHelper,
  clickViaPersistentHelper,
  pingHelperProcess,
  shutdownWinClickHelper,
  isWinClickHelperReady,
  getLastHelperPingAt,
  getActiveHelperKind,
  resolveHelperBackend,
};
