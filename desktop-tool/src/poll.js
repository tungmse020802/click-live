const http = require("http");
const https = require("https");
const { URL } = require("url");

function httpGetJson(urlStr, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    let url;
    try {
      url = new URL(urlStr);
    } catch (err) {
      reject(err);
      return;
    }
    const lib = url.protocol === "https:" ? https : http;
    const req = lib.get(urlStr, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        try {
          resolve(JSON.parse(Buffer.concat(chunks).toString("utf-8")));
        } catch (err) {
          reject(err);
        }
      });
    });
    req.on("error", reject);
    req.setTimeout(timeoutMs, () => {
      req.destroy(new Error("timeout"));
    });
  });
}

function startDesktopPoller({ queueUrl, pullToken, intervalMs, onOpen }) {
  if (!queueUrl || !pullToken) {
    console.warn("Desktop poller disabled — set DESKTOP_TOOL_QUEUE_URL + DESKTOP_TOOL_PULL_TOKEN");
    return () => {};
  }

  const base = queueUrl.replace(/\/$/, "");
  let inFlight = false;

  const tick = async () => {
    if (inFlight) return;
    inFlight = true;
    try {
      const data = await httpGetJson(
        `${base}/api/desktop/pull?token=${encodeURIComponent(pullToken)}`
      );
      if (!data?.ok || !Array.isArray(data.opens)) return;
      for (const item of data.opens) {
        const target = String(item.url || "").trim();
        if (!target) continue;
        onOpen({
          url: target,
          ttlMs: (Number(item.ttl_seconds) || 30) * 1000,
          jobId: item.job_id ?? null,
          clickAfterMs: Number(item.click_after_ms) || 0,
          timeLabel: String(item.time_label || "").trim(),
        });
      }
    } catch (err) {
      console.warn("Desktop poll failed:", err.message || err);
    } finally {
      inFlight = false;
    }
  };

  tick();
  const timer = setInterval(tick, intervalMs);
  return () => clearInterval(timer);
}

module.exports = {
  httpGetJson,
  startDesktopPoller,
};
