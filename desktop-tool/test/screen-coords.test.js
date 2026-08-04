const test = require("node:test");
const assert = require("node:assert/strict");

test("toPhysicalScreenPoint passes through on non-win32", () => {
  const original = process.platform;
  Object.defineProperty(process, "platform", { value: "darwin", configurable: true });
  try {
    const { toPhysicalScreenPoint } = require("../src/screen-coords");
    assert.deepEqual(toPhysicalScreenPoint(100, 200), { x: 100, y: 200 });
  } finally {
    Object.defineProperty(process, "platform", { value: original, configurable: true });
  }
});
