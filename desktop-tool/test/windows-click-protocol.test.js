const test = require("node:test");
const assert = require("node:assert/strict");
const {
  parseHelperOkLine,
  parseHelperPongLine,
  parseHelperErrLine,
} = require("../src/desktop-click");

test("parseHelperOkLine matches click id + coordinate echo", () => {
  assert.equal(parseHelperOkLine("ok:7,960,540", 7, 960, 540), true);
  assert.equal(parseHelperOkLine("ok:7,960,540\r\n", 7, 960, 540), true);
  assert.equal(parseHelperOkLine("ok:8,960,540", 7, 960, 540), false);
  assert.equal(parseHelperOkLine("ok:7,960,541", 7, 960, 540), false);
  assert.equal(parseHelperOkLine("ok:960,540", 7, 960, 540), false);
});

test("parseHelperPongLine matches ping id echo", () => {
  assert.equal(parseHelperPongLine("pong:12", 12), true);
  assert.equal(parseHelperPongLine("pong:12\r\n", 12), true);
  assert.equal(parseHelperPongLine("pong:13", 12), false);
});

test("parseHelperErrLine matches click id + detail", () => {
  assert.equal(parseHelperErrLine("err:7,cursor-at:100,200", 7), "cursor-at:100,200");
  assert.equal(parseHelperErrLine("err:7,sendinput:0,gle=5", 7), "sendinput:0,gle=5");
  assert.equal(parseHelperErrLine("err:8,cursor-at:100,200", 7), null);
});
