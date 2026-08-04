/**
 * Stress test logic: simulate rapid job opens — only latest generation may click.
 * Chạy: node test/rapid-open-stress.test.js
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const {
  nextClickGeneration,
  currentClickGeneration,
  isCurrentClickGeneration,
  abortClickWait,
  registerClickWaitAbort,
} = require("../src/click-scheduler");

test("rapid opens invalidate all but latest click generation", () => {
  const generations = [];
  for (let i = 0; i < 50; i += 1) {
    nextClickGeneration();
    generations.push(currentClickGeneration());
  }
  const latest = generations[generations.length - 1];
  for (let i = 0; i < generations.length - 1; i += 1) {
    assert.equal(isCurrentClickGeneration(generations[i]), false);
  }
  assert.equal(isCurrentClickGeneration(latest), true);
});

test("abort stops all registered waiters on burst open", () => {
  let aborted = 0;
  for (let i = 0; i < 20; i += 1) {
    registerClickWaitAbort(() => { aborted += 1; });
    abortClickWait();
  }
  assert.equal(aborted, 20);
});
