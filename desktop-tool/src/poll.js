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

function startDesktopPoller({ queueUrl, pullToken, queueUsername, intervalMs, onOpen }) {
  if (!queueUrl || !pullToken || !queueUsername) {
    console.warn(
      "Desktop poller DISABLED — chọn user và đăng nhập trong app (Tài khoản queue).\n"
      + "  Cùng user/mật khẩu với web queue UI (admin1…admin10 / Admin123@)."
    );
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
      if (!data?.ok) {
        if (data?.error) {
          console.warn("Desktop poll rejected:", data.error, "— đăng nhập desktop đúng user (admin1…)");
        }
        return;
      }
      if (!Array.isArray(data.opens)) return;
      const opens = data.opens
        .map((item) => ({
          url: String(item.url || "").trim(),
          ttlMs: (Number(item.ttl_seconds) || 30) * 1000,
          jobId: item.job_id ?? null,
          clickAfterMs: Number(item.click_after_ms) || 0,
          timeLabel: String(item.time_label || "").trim(),
          queuedAtMs: Number(item.queued_at_ms) || null,
          endTimeMs: Number(item.end_time_ms) || null,
        }))
        .filter((item) => item.url);
      if (opens.length === 0) return;
      if (opens.length > 1) {
        console.log(`Desktop poll: bỏ ${opens.length - 1} link cũ, chỉ timing tab cuối`);
      }
      const item = opens[opens.length - 1];
      const who = data.queue_user ? ` user=${data.queue_user}` : "";
      console.log(`Desktop poll: 1 link${who}`);
      onOpen(item);
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
