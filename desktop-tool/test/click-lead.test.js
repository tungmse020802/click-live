const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const {
  recordClickDuration,
  recordClickOutcome,
  resolveClickExecutionLeadMs,
  resetClickLeadSamples,
  getClickLeadStats,
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

test("drift correction reduces lead when clicks land early", () => {
  delete process.env.DESKTOP_CLICK_EXECUTION_LEAD_MS;
  process.env.DESKTOP_TOOL_USER_DATA = fs.mkdtempSync(path.join(os.tmpdir(), "click-lead-drift-"));
  resetClickLeadSamples();
  for (let i = 0; i < 6; i += 1) recordClickDuration(80);
  const base = resolveClickExecutionLeadMs();
  for (let i = 0; i < 5; i += 1) {
    recordClickOutcome({ clickDurationMs: 80, driftFromDisplayMs: -30 });
  }
  const adjusted = resolveClickExecutionLeadMs();
  assert.ok(adjusted < base, `expected ${adjusted} < ${base}`);
  const stats = getClickLeadStats();
  assert.ok(stats.correctionMs < 0);
});
