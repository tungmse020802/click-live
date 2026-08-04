const test = require("node:test");
const assert = require("node:assert/strict");

test("cancelActiveClickTask bumps generation so queued clicks go stale", () => {
  const scheduler = require("../src/click-scheduler");
  scheduler.reset?.();
  const gen = scheduler.currentClickGeneration();
  scheduler.nextClickGeneration();
  assert.equal(scheduler.isCurrentClickGeneration(gen), false);
});

test("parseHelperOkLine rejects legacy ok without id", () => {
  const { parseHelperOkLine } = require("../src/desktop-click");
  assert.equal(parseHelperOkLine("ok:0,100,200", 5, 100, 200), false);
  assert.equal(parseHelperOkLine("ok:5,100,200", 5, 100, 200), true);
});
