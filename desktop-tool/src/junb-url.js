const { decodeHtmlUrl } = require("./server");
const { resolveClickExecutionLeadMs } = require("./click-lead");

const THANHTAI_WS_HOSTS = [
  "realtime-67lx.onrender.com",
  "sever1-b5fd.onrender.com",
];

const THANHTAI_WS_TIMEOUT_MS = 5000;
const END_TIME_CACHE_TTL_MS = 5_000;

/** Mốc hiển thị 0.0s trên overlay (= lúc user muốn click). */
function clickDisplayTargetMs(endTimeMs, delayOffsetMs = 0) {
  if (!endTimeMs) return null;
  return Math.round(endTimeMs + (Number(delayOffsetMs) || 0));
}

/** Mốc bắt đầu gọi click (sớm hơn display target một chút để bù độ trễ OS). */
function clickExecuteAtMs(endTimeMs, delayOffsetMs = 0) {
  const target = clickDisplayTargetMs(endTimeMs, delayOffsetMs);
  if (!target) return null;
  return target - resolveClickExecutionLeadMs();
}

/** ms còn lại trên đồng hồ countdown (0.0s = hết giờ) trước offset user. */
function displayRemainingMs(endTimeMs, delayOffsetMs = 0, nowMs = Date.now()) {
  if (!endTimeMs) return null;
  return Math.round(endTimeMs - nowMs + (Number(delayOffsetMs) || 0));
}

/** Hẹn timer sớm hơn để bù độ trễ PowerShell / cliclick — click chạm đúng lúc offset. */
function computeClickFireDelayMs(schedule, delayOffsetMs = 0, nowMs = Date.now()) {
  const offset = Number(delayOffsetMs) || 0;
  const lead = resolveClickExecutionLeadMs();
  if (schedule?.endTimeMs) {
    return Math.max(0, Math.round(schedule.endTimeMs - nowMs + offset - lead));
  }
  return Math.max(0, Math.round((Number(schedule?.clickWaitMs) || 0) - lead));
}

function sleepMs(ms) {
  const wait = Math.max(0, Math.round(ms));
  if (wait <= 0) return Promise.resolve();
  return new Promise((resolve) => setTimeout(resolve, wait));
}

/** Chờ tới timestamp tuyệt đối — một vòng chờ duy nhất, ổn định hơn setTimeout. */
async function waitUntilTimestamp(targetMs, { shouldAbort } = {}) {
  if (!Number.isFinite(targetMs)) return false;
  while (Date.now() < targetMs) {
    if (typeof shouldAbort === "function" && shouldAbort()) return false;
    const remaining = targetMs - Date.now();
    if (remaining > 80) await sleepMs(remaining - 40);
    else if (remaining > 20) await sleepMs(Math.max(1, remaining - 8));
    else if (remaining > 2) await sleepMs(1);
    /* else: busy-wait vài ms cuối cho chính xác */
  }
  return !(typeof shouldAbort === "function" && shouldAbort());
}

/** @deprecated use waitUntilTimestamp(clickExecuteAtMs(...)) */
async function waitUntilClickTarget(endTimeMs, delayOffsetMs = 0, { shouldAbort } = {}) {
  const targetAt = clickExecuteAtMs(endTimeMs, delayOffsetMs);
  if (!targetAt) return;
  await waitUntilTimestamp(targetAt, { shouldAbort });
}

/** @type {Map<string, { endTimeMs: number, source: string, expiresAt: number }>} */
const endTimeCache = new Map();

let wsModule = null;
function resolveWebSocketCtor() {
  if (typeof WebSocket === "function") return WebSocket;
  if (wsModule !== false) {
    try {
      wsModule = require("ws");
      return wsModule;
    } catch {
      wsModule = false;
    }
  }
  return null;
}

function normalizeEndTimeMs(raw) {
  const end = Number(raw);
  if (!Number.isFinite(end) || end <= 0) return null;
  // Unix giây (10 chữ số) → ms
  if (end < 1e12) return Math.round(end * 1000);
  return Math.round(end);
}

function cacheKeyForUrl(url) {
  return String(url || "").trim().split("#")[0];
}

function decodeJunbPayload(url) {
  try {
    const parsed = new URL(decodeHtmlUrl(url));
    const raw = parsed.searchParams.get("r");
    if (!raw) return null;
    const padded = raw + "=".repeat((4 - (raw.length % 4)) % 4);
    const json = JSON.parse(Buffer.from(padded, "base64").toString("utf-8"));
    return json && typeof json === "object" ? json : null;
  } catch {
    return null;
  }
}

function parseJunbEndTimeMs(url) {
  const payload = decodeJunbPayload(url);
  if (!payload) return null;
  return normalizeEndTimeMs(payload.end_time);
}

