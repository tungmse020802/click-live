"use strict";

function localTimezoneLabel() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "local";
}

function localTimeLabel(timestampMs) {
  return new Date(timestampMs).toLocaleString("sv-SE", {
    hour12: false,
    timeZoneName: "shortOffset",
  });
}

function openTargetTime(job, nowMs = Date.now(), options = {}) {
  const clockSource = options.clockSource || "mac_local";
  const allowClickAfterFallback = options.allowClickAfterFallback !== false;
  const log = options.log || (() => {});
  const timezone = options.timezone || localTimezoneLabel();
  const timeText = [job?.time, job?.message].filter(Boolean).join(" ");
  const absolute = timeText.match(/-\s*(\d{1,2}):(\d{2}):(\d{2})(?:\s|$)/);
  if (absolute) {
    const rawH = Number(absolute[1]);
    const mm = Number(absolute[2]);
    const ss = Number(absolute[3]);
    const hh = rawH % 24;
    const target = new Date(nowMs);
    target.setHours(hh, mm, ss, 0);
    const wrappedHour = rawH >= 24;
    if (target.getTime() < nowMs - 12 * 60 * 60 * 1000) {
      target.setDate(target.getDate() + 1);
    }
    const targetMs = target.getTime();
    log(
      `[TIMING] parse TIME="${absolute[0].trim()}" rawH=${rawH} wrappedHour=${wrappedHour}`
      + ` clock=${clockSource} tz=${timezone}`
      + ` -> target ${localTimeLabel(targetMs)}`,
    );
    return {
      targetAtMs: targetMs,
      source: "message_clock_mac_local",
      label: absolute[0].replace(/^-\s*/, ""),
      clock_source: clockSource,
      timezone,
    };
  }

  const delayMs = Number(job?.click_after_ms || 0);
  if (delayMs > 0 && allowClickAfterFallback) {
    return {
      targetAtMs: Number(job?.received_at_ms || nowMs) + delayMs,
      source: "click_after_ms",
      label: `${delayMs}ms`,
      clock_source: "relative_received_at",
    };
  }
  return null;
}

function openTapRequestTime(targetAtMs, requestLeadMs) {
  return targetAtMs - Math.max(0, requestLeadMs);
}

function jobTimeWindow(job, nowMs = Date.now(), minMs = 15000, maxMs = 25000, options = {}) {
  const schedule = openTargetTime(job, nowMs, options);
  if (!schedule) return { state: "missing", remainingMs: null, schedule: null };
  const remainingMs = schedule.targetAtMs - nowMs;
  if (remainingMs > maxMs) return { state: "early", remainingMs, schedule };
  if (remainingMs < minMs) return { state: "late", remainingMs, schedule };
  return { state: "ready", remainingMs, schedule };
}

module.exports = {
  jobTimeWindow,
  localTimeLabel,
  localTimezoneLabel,
  openTapRequestTime,
  openTargetTime,
};
