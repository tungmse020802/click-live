const test = require("node:test");
const assert = require("node:assert/strict");
const {
  isScheduleTooStale,
  scheduleStaleMs,
  parseAbsoluteTargetMs,
} = require("../src/junb-url");

test("isScheduleTooStale detects late job", () => {
  const now = Date.parse("2026-08-02T22:18:07.000Z");
  const end = now - 25_000;
  assert.equal(isScheduleTooStale(end, -1450, now), true);
  assert.equal(scheduleStaleMs(end, -1450, now), 25_000 + 1450);
});

test("isScheduleTooStale allows fresh job", () => {
  const now = Date.now();
  const end = now + 5000;
  assert.equal(isScheduleTooStale(end, 0, now), false);
});

test("parseAbsoluteTargetMs reads HH:MM:SS from TIME label", () => {
  const now = Date.parse("2026-08-02T22:17:00.000Z");
  const ms = parseAbsoluteTargetMs("00:57s - 22:18:07", now);
  assert.ok(ms);
});
