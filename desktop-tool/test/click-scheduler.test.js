const test = require("node:test");
const assert = require("node:assert/strict");
const {
  nextClickGeneration,
  isCurrentClickGeneration,
  abortClickWait,
  registerClickWaitAbort,
  clearClickWaitAbort,
} = require("../src/click-scheduler");

test("click generation invalidates older jobs", () => {
  const g1 = nextClickGeneration();
  assert.equal(isCurrentClickGeneration(g1), true);
  const g2 = nextClickGeneration();
  assert.equal(isCurrentClickGeneration(g1), false);
  assert.equal(isCurrentClickGeneration(g2), true);
});

test("abortClickWait stops registered waiter", () => {
  let aborted = false;
  registerClickWaitAbort(() => {
    aborted = true;
  });
  abortClickWait();
  assert.equal(aborted, true);
});

test("clearClickWaitAbort only clears own handler", () => {
  let n = 0;
  const fn = () => { n += 1; };
  registerClickWaitAbort(fn);
  clearClickWaitAbort(fn);
  abortClickWait();
  assert.equal(n, 0);
});
