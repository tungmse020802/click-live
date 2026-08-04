/** Bù độ trỵ click OS — tự học từ clickDurationMs gần đây. */

const MAX_SAMPLES = 24;
const samples = [];

function platformDefaultLeadMs() {
  if (process.platform === "win32") return 100;
  return 40;
}

function recordClickDuration(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n) || n < 0) return;
  samples.push(Math.round(n));
  while (samples.length > MAX_SAMPLES) samples.shift();
}

function percentile(sorted, ratio) {
  if (!sorted.length) return 0;
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.floor(sorted.length * ratio)));
  return sorted[idx];
}

function resolveClickExecutionLeadMs() {
  const env = Number(process.env.DESKTOP_CLICK_EXECUTION_LEAD_MS);
  if (Number.isFinite(env) && env >= 0) return Math.round(env);

  const floor = process.platform === "win32" ? 35 : 15;
  const ceiling = process.platform === "win32" ? 220 : 100;
  const fallback = platformDefaultLeadMs();

  if (samples.length < 3) return fallback;

  const sorted = [...samples].sort((a, b) => a - b);
  const p95 = percentile(sorted, 0.95);
  const margin = process.platform === "win32" ? 20 : 10;
  return Math.min(ceiling, Math.max(floor, p95 + margin));
}

function getClickLeadStats() {
  return {
    samples: samples.length,
    leadMs: resolveClickExecutionLeadMs(),
    recent: samples.slice(-5),
  };
}

function resetClickLeadSamples() {
  samples.length = 0;
}

module.exports = {
  recordClickDuration,
  resolveClickExecutionLeadMs,
  platformDefaultLeadMs,
  getClickLeadStats,
  resetClickLeadSamples,
};
