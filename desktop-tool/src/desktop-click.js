const { execFile, spawn } = require("child_process");
const { promisify } = require("util");
const fs = require("fs");
const os = require("os");
const path = require("path");

const execFileAsync = promisify(execFile);
const { windowsClickHelperPath } = require("./paths");
const { clickLog, clickLogWarn, clickLogError } = require("./click-log");
const { isCurrentClickGeneration } = require("./click-scheduler");

let winClickHelper = null;
let winClickReady = null;
let winClickQueue = Promise.resolve();
let helperClickSeq = 0;
let helperSpawnGen = 0;
let helperSuccessfulClicks = 0;
const HELPER_STARTUP_TIMEOUT_MS = 12000;
const HELPER_CLICK_TIMEOUT_MS = 3000;
const HELPER_MAX_CLICKS = Math.max(
  20,
  Number(process.env.DESKTOP_CLICK_HELPER_MAX_CLICKS) || 120
);
/** Stdout tích lũy — parse theo dòng, tránh nhầm ok cũ. */
let helperStdoutBuffer = "";

function parseHelperOkLine(line, clickId, px, py) {
  const trimmed = String(line || "").trim();
  const expected = `ok:${clickId},${px},${py}`;
  return trimmed === expected || trimmed.startsWith(`${expected}\r`);
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

function resolveCliclickBin() {
  const envBin = String(process.env.DESKTOP_CLICLICK_BIN || "").trim();
  if (envBin && fs.existsSync(envBin)) return envBin;

  const bundled = path.join(__dirname, "..", "resources", "bin", "darwin", "cliclick");
  if (fs.existsSync(bundled)) return bundled;

  const pathCandidates = [
    "/opt/homebrew/bin/cliclick",
    "/usr/local/bin/cliclick",
  ];
  for (const candidate of pathCandidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return "cliclick";
}

function isStaleClickRequest(clickGen) {
  return clickGen != null && !isCurrentClickGeneration(clickGen);
}

function dropStaleClick(clickGen, stage) {
  clickLog("skip", `drop stale click at ${stage}`, { clickGen });
  const err = new Error("stale click cancelled");
  err.code = "CLICK_STALE";
  throw err;
}

async function restartWinClickHelper(reason) {
  clickLog("helper", "restarting Windows click helper", {
    reason,
    successfulClicks: helperSuccessfulClicks,
  });
  helperSuccessfulClicks = 0;
  shutdownWinClickHelper();
  helperStdoutBuffer = "";
  await ensureWinClickHelper();
}

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

function ensureWinClickHelper() {
  if (winClickHelper && !winClickHelper.killed) {
    return Promise.resolve();
  }
  if (winClickReady) return winClickReady;

  const spawnGen = ++helperSpawnGen;
  winClickReady = new Promise((resolve, reject) => {
    const ps1 = helperScriptPath();
    if (!fs.existsSync(ps1)) {
      winClickReady = null;
      reject(new Error("windows-click-helper.ps1 not found"));
      return;
    }

    const startedAt = Date.now();
    clickLog("helper", "starting Windows click helper", { script: ps1, spawnGen });

    const child = spawn("powershell.exe", [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-Sta",
      "-NoLogo",
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
      clickLogError("helper", "Windows click helper startup timeout", {
        spawnGen,
        waitedMs: HELPER_STARTUP_TIMEOUT_MS,
      });
      killHelperProcess(child);
      winClickReady = null;
      winClickHelper = null;
      finish(reject, new Error("Windows click helper startup timeout"));
    }, HELPER_STARTUP_TIMEOUT_MS);

    const fail = (err) => {
      winClickReady = null;
      winClickHelper = null;
      finish(reject, err);
    };

    child.stdout.on("data", (chunk) => {
      if (spawnGen !== helperSpawnGen) return;
      buffer += chunk.toString();
      if (buffer.includes("ready")) {
        winClickHelper = child;
        helperStdoutBuffer = "";
        attachHelperStdoutPump();
        clickLog("helper", "Windows click helper ready", {
          startupMs: Date.now() - startedAt,
          spawnGen,
        });
        finish(resolve);
      }
    });

    child.stderr.on("data", (chunk) => {
      const msg = chunk.toString().trim();
      if (msg) {
        console.warn("win-click-helper:", msg);
        clickLogWarn("helper", "Windows click helper stderr", { detail: msg });
      }
    });

    child.on("error", (err) => {
      clickLogError("helper", "Windows click helper spawn failed", { error: String(err.message || err) });
      fail(err);
    });
    child.on("exit", (code) => {
      if (spawnGen !== helperSpawnGen) return;
      clickLogWarn("helper", "Windows click helper exited", { code, spawnGen });
      winClickHelper = null;
      winClickReady = null;
    });
  });

  return winClickReady;
}

function clickViaHelper(px, py) {
  return new Promise((resolve, reject) => {
    if (!winClickHelper || winClickHelper.killed) {
      reject(new Error("Windows click helper not running"));
      return;
    }

    const clickId = ++helperClickSeq;
    const sentAt = Date.now();
    const expected = `ok:${clickId},${px},${py}`;
    const timer = setTimeout(() => {
      cleanup();
      clickLogError("click", "Windows click helper timeout", {
        clickId, x: px, y: py, waitedMs: HELPER_CLICK_TIMEOUT_MS,
      });
      reject(new Error("Windows click timeout"));
    }, HELPER_CLICK_TIMEOUT_MS);

    const onLine = (line) => {
      if (parseHelperOkLine(line, clickId, px, py)) {
        cleanup();
        const durationMs = Date.now() - sentAt;
        resolve({
          method: "powershell-helper",
          x: px,
          y: py,
          durationMs,
          invokedAt: sentAt,
          clickId,
        });
      } else if (/^ok:/.test(String(line || "").trim())) {
        clickLogWarn("helper", "ignored mismatched helper ok", {
          line: String(line).trim(),
          expected,
        });
      }
    };

    const cleanup = () => {
      clearTimeout(timer);
      winClickHelper?.off("helper-line", onLine);
    };

    winClickHelper.on("helper-line", onLine);
    try {
      winClickHelper.stdin.write(`${clickId},${px},${py}\n`);
    } catch (err) {
      cleanup();
      reject(err);
    }
  });
}

async function clickScreenPointWindowsFallback(px, py) {
  const invokedAt = Date.now();
  clickLogWarn("click", "Windows click fallback (spawn PowerShell)", { x: px, y: py });
  const script = [
    "$sig = @'",
    "[DllImport(\"user32.dll\")] public static extern bool SetCursorPos(int X, int Y);",
    "[DllImport(\"user32.dll\")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint cButtons, uint dwExtraInfo);",
    "'@",
    '$null = Add-Type -MemberDefinition $sig -Name WinMouse -Namespace ClickLive -PassThru',
    `[ClickLive.WinMouse]::SetCursorPos(${px}, ${py}) | Out-Null`,
    "[ClickLive.WinMouse]::mouse_event(0x0002, 0, 0, 0, 0)",
    "[ClickLive.WinMouse]::mouse_event(0x0004, 0, 0, 0, 0)",
    "",
  ].join("\r\n");

  const ps1 = path.join(os.tmpdir(), `click-live-click-${process.pid}-${Date.now()}.ps1`);
  fs.writeFileSync(ps1, script, "utf8");

  try {
    await execFileAsync("powershell.exe", [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      ps1,
    ]);
  } catch (err) {
    const detail = String(err.stderr || err.message || err).trim();
    throw new Error(detail || "Windows click failed");
  } finally {
    try {
      fs.unlinkSync(ps1);
    } catch {
      /* ignore */
    }
  }

  const durationMs = Date.now() - invokedAt;
  clickLogWarn("click", "Windows click fallback done", { x: px, y: py, durationMs });
  return { method: "powershell", x: px, y: py, durationMs, invokedAt };
}

async function clickScreenPointWindowsInner(px, py, options = {}) {
  const { clickGen } = options;
  if (isStaleClickRequest(clickGen)) {
    dropStaleClick(clickGen, "helper-inner");
  }
  try {
    await ensureWinClickHelper();
    if (isStaleClickRequest(clickGen)) {
      dropStaleClick(clickGen, "helper-after-ready");
    }
    const result = await clickViaHelper(px, py);
    helperSuccessfulClicks += 1;
    if (helperSuccessfulClicks >= HELPER_MAX_CLICKS) {
      await restartWinClickHelper("max-clicks");
    }
    return result;
  } catch (err) {
    if (err?.code === "CLICK_STALE") throw err;
    clickLogWarn("click", "Windows click helper failed, using fallback", {
      error: String(err.message || err),
      x: px,
      y: py,
    });
    console.warn("Windows click helper failed, fallback:", err.message || err);
    if (isStaleClickRequest(clickGen)) {
      dropStaleClick(clickGen, "fallback-blocked");
    }
    return clickScreenPointWindowsFallback(px, py);
  }
}

function clickScreenPointWindows(px, py, options = {}) {
  const task = winClickQueue
    .catch(() => {})
    .then(() => {
      if (isStaleClickRequest(options.clickGen)) {
        dropStaleClick(options.clickGen, "queue");
      }
      return clickScreenPointWindowsInner(px, py, options);
    });
  winClickQueue = task.catch(() => {});
  return task;
}

function warmUpWinClickHelper() {
  if (process.platform !== "win32") return Promise.resolve();
  return ensureWinClickHelper()
    .then(() => {
      clickLog("helper", "Windows click helper warmup OK");
    })
    .catch((err) => {
      clickLogWarn("helper", "Windows click helper warmup failed", {
        error: String(err.message || err),
      });
      console.warn("Windows click helper warmup failed:", err.message || err);
      winClickReady = null;
      winClickHelper = null;
    });
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

async function clickScreenPointDarwin(px, py, options = {}) {
  const { clickGen } = options;
  if (isStaleClickRequest(clickGen)) {
    dropStaleClick(clickGen, "darwin");
  }
  const cliclick = resolveCliclickBin();
  const invokedAt = Date.now();
  try {
    await execFileAsync(cliclick, [`c:${px},${py}`]);
    const durationMs = Date.now() - invokedAt;
    return { method: "cliclick", x: px, y: py, durationMs, invokedAt };
  } catch (err) {
    const detail = String(err.stderr || err.message || err).trim();
    if (/could not be found|ENOENT/i.test(detail) || err.code === "ENOENT") {
      throw new Error(
        "Chua cai cliclick. Chay: brew install cliclick — roi bat quyen Accessibility cho Electron."
      );
    }
    if (/Accessibility|assistive|not permitted|-25212|AXError/i.test(detail)) {
      throw new Error(
        "Thieu quyen Accessibility. System Settings → Privacy → Accessibility → bat cho Electron."
      );
    }
    throw new Error(detail || "Khong click duoc desktop");
  }
}

async function clickScreenPoint(x, y, options = {}) {
  const px = Math.round(Number(x));
  const py = Math.round(Number(y));
  if (!Number.isFinite(px) || !Number.isFinite(py)) {
    throw new Error("Toa do click khong hop le");
  }
  if (px < 0 || py < 0 || px > 65535 || py > 65535) {
    throw new Error(`Toa do click ngoai pham vi: ${px},${py}`);
  }

  clickLog("click", "invoke clickScreenPoint", {
    x: px,
    y: py,
    clickGen: options.clickGen ?? null,
  });
  if (process.platform === "win32") {
    return clickScreenPointWindows(px, py, options);
  }
  if (process.platform === "darwin") {
    return clickScreenPointDarwin(px, py, options);
  }
  throw new Error(`Desktop click chua ho tro nen tang: ${process.platform}`);
}

function isWinClickHelperReady() {
  return Boolean(winClickHelper && !winClickHelper.killed);
}

module.exports = {
  clickScreenPoint,
  resolveCliclickBin,
  warmUpWinClickHelper,
  shutdownWinClickHelper,
  parseHelperOkLine,
  isWinClickHelperReady,
};
