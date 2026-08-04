const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const {
  recordClickDuration,
  recordClickOutcome,
  resolveClickExecutionLeadMs,
  getSessionClickTiming,
  resetClickLeadSamples,
  getClickLeadStats,
  isTrustworthyClickOutcome,
} = require("../src/click-lead");

test("adaptive lead stays within platform bounds", () => {
  delete process.env.DESKTOP_CLICK_EXECUTION_LEAD_MS;
  process.env.DESKTOP_TOOL_USER_DATA = fs.mkdtempSync(path.join(os.tmpdir(), "click-lead-"));
  resetClickLeadSamples();
  for (let i = 0; i < 8; i += 1) recordClickDuration(45);
  const after = resolveClickExecutionLeadMs();
  assert.ok(after >= 15);
  assert.ok(after <= 220);
});

test("env DESKTOP_CLICK_EXECUTION_LEAD_MS overrides adaptive", () => {
  resetClickLeadSamples();
  process.env.DESKTOP_CLICK_EXECUTION_LEAD_MS = "0";
  assert.equal(resolveClickExecutionLeadMs(), 0);
  delete process.env.DESKTOP_CLICK_EXECUTION_LEAD_MS;
});

test("session click timing stays fixed across jobs", () => {
  delete process.env.DESKTOP_CLICK_EXECUTION_LEAD_MS;
  process.env.DESKTOP_TOOL_USER_DATA = fs.mkdtempSync(path.join(os.tmpdir(), "click-lead-drift-"));
  resetClickLeadSamples();
  for (let i = 0; i < 6; i += 1) recordClickDuration(30);
  const t1 = getSessionClickTiming();
  for (let i = 0; i < 5; i += 1) {
    recordClickOutcome({
      clickDurationMs: 30,
      driftFromDisplayMs: -110,
      trustworthy: true,
    });
  }
  const t2 = getSessionClickTiming();
  assert.equal(t1.executeAdvanceMs, t2.executeAdvanceMs);
  assert.equal(t1.clickLatencyMs, t2.clickLatencyMs);
  const stats = getClickLeadStats();
  assert.ok(stats.targetOverlayMs >= 40);
});

test("isTrustworthyClickOutcome rejects late fire and huge drift", () => {
  assert.equal(isTrustworthyClickOutcome({ fireDelayMs: 0, driftFromDisplayMs: -80 }), false);
  assert.equal(isTrustworthyClickOutcome({ fireDelayMs: 5000, driftFromDisplayMs: 2500 }), false);
  assert.equal(isTrustworthyClickOutcome({ fireDelayMs: 5000, driftFromDisplayMs: -85 }), true);
});
