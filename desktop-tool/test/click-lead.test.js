const test = require("node:test");
const assert = require("node:assert/strict");
const {
  recordClickDuration,
  resolveClickExecutionLeadMs,
  resetClickLeadSamples,
} = require("../src/click-lead");

test("adaptive lead stays within platform bounds", () => {
  delete process.env.DESKTOP_CLICK_EXECUTION_LEAD_MS;
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
