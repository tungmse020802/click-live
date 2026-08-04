/** Bù độ trễ click OS — canh thời điểm chạm chuột cố định so với TIME+offset. */

const fs = require("fs");
const path = require("path");

const MAX_SAMPLES = 24;
const DRIFT_EMA_ALPHA = 0.3;
const MAX_OUTLIER_DRIFT_MS = 180;
const MIN_TRUSTWORTHY_FIRE_MS = 500;

const samples = [];
let driftEma = null;
let driftSampleCount = 0;
/** Cố định cả session — mọi job cùng targetBefore + latency. */
let sessionTiming = null;
let calibrationLoaded = false;
let saveTimer = null;

function platformDefaultLeadMs() {
  if (process.platform === "win32") return 100;
  return 40;
}

function resolveTargetOverlayRemainingMs() {
  const env = Number(process.env.DESKTOP_CLICK_TARGET_OVERLAY_MS);
  if (Number.isFinite(env) && env >= 0) return Math.round(env);
  return process.platform === "win32" ? 80 : 40;
}

function advanceBounds() {
  return process.platform === "win32"
    ? { floor: 35, ceiling: 220 }
    : { floor: 15, ceiling: 100 };
}

function clampAdvance(ms) {
  const { floor, ceiling } = advanceBounds();
  return Math.min(ceiling, Math.max(floor, Math.round(ms)));
}

function resolveCalibrationPath() {
  const envDir = String(process.env.DESKTOP_TOOL_USER_DATA || "").trim();
  if (envDir) return path.join(path.resolve(envDir), "click-lead.json");

  try {
    const { app } = require("electron");
    if (app?.getPath) {
      return path.join(app.getPath("userData"), "click-lead.json");
    }
  } catch {
    /* chạy ngoài Electron */
  }

  return path.join(__dirname, "..", "click-lead.json");
}

function loadCalibration() {
  if (calibrationLoaded) return;
  calibrationLoaded = true;

  try {
    const raw = fs.readFileSync(resolveCalibrationPath(), "utf8");
    const data = JSON.parse(raw);
    if (Array.isArray(data.samples)) {
      samples.length = 0;
      for (const n of data.samples.slice(-MAX_SAMPLES)) {
        const v = Number(n);
        if (Number.isFinite(v) && v >= 0) samples.push(Math.round(v));
      }
    }
    if (Number.isFinite(Number(data.driftEma))) {
      driftEma = Math.round(Number(data.driftEma));
    }
    if (Number.isFinite(Number(data.driftSampleCount))) {
      driftSampleCount = Math.max(0, Math.round(Number(data.driftSampleCount)));
    }
  } catch {
    /* chưa có file hoặc lỗi parse — bắt đầu mới */
  }
}

function scheduleSaveCalibration() {
  if (saveTimer) return;
  saveTimer = setTimeout(() => {
    saveTimer = null;
    try {
      const file = resolveCalibrationPath();
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, JSON.stringify({
        samples,
        driftEma,
        driftSampleCount,
        updatedAt: new Date().toISOString(),
      }), "utf8");
    } catch {
      /* ignore */
    }
  }, 800);
}

function recordClickDuration(ms) {
  loadCalibration();
  const n = Number(ms);
  if (!Number.isFinite(n) || n < 0) return;
  samples.push(Math.round(n));
  while (samples.length > MAX_SAMPLES) samples.shift();
  scheduleSaveCalibration();
}

function recordClickDrift(driftMs) {
  loadCalibration();
  const n = Number(driftMs);
  if (!Number.isFinite(n)) return;
  driftSampleCount += 1;
  if (driftEma == null) {
    driftEma = Math.round(n);
  } else {
    driftEma = Math.round(driftEma * (1 - DRIFT_EMA_ALPHA) + n * DRIFT_EMA_ALPHA);
  }
  scheduleSaveCalibration();
}

function percentile(sorted, ratio) {
  if (!sorted.length) return 0;
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.floor(sorted.length * ratio)));
  return sorted[idx];
}

