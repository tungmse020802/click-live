const test = require("node:test");
const assert = require("node:assert/strict");
const { parseHelperOkLine } = require("../src/desktop-click");

test("parseHelperOkLine matches click id + coordinate echo", () => {
  assert.equal(parseHelperOkLine("ok:7,960,540", 7, 960, 540), true);
  assert.equal(parseHelperOkLine("ok:7,960,540\r\n", 7, 960, 540), true);
  assert.equal(parseHelperOkLine("ok:8,960,540", 7, 960, 540), false);
  assert.equal(parseHelperOkLine("ok:7,960,541", 7, 960, 540), false);
  assert.equal(parseHelperOkLine("ok:960,540", 7, 960, 540), false);
});
