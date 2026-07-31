const { decodeHtmlUrl } = require("./server");

const THANHTAI_WS_HOSTS = [
  "realtime-67lx.onrender.com",
  "sever1-b5fd.onrender.com",
];

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
  const end = Number(payload.end_time);
  return Number.isFinite(end) && end > 0 ? end : null;
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

function fetchThanhtaiEndTimeMs(roomId, { timeoutMs = 8000 } = {}) {
  const timeId = String(roomId || "").trim();
  if (!timeId) return Promise.reject(new Error("missing room_id"));

  const tryHost = (host) => new Promise((resolve, reject) => {
    if (typeof WebSocket !== "function") {
      reject(new Error("WebSocket unavailable"));
      return;
    }

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

    const ws = new WebSocket(`wss://${host}/?time_id=${encodeURIComponent(timeId)}`);
    const timer = setTimeout(() => finish(reject, new Error("thanhtai ws timeout")), timeoutMs);

    ws.onmessage = (event) => {
      let pkt;
      try {
        pkt = JSON.parse(event.data);
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
        finish(resolve, pkt.end_time);
      }
    };

    ws.onerror = () => finish(reject, new Error("thanhtai ws error"));
    ws.onclose = () => {
      if (!done) finish(reject, new Error("thanhtai ws closed"));
    };
  });

  return (async () => {
    let lastErr;
    for (const host of THANHTAI_WS_HOSTS) {
      try {
        return await tryHost(host);
      } catch (err) {
        lastErr = err;
      }
    }
    throw lastErr || new Error("thanhtai end_time unavailable");
  })();
}

async function resolveCountdownEndTimeMs(url) {
  const junbEnd = parseJunbEndTimeMs(url);
  if (junbEnd) {
    return { endTimeMs: junbEnd, source: "junb_end_time" };
  }

  const roomId = extractThanhtaiRoomId(url);
  if (roomId) {
    try {
      const endTimeMs = await fetchThanhtaiEndTimeMs(roomId);
      return { endTimeMs, source: "thanhtai_end_time" };
    } catch {
      return { endTimeMs: null, source: null };
    }
  }

  return { endTimeMs: null, source: null };
}

async function computeCountdownSchedule(
  url,
  { clickAfterMs = 0, delayOffsetMs = 0, defaultWaitMs = 0, tabCloseAfterEndMs = 30_000 } = {},
) {
  const now = Date.now();
  const offset = Number(delayOffsetMs) || 0;
  const closeAfterEnd = Number(tabCloseAfterEndMs) || 30_000;
  const resolved = await resolveCountdownEndTimeMs(url);
  const endTimeMs = resolved.endTimeMs;

  if (endTimeMs) {
    const clickWaitMs = Math.max(0, Math.round(endTimeMs - now + offset));
    const closeWaitMs = Math.max(
      clickWaitMs + closeAfterEnd,
      Math.round(endTimeMs - now + closeAfterEnd),
    );
    return {
      clickWaitMs,
      closeWaitMs,
      endTimeMs,
      source: resolved.source || "countdown_end_time",
    };
  }

  const base = Number(clickAfterMs) > 0 ? Number(clickAfterMs) : Number(defaultWaitMs) || 0;
  const clickWaitMs = Math.max(0, Math.round(base + offset));
  return {
    clickWaitMs,
    closeWaitMs: clickWaitMs + closeAfterEnd,
    endTimeMs: null,
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
  isThanhtaiCountdownUrl,
  extractThanhtaiRoomId,
  fetchThanhtaiEndTimeMs,
  resolveCountdownEndTimeMs,
  computeCountdownSchedule,
  computeJunbSchedule,
};
