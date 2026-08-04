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
  assert.ok(after <= 900);
});

test("session click timing adapts when clicks land late", () => {
  delete process.env.DESKTOP_CLICK_EXECUTION_LEAD_MS;
  process.env.DESKTOP_TOOL_USER_DATA = fs.mkdtempSync(path.join(os.tmpdir(), "click-lead-drift-"));
  resetClickLeadSamples();
  for (let i = 0; i < 6; i += 1) recordClickDuration(30);
  const t1 = getSessionClickTiming();
  recordClickOutcome({
    clickDurationMs: 280,
    driftFromDisplayMs: 799,
    waitDriftMs: 120,
    trustworthy: true,
  });
  const t2 = getSessionClickTiming();
  assert.ok(t2.executeAdvanceMs > t1.executeAdvanceMs);
  assert.ok(t2.executeAdvanceMs <= 900);
});

test("env DESKTOP_CLICK_EXECUTION_LEAD_MS overrides adaptive", () => {
  resetClickLeadSamples();
  process.env.DESKTOP_CLICK_EXECUTION_LEAD_MS = "0";
  assert.equal(resolveClickExecutionLeadMs(), 0);
  delete process.env.DESKTOP_CLICK_EXECUTION_LEAD_MS;
});

test("isTrustworthyClickOutcome rejects late fire and huge drift", () => {
  assert.equal(isTrustworthyClickOutcome({ fireDelayMs: 0, driftFromDisplayMs: -80 }), false);
  assert.equal(isTrustworthyClickOutcome({ fireDelayMs: 5000, driftFromDisplayMs: 2500 }), false);
  assert.equal(isTrustworthyClickOutcome({ fireDelayMs: 5000, driftFromDisplayMs: -85 }), true);
});
