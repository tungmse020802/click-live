const { execFile } = require("child_process");
const { promisify } = require("util");
const fs = require("fs");
const path = require("path");

const execFileAsync = promisify(execFile);
const { windowsClickHelperPath } = require("./paths");
const { clickLog, clickLogWarn } = require("./click-log");
const { isCurrentClickGeneration } = require("./click-scheduler");
const {
  parseHelperOkLine,
  parseHelperPongLine,
  parseHelperErrLine,
} = require("./windows-click-protocol");
const {
  initWindowsSendInput,
  clickAt: sendInputClickAt,
  pingLatencyMs,
  isWindowsSendInputReady,
  getInitError,
} = require("./windows-sendinput");

let winClickQueue = Promise.resolve();
const clickLatencySamples = [];
const LATENCY_MAX_SAMPLES = 16;
const LATENCY_WARMUP_PINGS = Math.max(
  1,
  Number(process.env.DESKTOP_CLICK_HELPER_WARMUP_PINGS) || 3
);

function recordClickLatency(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n) || n < 0) return;
  clickLatencySamples.push(Math.round(n));
  while (clickLatencySamples.length > LATENCY_MAX_SAMPLES) clickLatencySamples.shift();
}

function percentile(sorted, ratio) {
  if (!sorted.length) return 0;
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.floor(sorted.length * ratio)));
  return sorted[idx];
}

/** Ước lượng latency click Windows — dùng cho canh giờ. */
function getHelperLatencyEstimateMs() {
  if (!clickLatencySamples.length) {
    return process.platform === "win32" ? 3 : 8;
  }
  const sorted = [...clickLatencySamples].sort((a, b) => a - b);
  return Math.round(percentile(sorted, 0.75));
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

function helperScriptPath() {
  return windowsClickHelperPath();
}

async function clickScreenPointWindowsFallback(px, py) {
  const invokedAt = Date.now();
  clickLogWarn("click", "Windows click fallback (PowerShell SendInput)", { x: px, y: py });
  const ps1 = helperScriptPath();
  if (!fs.existsSync(ps1)) {
    throw new Error("windows-click-helper.ps1 not found");
  }

  try {
    await execFileAsync("powershell.exe", [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-Sta",
      "-NoLogo",
      "-NonInteractive",
      "-File",
      ps1,
      "-Once",
      "-X",
      String(px),
      "-Y",
      String(py),
    ]);
  } catch (err) {
    const detail = String(err.stderr || err.message || err).trim();
    throw new Error(detail || "Windows click failed");
  }

  const durationMs = Date.now() - invokedAt;
  clickLogWarn("click", "Windows click fallback done", { x: px, y: py, durationMs });
  return { method: "powershell-sendinput", x: px, y: py, durationMs, invokedAt };
}

async function clickViaSendInput(px, py) {
  const invokedAt = Date.now();
  if (!initWindowsSendInput()) {
    throw new Error(getInitError() || "SendInput init failed");
  }

  const result = sendInputClickAt(px, py);
  const durationMs = Date.now() - invokedAt;
  recordClickLatency(durationMs);

  if (!result.ok) {
    throw new Error(`SendInput rejected: ${result.detail}`);
  }

  return {
    method: "sendinput",
    x: px,
    y: py,
    durationMs,
    invokedAt,
    actualX: result.actualX,
    actualY: result.actualY,
  };
}

async function clickScreenPointWindowsInner(px, py, options = {}) {
  const { clickGen } = options;
  if (isStaleClickRequest(clickGen)) {
    dropStaleClick(clickGen, "win-inner");
  }

  try {
    if (isStaleClickRequest(clickGen)) {
      dropStaleClick(clickGen, "win-before-click");
    }
    return await clickViaSendInput(px, py);
  } catch (err) {
    if (err?.code === "CLICK_STALE") throw err;
    clickLogWarn("click", "Windows SendInput failed, using PowerShell fallback", {
      error: String(err.message || err),
      x: px,
      y: py,
    });
    console.warn("Windows SendInput failed, fallback:", err.message || err);
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

async function primeClickLatency() {
  if (process.platform !== "win32") return null;
  if (!initWindowsSendInput()) return null;

  const samples = [];
  for (let i = 0; i < LATENCY_WARMUP_PINGS; i += 1) {
    try {
      samples.push(pingLatencyMs());
    } catch (err) {
      clickLogWarn("helper", "Windows SendInput ping failed", {
        error: String(err.message || err),
        attempt: i + 1,
      });
    }
  }
  if (!samples.length) return null;

  for (const ms of samples) recordClickLatency(ms);
  const sorted = [...samples].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  clickLog("helper", "Windows SendInput latency primed", {
    medianMs: median,
    samples,
    estimateMs: getHelperLatencyEstimateMs(),
  });
  try {
    const { refreshSessionClickTiming } = require("./click-lead");
    refreshSessionClickTiming();
  } catch {
    /* ignore */
  }
  return median;
}

function warmUpWinClickHelper() {
  if (process.platform !== "win32") return Promise.resolve();
  return Promise.resolve()
    .then(() => {
      if (!initWindowsSendInput()) {
        throw new Error(getInitError() || "SendInput init failed");
      }
      return primeClickLatency();
    })
    .then(() => {
      clickLog("helper", "Windows SendInput warmup OK", {
        estimateMs: getHelperLatencyEstimateMs(),
      });
    })
    .catch((err) => {
      clickLogWarn("helper", "Windows SendInput warmup failed", {
        error: String(err.message || err),
      });
      console.warn("Windows SendInput warmup failed:", err.message || err);
    });
}

function shutdownWinClickHelper() {
  /* koffi in-process — không cần shutdown */
}

function pingHelper() {
  const started = Date.now();
  pingLatencyMs();
  const latencyMs = Date.now() - started;
  recordClickLatency(latencyMs);
  return Promise.resolve(latencyMs);
}

function isWinClickHelperReady() {
  return isWindowsSendInputReady();
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
    helperLatencyMs: getHelperLatencyEstimateMs(),
  });
  if (process.platform === "win32") {
    return clickScreenPointWindows(px, py, options);
  }
  if (process.platform === "darwin") {
    return clickScreenPointDarwin(px, py, options);
  }
  throw new Error(`Desktop click chua ho tro nen tang: ${process.platform}`);
}

module.exports = {
  clickScreenPoint,
  resolveCliclickBin,
  warmUpWinClickHelper,
  shutdownWinClickHelper,
  parseHelperOkLine,
  parseHelperPongLine,
  parseHelperErrLine,
  pingHelper,
  getHelperLatencyEstimateMs,
  isWinClickHelperReady,
};
