/** Bù độ trễ click OS — học từ clickDurationMs + hiệu chỉnh drift thực tế (closed-loop). */

const fs = require("fs");
const path = require("path");

const MAX_SAMPLES = 24;
const DRIFT_EMA_ALPHA = 0.3;
const DRIFT_CORRECTION_GAIN = 0.45;
const MAX_DRIFT_CORRECTION_MS = 45;

const samples = [];
let driftEma = null;
let driftSampleCount = 0;
let calibrationLoaded = false;
let saveTimer = null;

function platformDefaultLeadMs() {
  if (process.platform === "win32") return 100;
  return 40;
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

/** Ghi nhận sau click có TIME — duration (latency) + drift (đúng/muộn/sớm vs overlay 0.0s). */
function recordClickOutcome({ clickDurationMs, driftFromDisplayMs } = {}) {
  if (clickDurationMs != null) recordClickDuration(clickDurationMs);
  if (driftFromDisplayMs != null) recordClickDrift(driftFromDisplayMs);
}

function percentile(sorted, ratio) {
  if (!sorted.length) return 0;
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.floor(sorted.length * ratio)));
  return sorted[idx];
}

function durationBasedLeadMs() {
  const floor = process.platform === "win32" ? 35 : 15;
  const ceiling = process.platform === "win32" ? 220 : 100;
  const fallback = platformDefaultLeadMs();

  if (samples.length < 3) return fallback;

  const sorted = [...samples].sort((a, b) => a - b);
  const p95 = percentile(sorted, 0.95);
  const margin = process.platform === "win32" ? 20 : 10;
  return Math.min(ceiling, Math.max(floor, p95 + margin));
}

function driftCorrectionMs() {
  if (driftEma == null || driftSampleCount < 2) return 0;
  const raw = driftEma * DRIFT_CORRECTION_GAIN;
  return Math.round(Math.max(-MAX_DRIFT_CORRECTION_MS, Math.min(MAX_DRIFT_CORRECTION_MS, raw)));
}

function resolveClickExecutionLeadMs() {
  loadCalibration();

  const env = Number(process.env.DESKTOP_CLICK_EXECUTION_LEAD_MS);
  if (Number.isFinite(env) && env >= 0) return Math.round(env);

  const floor = process.platform === "win32" ? 35 : 15;
  const ceiling = process.platform === "win32" ? 220 : 100;
  const base = durationBasedLeadMs();
  const corrected = base + driftCorrectionMs();
  return Math.min(ceiling, Math.max(floor, corrected));
}

function getClickLeadStats() {
  loadCalibration();
  const baseLeadMs = durationBasedLeadMs();
  const correctionMs = driftCorrectionMs();
  return {
    samples: samples.length,
    driftSamples: driftSampleCount,
    driftEma,
    baseLeadMs,
    correctionMs,
    leadMs: resolveClickExecutionLeadMs(),
    recent: samples.slice(-5),
  };
}

function resetClickLeadSamples() {
  samples.length = 0;
  driftEma = null;
  driftSampleCount = 0;
  calibrationLoaded = true;
  scheduleSaveCalibration();
}

module.exports = {
  recordClickDuration,
  recordClickDrift,
  recordClickOutcome,
  resolveClickExecutionLeadMs,
  platformDefaultLeadMs,
  getClickLeadStats,
  resetClickLeadSamples,
};