function isThanhtaiCountdownUrl(url) {
  try {
    const parsed = new URL(decodeHtmlUrl(url));
    return /thanhtai\.io$/i.test(parsed.hostname.replace(/^www\./, ""))
      && /countdow/i.test(parsed.pathname || "");
  } catch {
    return false;
  }
}

function extractThanhtaiRoomId(url) {
  if (!isThanhtaiCountdownUrl(url)) return null;
  try {
    const parsed = new URL(decodeHtmlUrl(url));
    const data = parsed.searchParams.get("data");
    if (!data) return null;
    const padded = data + "=".repeat((4 - (data.length % 4)) % 4);
    const decoded = Buffer.from(padded, "base64").toString("ascii").trim();
    return /^\d{10,}$/.test(decoded) ? decoded : null;
  } catch {
    return null;
  }
}

/** Giống ios_wda_controller/lib/timing.js — mốc HH:MM:SS trong TIME tin nhắn. */
function parseAbsoluteTargetMs(timeLabel, nowMs = Date.now()) {
  const timeText = String(timeLabel || "");
  const absolute = timeText.match(/(?:-\s*|TIME\s*[:：]\s*)(\d{1,2}):(\d{2}):(\d{2})\b/i)
    || timeText.match(/\b(\d{1,2}):(\d{2}):(\d{2})\s*$/);
  if (!absolute) return null;

  const rawH = Number(absolute[1]);
  const mm = Number(absolute[2]);
  const ss = Number(absolute[3]);
  if (![rawH, mm, ss].every(Number.isFinite)) return null;

  const hh = rawH % 24;
  const target = new Date(nowMs);
  target.setHours(hh, mm, ss, 0);
  if (target.getTime() < nowMs - 12 * 60 * 60 * 1000) {
    target.setDate(target.getDate() + 1);
  }
  return target.getTime();
}

function attachWsHandlers(ws, { onMessage, onFail }) {
  if (typeof ws.on === "function") {
    ws.on("message", (data) => {
      const text = Buffer.isBuffer(data) ? data.toString("utf-8") : String(data);
      onMessage(text);
    });
    ws.on("error", onFail);
    ws.on("close", () => onFail(new Error("thanhtai ws closed")));
    return;
  }

  ws.onmessage = (event) => onMessage(String(event.data || ""));
  ws.onerror = () => onFail(new Error("thanhtai ws error"));
  ws.onclose = () => onFail(new Error("thanhtai ws closed"));
}

function fetchThanhtaiEndTimeMs(roomId, { timeoutMs = THANHTAI_WS_TIMEOUT_MS } = {}) {
  const timeId = String(roomId || "").trim();
  if (!timeId) return Promise.reject(new Error("missing room_id"));

  const WebSocketCtor = resolveWebSocketCtor();
  if (!WebSocketCtor) {
    return Promise.reject(new Error("WebSocket unavailable"));
  }

  const tryHost = (host) => new Promise((resolve, reject) => {
    let done = false;
    const finish = (fn, value) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      try {
        ws.close();
      } catch {
        /* ignore */
      }
      fn(value);
    };

    const ws = new WebSocketCtor(`wss://${host}/?time_id=${encodeURIComponent(timeId)}`);
    const timer = setTimeout(() => finish(reject, new Error("thanhtai ws timeout")), timeoutMs);

    attachWsHandlers(ws, {
      onFail: (err) => finish(reject, err instanceof Error ? err : new Error("thanhtai ws error")),
      onMessage: (raw) => {
        let pkt;
        try {
          pkt = JSON.parse(raw);
        } catch {
          return;
        }
        if (!pkt || typeof pkt !== "object") return;

        if (pkt.type === "error") {
          finish(reject, new Error(pkt.error || "thanhtai ws error"));
          return;
        }

        if (
          (pkt.type === "hello" || pkt.type === "resync")
          && typeof pkt.end_time === "number"
          && pkt.end_time > 0
        ) {
          finish(resolve, normalizeEndTimeMs(pkt.end_time));
        }
      },
    });
  });

  return Promise.any(THANHTAI_WS_HOSTS.map((host) => tryHost(host))).catch((aggregateErr) => {
    const errs = aggregateErr?.errors || [];
    throw errs[errs.length - 1] || aggregateErr || new Error("thanhtai end_time unavailable");
  });
}