function predictClickLatencyMs() {
  loadCalibration();
  try {
    const { getHelperLatencyEstimateMs } = require("./desktop-click");
    const warm = getHelperLatencyEstimateMs();
    if (Number.isFinite(warm) && warm > 0) return Math.round(warm);
  } catch {
    /* ngoài Electron hoặc chưa warm */
  }
  const fallback = process.platform === "win32" ? 12 : 8;
  if (samples.length < 3) return fallback;
  const sorted = [...samples].sort((a, b) => a - b);
  const p75 = Math.round(percentile(sorted, 0.75));
  return Math.max(fallback, p75);
}

function buildSessionClickTiming() {
  const targetBeforeMs = resolveTargetOverlayRemainingMs();
  const clickLatencyMs = predictClickLatencyMs();
  const executeAdvanceMs = clampAdvance(targetBeforeMs + clickLatencyMs);
  return { targetBeforeMs, clickLatencyMs, executeAdvanceMs };
}

/** Timing cố định cả session — mọi job dùng cùng mốc chạm chuột. */
function getSessionClickTiming() {
  loadCalibration();
  const env = Number(process.env.DESKTOP_CLICK_EXECUTION_LEAD_MS);
  if (Number.isFinite(env) && env >= 0) {
    const advance = Math.round(env);
    return {
      targetBeforeMs: resolveTargetOverlayRemainingMs(),
      clickLatencyMs: Math.max(0, advance - resolveTargetOverlayRemainingMs()),
      executeAdvanceMs: advance,
    };
  }
  if (!sessionTiming) {
    sessionTiming = buildSessionClickTiming();
  }
  return sessionTiming;
}

/** Gọi sau warmup helper — cập nhật latency đo thực tế (pipe ấm). */
function refreshSessionClickTiming() {
  if (Number.isFinite(Number(process.env.DESKTOP_CLICK_EXECUTION_LEAD_MS))) {
    return getSessionClickTiming();
  }
  sessionTiming = buildSessionClickTiming();
  return sessionTiming;
}

function resolveExecuteAdvanceMs() {
  return getSessionClickTiming().executeAdvanceMs;
}

function resolveClickExecutionLeadMs() {
  return resolveExecuteAdvanceMs();
}

function isTrustworthyClickOutcome({ driftFromDisplayMs, fireDelayMs, waitDriftMs } = {}) {
  if (fireDelayMs != null && fireDelayMs < MIN_TRUSTWORTHY_FIRE_MS) return false;
  if (waitDriftMs != null && Math.abs(waitDriftMs) > 600) return false;
  if (driftFromDisplayMs != null && Math.abs(driftFromDisplayMs) > MAX_OUTLIER_DRIFT_MS) return false;
  return true;
}

/** Ghi latency/drift để thống kê — không đổi timing giữa các job trong session. */
function recordClickOutcome({
  clickDurationMs,
  driftFromDisplayMs,
  trustworthy = true,
} = {}) {
  if (clickDurationMs != null) recordClickDuration(clickDurationMs);
  if (!trustworthy || driftFromDisplayMs == null) return;
  if (Math.abs(driftFromDisplayMs) > MAX_OUTLIER_DRIFT_MS) return;
  recordClickDrift(driftFromDisplayMs);
}

function getClickLeadStats() {
  loadCalibration();
  const timing = getSessionClickTiming();
  return {
    samples: samples.length,
    driftSamples: driftSampleCount,
    driftEma,
    targetOverlayMs: timing.targetBeforeMs,
    clickLatencyMs: timing.clickLatencyMs,
    sessionAdvanceMs: timing.executeAdvanceMs,
    leadMs: timing.executeAdvanceMs,
    recent: samples.slice(-5),
  };
}

function resetClickLeadSamples() {
  samples.length = 0;
  driftEma = null;
  driftSampleCount = 0;
  sessionTiming = null;
  calibrationLoaded = true;
  scheduleSaveCalibration();
}

module.exports = {
  recordClickDuration,
  recordClickDrift,
  recordClickOutcome,
  resolveClickExecutionLeadMs,
  resolveExecuteAdvanceMs,
  resolveTargetOverlayRemainingMs,
  predictClickLatencyMs,
  getSessionClickTiming,
  refreshSessionClickTiming,
  isTrustworthyClickOutcome,
  platformDefaultLeadMs,
  getClickLeadStats,
  resetClickLeadSamples,
};
