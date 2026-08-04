const test = require("node:test");
const assert = require("node:assert/strict");
const { waitUntilDynamicTarget } = require("../src/junb-url");

function sleepMs(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test("waitUntilDynamicTarget follows offset change during wait", async () => {
  const base = Date.now() + 400;
  let offsetMs = 0;

  const done = waitUntilDynamicTarget(
    () => base + offsetMs,
    { shouldAbort: () => false },
  );

  await sleepMs(80);
  offsetMs = 300;
  await sleepMs(80);
  offsetMs = 600;

  const t0 = Date.now();
  const ok = await done;
  const elapsed = Date.now() - t0;

  assert.equal(ok, true);
  assert.ok(elapsed >= 450, `expected ~600ms extra wait, got ${elapsed}ms`);
});

test("waitUntilDynamicTarget aborts when shouldAbort flips", async () => {
  let abort = false;
  const target = Date.now() + 5000;
  const done = waitUntilDynamicTarget(
    () => target,
    { shouldAbort: () => abort },
  );
  await sleepMs(50);
  abort = true;
  const ok = await done;
  assert.equal(ok, false);
});
