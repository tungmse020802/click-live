const http = require("http");
const https = require("https");
const { URL } = require("url");

function httpRequestJson(urlStr, { method = "GET", body = null, timeoutMs = 12000 } = {}) {
  return new Promise((resolve, reject) => {
    let url;
    try {
      url = new URL(urlStr);
    } catch (err) {
      reject(err);
      return;
    }
    const lib = url.protocol === "https:" ? https : http;
    const payload = body != null ? JSON.stringify(body) : null;
    const req = lib.request(
      urlStr,
      {
        method,
        headers: payload
          ? {
              "Content-Type": "application/json; charset=utf-8",
              "Content-Length": Buffer.byteLength(payload),
            }
          : {},
      },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () => {
          let data;
          try {
            data = JSON.parse(Buffer.concat(chunks).toString("utf-8"));
          } catch (err) {
            reject(err);
            return;
          }
          if (res.statusCode >= 400) {
            reject(new Error(data?.error || `HTTP ${res.statusCode}`));
            return;
          }
          resolve(data);
        });
      }
    );
    req.on("error", reject);
    req.setTimeout(timeoutMs, () => {
      req.destroy(new Error("timeout"));
    });
    if (payload) req.write(payload);
    req.end();
  });
}

async function fetchQueueUsers(queueUrl) {
  const base = String(queueUrl || "").replace(/\/$/, "");
  if (!base) throw new Error("Chưa cấu hình URL queue server");
  const data = await httpRequestJson(`${base}/api/desktop/auth/users`);
  if (!data?.ok || !Array.isArray(data.users)) {
    throw new Error(data?.error || "Không tải được danh sách user");
  }
  return data.users.map((name) => String(name || "").trim()).filter(Boolean);
}

async function desktopLogin(queueUrl, username, password) {
  const base = String(queueUrl || "").replace(/\/$/, "");
  const name = String(username || "").trim();
  const pass = String(password || "");
  if (!base) throw new Error("Chưa cấu hình URL queue server");
  if (!name || !pass) throw new Error("Nhập tên đăng nhập và mật khẩu");

  const data = await httpRequestJson(`${base}/api/desktop/auth/login`, {
    method: "POST",
    body: { username: name, password: pass },
  });
  if (!data?.ok || !data.pull_token) {
    throw new Error(data?.error || "Đăng nhập thất bại");
  }
  return data;
}

module.exports = {
  httpRequestJson,
  fetchQueueUsers,
  desktopLogin,
};