async function resolveCountdownEndTimeMs(url, presetEndTimeMs = null, { useCache = true } = {}) {
  const preset = normalizeEndTimeMs(presetEndTimeMs);
  if (preset) {
    return { endTimeMs: preset, source: "server_end_time" };
  }

  const cacheKey = cacheKeyForUrl(url);
  if (useCache) {
    const cached = endTimeCache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) {
      return { endTimeMs: cached.endTimeMs, source: cached.source };
    }
  }

  const junbEnd = parseJunbEndTimeMs(url);
  if (junbEnd) {
    const entry = {
      endTimeMs: junbEnd,
      source: "junb_end_time",
      expiresAt: Date.now() + END_TIME_CACHE_TTL_MS,
    };
    endTimeCache.set(cacheKey, entry);
    return { endTimeMs: entry.endTimeMs, source: entry.source };
  }

  const roomId = extractThanhtaiRoomId(url);
  if (roomId) {
    try {
      const endTimeMs = await fetchThanhtaiEndTimeMs(roomId);
      const entry = {
        endTimeMs,
        source: "thanhtai_end_time",
        expiresAt: Date.now() + END_TIME_CACHE_TTL_MS,
      };
      endTimeCache.set(cacheKey, entry);
      return { endTimeMs: entry.endTimeMs, source: entry.source };
    } catch {
      return { endTimeMs: null, source: null };
    }
  }

  return { endTimeMs: null, source: null };
}

function buildEndTimeSchedule(endTimeMs, {
  now,
  offset,
  closeAfterEnd,
  source,
}) {
  const clickWaitMs = computeClickFireDelayMs({ endTimeMs, clickWaitMs: 0 }, offset, now);
  const closeWaitMs = Math.max(
    clickWaitMs + closeAfterEnd,
    Math.round(endTimeMs - now + closeAfterEnd),
  );
  return {
    clickWaitMs,
    closeWaitMs,
    endTimeMs,
    displayRemainingMs: displayRemainingMs(endTimeMs, offset, now),
    executionLeadMs: resolveClickExecutionLeadMs(),
    source,
  };
}

async function computeCountdownSchedule(
  url,
  {
    clickAfterMs = 0,
    delayOffsetMs = 0,
    defaultWaitMs = 0,
    tabCloseAfterEndMs = 30_000,
    timeLabel = "",
    queuedAtMs = null,
    endTimeMs: presetEndTimeMs = null,
  } = {},
) {
  const offset = Number(delayOffsetMs) || 0;
  const closeAfterEnd = Number(tabCloseAfterEndMs) || 30_000;
  const queuedAt = Number(queuedAtMs) > 0 ? Math.round(Number(queuedAtMs)) : null;

  // Giống iOS: TIME tuyệt đối HH:MM:SS trong tin (vd. 00:57s - 12:34:56) ưu tiên nhất.
  const absoluteTargetMs = parseAbsoluteTargetMs(timeLabel, Date.now());
  if (absoluteTargetMs) {
    return buildEndTimeSchedule(absoluteTargetMs, {
      now: Date.now(),
      offset,
      closeAfterEnd,
      source: "message_clock",
    });
  }

  const resolved = await resolveCountdownEndTimeMs(url, presetEndTimeMs, { useCache: false });
  const now = Date.now();
  let endTimeMs = resolved.endTimeMs;
  let source = resolved.source;

  if (!endTimeMs && queuedAt && Number(clickAfterMs) > 0) {
    endTimeMs = queuedAt + Math.round(Number(clickAfterMs));
    source = "queued_click_after";
  }

  if (endTimeMs) {
    return buildEndTimeSchedule(endTimeMs, { now, offset, closeAfterEnd, source: source || "countdown_end_time" });
  }

  const base = Number(clickAfterMs) > 0 ? Number(clickAfterMs) : Number(defaultWaitMs) || 0;
  const clickWaitMs = computeClickFireDelayMs({ clickWaitMs: Math.max(0, Math.round(base + offset)) }, 0, now);
  return {
    clickWaitMs,
    closeWaitMs: clickWaitMs + closeAfterEnd,
    endTimeMs: null,
    displayRemainingMs: null,
    executionLeadMs: resolveClickExecutionLeadMs(),
    source: "time_meta",
  };
}

/** @deprecated use computeCountdownSchedule */
async function computeJunbSchedule(url, opts) {
  return computeCountdownSchedule(url, opts);
}

module.exports = {
  decodeJunbPayload,
  parseJunbEndTimeMs,
  parseAbsoluteTargetMs,
  normalizeEndTimeMs,
  isThanhtaiCountdownUrl,
  extractThanhtaiRoomId,
  fetchThanhtaiEndTimeMs,
  resolveCountdownEndTimeMs,
  computeCountdownSchedule,
  computeJunbSchedule,
  resolveClickExecutionLeadMs,
  computeClickFireDelayMs,
  displayRemainingMs,
  clickDisplayTargetMs,
  clickExecuteAtMs,
  waitUntilTimestamp,
  waitUntilClickTarget,
};
