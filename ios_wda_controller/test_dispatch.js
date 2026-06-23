"use strict";

// Simulates exactly what runQueueItemWorker in fleet-agent.js does.
// Run: node test_dispatch.js
// Uses config.env from ios_wda_controller, fetches a real job from queue server,
// spawns worker.js with MANUAL_QUEUE_JOB_JSON just like wda_control_panel does.

const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const { spawn } = require("node:child_process");

const controllerDir = __dirname;
const workerPath = path.join(controllerDir, "worker.js");

// Read config.env (same logic as AutomationWorker.readEnvFile)
function readEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return {};
  const result = {};
  for (const rawLine of fs.readFileSync(filePath, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator <= 0) continue;
    const key = line.slice(0, separator).trim();
    let value = line.slice(separator + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    result[key] = value;
  }
  return result;
}

function resolveDeeplinkOpenMode(configuredMode) {
  const mode = String(configuredMode || "").trim();
  if (process.platform === "win32") {
    return mode && mode !== "safari" ? mode : "mobile_deeplink";
  }
  return mode || "mobile_deeplink";
}

function extractTimeMeta(item) {
  const payload = item?.payload || {};
  const text = String(item?.message?.text || "");
  const candidates = [payload.TIME, payload.time, payload.Time, payload.click_time, payload.open_time, text];
  for (const value of candidates) {
    const raw = String(value || "");
    const match = raw.match(/TIME\s*[:：]\s*([^\n\r]+)/i)
      || raw.match(/(\d{1,2}:\d{2}\s*s?\s*-\s*\d{1,2}:\d{2}:\d{2})/i)
      || raw.match(/(\d{1,2}:\d{2}\s*s?)/i);
    if (match) {
      let label = match[1].trim().split(/\s+(?:https?|tiktok):\/\//i)[0].trim();
      const tsEnd = label.match(/^(\d{1,2}:\d{2}\s*s?\s*-\s*\d{1,2}:\d{2}:\d{2})/i)
        || label.match(/^(\d{1,2}:\d{2}:\d{2})/i);
      if (tsEnd) label = tsEnd[1].trim();
      const delayMatch = label.match(/(\d{1,2}):(\d{2})\s*s?/i);
      const click_after_ms = delayMatch ? (Number(delayMatch[1]) * 60 + Number(delayMatch[2])) * 1000 : 0;
      return { label, click_after_ms };
    }
  }
  return { label: "", click_after_ms: Number(payload.click_after_ms || item?.click_after_ms || 0) };
}

function extractQueueUrl(item) {
  const payload = item?.payload || {};
  const message = item?.message || {};
  const candidates = [payload.url, payload.link, payload.deeplink, payload.deep_link, payload.live_url, payload.room_url, message.text];
  for (const value of candidates) {
    const match = String(value || "").match(/(?:https?:\/\/|tiktok:\/\/)[^\s<>'"]+/i);
    if (match) return match[0];
  }
  return "";
}

async function fetchQueueItem() {
  return new Promise((resolve, reject) => {
    const url = "http://103.38.237.7:8787/api/queue?limit=1&statuses=pending";
    http.get(url, (res) => {
      let body = "";
      res.on("data", (d) => (body += d));
      res.on("end", () => {
        try {
          const resp = JSON.parse(body);
          const items = resp.items || [];
          if (!items.length) { reject(new Error("no pending items in /api/queue: " + body.slice(0, 200))); return; }
          resolve(items[0]);
        } catch (e) { reject(new Error("JSON parse: " + body.slice(0, 200))); }
      });
    }).on("error", reject);
  });
}

async function main() {
  const controllerEnv = readEnvFile(path.join(controllerDir, "config.env"));
  const wdaUrl = "http://127.0.0.1:4723";

  console.log("[dispatch] fetching job from /api/queue ...");
  const item = await fetchQueueItem();
  if (!item?.id) { console.error("[dispatch] no item:", JSON.stringify(item).slice(0, 300)); process.exit(1); }

  const url = extractQueueUrl(item);
  const timeMeta = extractTimeMeta(item);
  const text = String(item?.message?.text || item?.message || "");
  const payload = item?.payload || {};

  const job = {
    id: Number(item.id),
    url,
    time: timeMeta.label,
    message: text,
    click_after_ms: timeMeta.click_after_ms,
    payload,
    received_at_ms: Date.now(),
    server_generated_at: new Date().toISOString(),
  };

  console.log("[dispatch] job built:");
  console.log("  id:", job.id);
  console.log("  url:", job.url);
  console.log("  time:", job.time);
  console.log("  click_after_ms:", job.click_after_ms);
  console.log("  message:", job.message.slice(0, 100));

  const device = {
    udid: controllerEnv.DEVICE_UDID || "00008030-000805902E3B802E",
    deviceId: controllerEnv.DEVICE_ID || "iphone-01",
    name: controllerEnv.DEVICE_NAME || "Tung",
    version: controllerEnv.PLATFORM_VERSION || "18.6.2",
  };

  const env = {
    ...process.env,
    ...controllerEnv,
    WDA_URL: wdaUrl,
    APPIUM_URL: wdaUrl,
    QUEUE_SERVER_URL: controllerEnv.QUEUE_SERVER_URL || "http://103.38.237.7:8787",
    DEVICE_UDID: device.udid,
    DEVICE_NAME: device.name,
    DEVICE_ID: device.deviceId,
    PLATFORM_VERSION: device.version,
    TIKTOK_BUNDLE_ID: controllerEnv.TIKTOK_BUNDLE_ID || "com.ss.iphone.ugc.Ame",
    WDA_SESSION_BUNDLE_ID: controllerEnv.WDA_SESSION_BUNDLE_ID || "com.apple.mobilesafari",
    DEEPLINK_OPEN_MODE: resolveDeeplinkOpenMode(controllerEnv.DEEPLINK_OPEN_MODE),
    DEEPLINK_FALLBACK_TO_URL: controllerEnv.DEEPLINK_FALLBACK_TO_URL || "false",
    DEEPLINK_REQUIRE_TIKTOK_FOREGROUND: controllerEnv.DEEPLINK_REQUIRE_TIKTOK_FOREGROUND || "true",
    LIVE_TIME_MIN_SECONDS: controllerEnv.LIVE_TIME_MIN_SECONDS || "20",
    LIVE_TIME_MAX_SECONDS: controllerEnv.LIVE_TIME_MAX_SECONDS || "30",
    FILTER_MAX_VIEWS: controllerEnv.FILTER_MAX_VIEWS || "0",
    FILTER_MIN_BOX1: controllerEnv.FILTER_MIN_BOX1 || "0",
    FILTER_MIN_BOX2: controllerEnv.FILTER_MIN_BOX2 || "0",
    FILTER_MIN_RATE: controllerEnv.FILTER_MIN_RATE || "0",
    OPEN_TAP_REQUEST_LEAD_MS: controllerEnv.OPEN_TAP_REQUEST_LEAD_MS || "2500",
    OPEN_TAP_TRANSPORT_COMPENSATION_MS: controllerEnv.OPEN_TAP_TRANSPORT_COMPENSATION_MS || "200",
    OPEN_MAX_LATENESS_MS: controllerEnv.OPEN_MAX_LATENESS_MS || "1500",
    RUN_ONCE: "true",
    MANUAL_QUEUE_JOB_JSON: JSON.stringify(job),
    PYTHON_PATH: controllerEnv.PYTHON_PATH || "python3",
    ELECTRON_RUN_AS_NODE: "1",
  };

  console.log("\n[dispatch] spawning worker.js with RUN_ONCE=true MANUAL_QUEUE_JOB_JSON=<job>");
  console.log("[dispatch] DEEPLINK_OPEN_MODE:", env.DEEPLINK_OPEN_MODE);
  console.log("[dispatch] TIKTOK_BUNDLE_ID:", env.TIKTOK_BUNDLE_ID);
  console.log("[dispatch] TREASURE_INITIAL_SETTLE_MS:", env.TREASURE_INITIAL_SETTLE_MS);
  console.log("[dispatch] TREASURE_OVERLAY_WAIT_MS:", env.TREASURE_OVERLAY_WAIT_MS);
  console.log("[dispatch] TREASURE_DEBUG_MODE:", env.TREASURE_DEBUG_MODE);
  console.log("");

  const child = spawn(process.execPath, [workerPath], {
    cwd: controllerDir,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  const handleOutput = (chunk) => {
    process.stdout.write(chunk);
  };
  child.stdout.on("data", handleOutput);
  child.stderr.on("data", handleOutput);
  child.on("error", (e) => console.error("[dispatch] spawn error:", e.message));
  child.on("close", (code, signal) => {
    console.log(`\n[dispatch] worker exited code=${code} signal=${signal || ""}`);
  });
}

main().catch((e) => { console.error(e); process.exit(1); });
