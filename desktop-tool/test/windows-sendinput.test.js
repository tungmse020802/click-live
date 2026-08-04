const test = require("node:test");
const assert = require("node:assert/strict");
const { toAbsoluteCoord } = require("../src/windows-sendinput");

test("toAbsoluteCoord maps virtual screen coords to 0..65535", () => {
  assert.equal(toAbsoluteCoord(0, 0, 1920), 0);
  assert.equal(toAbsoluteCoord(1919, 0, 1920), 65535);
  assert.ok(Math.abs(toAbsoluteCoord(960, 0, 1920) - 32768) <= 20);
});

test("toAbsoluteCoord clamps out of range", () => {
  assert.equal(toAbsoluteCoord(-10, 0, 1920), 0);
  assert.equal(toAbsoluteCoord(5000, 0, 1920), 65535);
});

test("toAbsoluteCoord handles secondary monitor origin", () => {
  // Monitor bên phải: origin x=1920, width=1920 → x=1920 → abs 0
  assert.equal(toAbsoluteCoord(1920, 1920, 1920), 0);
  assert.equal(toAbsoluteCoord(3840, 1920, 1920), 65535);
});
