const http = require("http");
const { URL } = require("url");

const DEFAULT_PORT = 8795;
const DEFAULT_TTL_MS = 30_000;

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      if (!chunks.length) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf-8")));
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Private-Network": "true",
  });
  res.end(body);
}

function decodeHtmlUrl(url) {
  return String(url || '')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .trim();
}

function normalizeOpenUrl(url) {
  const text = decodeHtmlUrl(url);
  if (!text) return "";
  try {
    const parsed = new URL(text);
    if (parsed.searchParams.has("r")) {
      return `${parsed.origin}${parsed.pathname}?r=${parsed.searchParams.get("r")}`;
    }
    if (parsed.searchParams.has("data")) {
      return `${parsed.origin}${parsed.pathname}?data=${parsed.searchParams.get("data")}`;
    }
    if (parsed.searchParams.has("room_id")) {
      return `${parsed.origin}${parsed.pathname}?room_id=${parsed.searchParams.get("room_id")}`;
    }
  } catch {
    /* keep raw */
  }
  return text;
}

function createDesktopToolServer({ port = DEFAULT_PORT, onOpen, getSettings } = {}) {
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url || "/", `http://127.0.0.1:${port}`);

    if (req.method === "OPTIONS") {
      res.writeHead(204, {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Private-Network": "true",
      });
      res.end();
      return;
    }

    if (req.method === "GET" && url.pathname === "/health") {
      sendJson(res, 200, {
        ok: true,
        service: "click-live-desktop-tool",
        port,
        default_ttl_seconds: DEFAULT_TTL_MS / 1000,
        settings: typeof getSettings === "function" ? getSettings() : undefined,
      });
      return;
    }

    if (req.method === "GET" && url.pathname === "/settings") {
      sendJson(res, 200, {
        ok: true,
        settings: typeof getSettings === "function" ? getSettings() : {},
      });
      return;
    }

    if (req.method === "POST" && url.pathname === "/open") {
      try {
        const payload = await readJsonBody(req);
        const target = decodeHtmlUrl(String(payload.url || "").trim());
        if (!target.startsWith("http://") && !target.startsWith("https://")) {
          sendJson(res, 400, { ok: false, error: "Invalid url" });
          return;
        }
        const ttlSeconds = Number(payload.ttl_seconds);
        const ttlMs = Number.isFinite(ttlSeconds) && ttlSeconds > 0
          ? ttlSeconds * 1000
          : DEFAULT_TTL_MS;
        const jobId = payload.job_id ?? null;
        const clickAfterMs = Number(payload.click_after_ms);
        const timeLabel = String(payload.time_label || "").trim();
        const result = await Promise.resolve(onOpen({
          url: target,
          ttlMs,
          jobId,
          clickAfterMs: Number.isFinite(clickAfterMs) ? clickAfterMs : 0,
          timeLabel,
        }));
        const tabId = typeof result === "object" ? result.tabId : result;
        const deduplicated = Boolean(typeof result === "object" && result.deduplicated);
        sendJson(res, 200, {
          ok: true,
          tab_id: tabId,
          url: target,
          ttl_seconds: ttlMs / 1000,
          click_after_ms: Number.isFinite(clickAfterMs) ? clickAfterMs : 0,
          time_label: timeLabel,
          deduplicated,
        });
      } catch (err) {
        sendJson(res, 400, { ok: false, error: String(err.message || err) });
      }
      return;
    }

    sendJson(res, 404, { ok: false, error: "Not found" });
  });

  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => {
      resolve({ server, port });
    });
  });
}

module.exports = {
  createDesktopToolServer,
  normalizeOpenUrl,
  decodeHtmlUrl,
  DEFAULT_PORT,
  DEFAULT_TTL_MS,
};
