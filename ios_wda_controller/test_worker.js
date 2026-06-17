"use strict";

const assert = require("node:assert/strict");
const {
  jobTimeWindow,
  localTimeLabel,
  openTapRequestTime,
  openTargetTime,
} = require("./lib/timing");

const now = new Date(2026, 5, 14, 1, 39, 10, 250).getTime();

// absolute time parsed directly from message — no clock offset
const absolute = openTargetTime({
  time: "01:05s - 01:40:04 BOX : 100/25",
  click_after_ms: 65000,
  received_at_ms: now,
}, now);
assert.equal(absolute.source, "message_clock_mac_local");
assert.equal(absolute.clock_source, "mac_local");
assert.equal(absolute.targetAtMs, new Date(2026, 5, 14, 1, 40, 4, 0).getTime(),
  "target should equal message TIME with no offset");

// hours >= 24 are wrapped clock labels after midnight: 24:34:29 → today 00:34:29
const wrappedToday = openTargetTime({
  time: "01:05s - 24:34:29",
  received_at_ms: now,
}, now);
assert.equal(wrappedToday.source, "message_clock_mac_local");
assert.equal(wrappedToday.targetAtMs, new Date(2026, 5, 14, 0, 34, 29, 0).getTime(),
  "24:xx:xx should resolve to today's wrapped 00:xx:xx");

const nearMidnight = new Date(2026, 5, 17, 0, 17, 17, 0).getTime();
const wrappedFuture = openTargetTime({
  time: "01:05s - 24:18:18",
  received_at_ms: nearMidnight,
}, nearMidnight);
assert.equal(wrappedFuture.targetAtMs, new Date(2026, 5, 17, 0, 18, 18, 0).getTime(),
  "24:xx:xx near midnight should stay today, not sleep until tomorrow");

// fallback to click_after_ms when no absolute time
const fallback = openTargetTime({
  click_after_ms: 65000,
  received_at_ms: now,
}, now);
assert.equal(fallback.source, "click_after_ms");
assert.equal(fallback.targetAtMs, now + 65000);

assert.equal(openTargetTime({}, now), null);

assert.equal(openTapRequestTime(10000, 900), 9100);
assert.equal(openTapRequestTime(10000, -100), 10000);

// jobTimeWindow: target = message TIME, no offset
// now=01:39:10, message TIME=01:39:30 → +20s → ready (15-20s window)
assert.equal(jobTimeWindow({ time: "01:05s - 01:39:30" }, now, 15000, 20000).state, "ready",
  "20s away → ready");
// message TIME=01:39:20 → +10s → late (< 15s min)
assert.equal(jobTimeWindow({ time: "01:05s - 01:39:20" }, now, 15000, 20000).state, "late",
  "10s away → late");
// message TIME=01:39:35 → +25s → early (> 20s max)
assert.equal(jobTimeWindow({ time: "01:05s - 01:39:35" }, now, 15000, 20000).state, "early",
  "25s away → early");
// message TIME=01:38:00 → -70s → late
assert.equal(jobTimeWindow({ time: "01:05s - 01:38:00" }, now, 15000, 20000).state, "late",
  "past time → late");
assert.equal(jobTimeWindow({}, now, 15000, 20000).state, "missing");

assert.match(localTimeLabel(now), /2026-06-14 01:39:10/);
console.log("worker schedule tests passed.");
