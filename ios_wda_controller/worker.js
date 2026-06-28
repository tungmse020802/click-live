"use strict";

const fs = require("node:fs/promises");
const path = require("node:path");
const { spawn } = require("node:child_process");
const sharp = require("sharp");
const timing = require("./lib/timing");
const debugMode = require("./lib/debug-mode");

const config = {
  appiumUrl: trimSlash(process.env.APPIUM_URL || "http://127.0.0.1:4723"),
  wdaUrl: trimSlash(process.env.WDA_URL || ""),
  queueUrl: trimSlash(process.env.QUEUE_SERVER_URL || "http://103.38.237.7:8787"),
  udid: process.env.DEVICE_UDID || "00008030-000805902E3B802E",
  deviceName: process.env.DEVICE_NAME || "Tung",
  platformVersion: process.env.PLATFORM_VERSION || "18.6.2",
  deviceId: process.env.DEVICE_ID || "iphone-01",
  tiktokBundleId: process.env.TIKTOK_BUNDLE_ID || "",
  wdaSessionBundleId: process.env.WDA_SESSION_BUNDLE_ID || process.env.TIKTOK_BUNDLE_ID || "",
  deeplinkOpenMode: process.env.DEEPLINK_OPEN_MODE || "mobile_deeplink",
  deeplinkFallbackToUrl: boolEnv("DEEPLINK_FALLBACK_TO_URL", false),
  deeplinkOpenRetries: numberEnv("DEEPLINK_OPEN_RETRIES", 2),
  deeplinkAlertWaitMs: numberEnv("DEEPLINK_ALERT_WAIT_MS", 1800),
  deeplinkAlertSettleMs: numberEnv("DEEPLINK_ALERT_SETTLE_MS", 250),
  deeplinkOpenConfirmTaps: numberEnv("DEEPLINK_OPEN_CONFIRM_TAPS", 3),
  deeplinkSafariFallbackTaps: numberEnv("DEEPLINK_SAFARI_FALLBACK_TAPS", 2),
  deeplinkRequireTikTokForeground: boolEnv("DEEPLINK_REQUIRE_TIKTOK_FOREGROUND", true),
  deeplinkPostOpenSettleMs: numberEnv("DEEPLINK_POST_OPEN_SETTLE_MS", 700),
  deeplinkTerminateTikTokBeforeOpen: boolEnv("DEEPLINK_TERMINATE_TIKTOK_BEFORE_OPEN", true),
  deeplinkTerminateSafariBeforeOpen: boolEnv("DEEPLINK_TERMINATE_SAFARI_BEFORE_OPEN", true),
  deeplinkDismissFloatingOverlay: boolEnv("DEEPLINK_DISMISS_FLOATING_OVERLAY", true),
  deeplinkPreOpenSettleMs: numberEnv("DEEPLINK_PRE_OPEN_SETTLE_MS", 600),
  deeplinkForceActivateTikTokAfterOpen: boolEnv("DEEPLINK_FORCE_ACTIVATE_TIKTOK_AFTER_OPEN", true),
  deeplinkTerminateSafariAfterOpen: boolEnv("DEEPLINK_TERMINATE_SAFARI_AFTER_OPEN", true),
  deeplinkFullscreenSettleMs: numberEnv("DEEPLINK_FULLSCREEN_SETTLE_MS", 700),
  preferAppiumAppManagement: boolEnv("PREFER_APPIUM_APP_MANAGEMENT", true),
  pythonPath: process.env.PYTHON_PATH || "python3",
  runOnce: boolEnv("RUN_ONCE", true),
  screenshotDelayMs: numberEnv("SCREENSHOT_DELAY_SECONDS", 2) * 1000,
  pollWaitSeconds: numberEnv("POLL_WAIT_SECONDS", 25),
  liveTimeMinMs: numberEnv("LIVE_TIME_MIN_SECONDS", 20) * 1000,
  liveTimeMaxMs: numberEnv("LIVE_TIME_MAX_SECONDS", 30) * 1000,
  clockSource: process.env.CLOCK_SOURCE || "mac_local",
  allowClickAfterFallback: boolEnv("ALLOW_CLICK_AFTER_FALLBACK", true),
  filterMaxViews: numberEnv("FILTER_MAX_VIEWS", 0),    // 0 = disabled (views <= this; 0 means accept all)
  filterRewardMode: normalizeRewardMode(process.env.FILTER_REWARD_MODE || "all"),
  filterMinBox1: numberEnv("FILTER_MIN_BOX1", 0),      // box value 1 >= this
  filterMinBox2: numberEnv("FILTER_MIN_BOX2", 0),      // box value 2 >= this
  filterMinRate: numberEnv("FILTER_MIN_RATE", 0),       // rate >= this
  filterNoteContains: process.env.FILTER_NOTE_CONTAINS || "",
  treasureTapEnabled: boolEnv("TREASURE_TAP_ENABLED", true),
  treasureDetectEnabled: boolEnv("TREASURE_DETECT_ENABLED", true),
  treasureTemplatePath: process.env.TREASURE_TEMPLATE_PATH
    || path.join(__dirname, "templates", "treasure_yellow.png"),
  treasureMaskPath: process.env.TREASURE_MASK_PATH || path.join(__dirname, "templates", "treasure_box_mask.png"),
  treasureThreshold: numberEnv("TREASURE_THRESHOLD", 0.54),
  treasureMinRedRatio: numberEnv("TREASURE_MIN_RED_RATIO", 0.06),
  treasureMinWarmRatio: numberEnv("TREASURE_MIN_WARM_RATIO", 0.18),
  treasureScales: process.env.TREASURE_SCALES || "0.88,1.0,1.12",
  treasureEarlyExitScore: numberEnv("TREASURE_EARLY_EXIT_SCORE", 0.5),
  treasureTapScore: numberEnv("TREASURE_TAP_SCORE", 0.72),
  treasureConfirmFrames: numberEnv("TREASURE_CONFIRM_FRAMES", 2),
  treasureCandidateTtlMs: numberEnv("TREASURE_CANDIDATE_TTL_MS", 2200),
  treasureMaxFrameAgeMs: numberEnv("TREASURE_MAX_FRAME_AGE_MS", 700),
  treasureSameTargetDistance: numberEnv("TREASURE_SAME_TARGET_DISTANCE", 90),
  treasureRoi: process.env.TREASURE_ROI || "0,240,430,360",
  treasureStabilizeDelayMs: numberEnv("TREASURE_STABILIZE_DELAY_MS", 2000),
  treasureScanSeconds: numberEnv("TREASURE_SCAN_SECONDS", 8),
  treasureScanIntervalMs: numberEnv("TREASURE_SCAN_INTERVAL_MS", 300),
  treasureInitialSettleMs: numberEnv("TREASURE_INITIAL_SETTLE_MS", 2200),
  treasureTapX: numberEnv("TREASURE_TAP_X", 65),
  treasureTapY: numberEnv("TREASURE_TAP_Y", 170),
  treasureTapDelayMs: numberEnv("TREASURE_TAP_DELAY_SECONDS", 0) * 1000,
  treasurePreTapDelayMs: numberEnv("TREASURE_PRE_TAP_DELAY_SECONDS", 0) * 1000,
  treasureTapOffsetX: numberEnv("TREASURE_TAP_OFFSET_X", 0),
  treasureTapOffsetY: numberEnv("TREASURE_TAP_OFFSET_Y", 0),
  treasureTapSpread: numberEnv("TREASURE_TAP_SPREAD", 14),
  treasureFallbackTapOnMiss: boolEnv("TREASURE_FALLBACK_TAP_ON_MISS", false),
  treasureTapBudgetMs: numberEnv("TREASURE_TAP_BUDGET_MS", 2600),
  treasureOverlayWaitEnabled: boolEnv("TREASURE_OVERLAY_WAIT_ENABLED", true),
  treasureOverlayWaitMs: numberEnv("TREASURE_OVERLAY_WAIT_MS", 2200),
  treasureDebugMode: debugMode.normalizeDebugMode(process.env.TREASURE_DEBUG_MODE, "off"),
  openSafetyReserveMs: numberEnv("OPEN_SAFETY_RESERVE_MS", 1800),
  captureDir: resolveWorkDir(process.env.CAPTURE_DIR || "captures"),
  treasureDebugDir: resolveWorkDir(process.env.TREASURE_DEBUG_DIR || "debug_crops"),
  openButtonXRatio: numberEnv("OPEN_BUTTON_X_RATIO", 0.5),
  openButtonYRatio: numberEnv("OPEN_BUTTON_Y_RATIO", 0.93),
  openButtonDetectEnabled: boolEnv("OPEN_BUTTON_DETECT_ENABLED", true),
  openTapRequestLeadMs: numberEnv("OPEN_TAP_REQUEST_LEAD_MS", 1200),
  openTapTransportCompensationMs: numberEnv("OPEN_TAP_TRANSPORT_COMPENSATION_MS", 0),
  openDetectMinRemainingMs: numberEnv("OPEN_DETECT_MIN_REMAINING_MS", 3000),
  openResultWaitMs: numberEnv("OPEN_RESULT_WAIT_SECONDS", 0) * 1000,
  openPostTapSettleMs: numberEnv("OPEN_POST_TAP_SETTLE_MS", 200),
  openAfterTapCapture: boolEnv("OPEN_AFTER_TAP_CAPTURE", false),
  openMaxLatenessMs: numberEnv("OPEN_MAX_LATENESS_MS", 1500),
  httpTimeoutMs: numberEnv("WORKER_HTTP_TIMEOUT_MS", 35000),
};

let sessionId = "";
let stopping = false;
let cachedViewportRect = null;

function trimSlash(value) {
  return String(value).replace(/\/+$/, "");
}

function numberEnv(name, fallback) {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function boolEnv(name, fallback) {
  const value = process.env[name];
  if (value === undefined || value === "") return fallback;
  return !["0", "false", "no", "off"].includes(String(value).toLowerCase());
}

function normalizeRewardMode(value) {
  const mode = String(value || "").trim().toLowerCase();
  return ["all", "bag", "box", "both"].includes(mode) ? mode : "all";
}

function resolveWorkDir(value) {
  const raw = String(value || "").trim();
  if (!raw) return __dirname;
  return path.isAbsolute(raw) ? raw : path.resolve(__dirname, raw);
}

function localTimezoneLabel() {
  return timing.localTimezoneLabel();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    signal: options.signal || AbortSignal.timeout(config.httpTimeoutMs),
  });
  const text = await response.text();
  let body = {};
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { raw: text };
    }
  }
  if (!response.ok) {
    const message = body?.value?.message || body?.error || body?.raw || response.statusText;
    throw new Error(`${response.status} ${message}`);
  }
  return body;
}

async function wda(method, endpoint, body) {
  return requestJson(`${config.wdaUrl}${endpoint}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
}

async function appium(method, endpoint, body, options = {}) {
  return requestJson(`${config.appiumUrl}${endpoint}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal: options.timeoutMs ? AbortSignal.timeout(options.timeoutMs) : undefined,
  });
}

async function measureWdaRtt() {
  // Measure WDA RTT to log network latency (used for transport compensation tuning)
  if (config.wdaUrl) {
    try {
      const beforeMs = Date.now();
      await requestJson(`${config.wdaUrl}/status`);
      const rttMs = Date.now() - beforeMs;
      console.log(`[WDA RTT] ${rttMs}ms (set openTapRequestLeadMs > RTT for reliable tap timing)`);
    } catch (error) {
      console.warn(`[WDA RTT] ping failed: ${error.message}`);
    }
  }
}

async function waitForWdaReady(timeoutMs = 15000) {
  const deadline = Date.now() + Math.max(1000, timeoutMs);
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      await requestJson(`${config.wdaUrl}/status`);
      return true;
    } catch (error) {
      lastError = error;
      await sleep(500);
    }
  }
  throw lastError || new Error("WDA status not ready");
}

async function createSession() {
  if (!config.wdaUrl) {
    throw new Error("WDA_URL is missing");
  }
  await waitForWdaReady();
  const alwaysMatch = {
    platformName: "iOS",
    "appium:automationName": "XCUITest",
    "appium:udid": config.udid,
    "appium:deviceName": config.deviceName,
    "appium:platformVersion": config.platformVersion,
    "appium:webDriverAgentUrl": config.wdaUrl,
    "appium:newCommandTimeout": 3600,
    "appium:noReset": true,
    "appium:shouldUseSingletonTestManager": false,
    "appium:waitForIdleTimeout": 0,
  };
  if (config.wdaSessionBundleId) {
    alwaysMatch["appium:bundleId"] = config.wdaSessionBundleId;
  }
  const response = await appium("POST", "/session", {
    capabilities: {
      alwaysMatch,
    },
  });
  sessionId = response.value.sessionId;
  const caps = response.value.capabilities || {};
  const wdaDirect = caps["appium:webDriverAgentUrl"] || caps.webDriverAgentUrl || "";
  if (wdaDirect && wdaDirect !== config.wdaUrl) {
    config.wdaDirectUrl = wdaDirect.replace(/\/+$/, "");
    console.log(`[WDA] direct URL from session caps: ${config.wdaDirectUrl}`);
  }
  const rectResponse = await appium("GET", `/session/${sessionId}/window/rect`);
  cachedViewportRect = rectResponse.value || null;
  console.log(`Appium session ready: ${sessionId}`);
}

async function nextJob(afterId) {
  const url = new URL(`${config.queueUrl}/api/phone/next-job`);
  url.searchParams.set("after_id", String(afterId));
  url.searchParams.set("wait", String(config.pollWaitSeconds));
  url.searchParams.set("device_id", config.deviceId);
  const response = await requestJson(url);
  if (!response.job) return null;
  if (Number(response.job.id || 0) <= Number(afterId || 0)) {
    await sleep(1000);
    return null;
  }
  return {
    ...response.job,
    received_at_ms: Date.now(),
    server_generated_at: response.generated_at || "",
  };
}

async function report(jobId, status, error = "") {
  await requestJson(`${config.queueUrl}/api/phone/job-result`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      job_id: jobId,
      status,
      device_id: config.deviceId,
      error,
    }),
  });
}

function resolveJunbUrl(url) {
  if (!String(url || "").includes("junb.io.vn")) return url;
  try {
    const match = String(url).match(/[?&]([A-Za-z0-9_-]+)(?:$|&)/);
    if (!match) return url;
    const param = match[1];
    const chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
    const w = (param.endsWith("=") ? param.slice(0, -1) : param).split("").reverse().join("");
    let y = 0n;
    for (let z = 0; z < w.length; z++) {
      y = y * 62n + BigInt(chars.indexOf(w[z]));
    }
    y = y - 0xe6875n;
    const decoded = y.toString().slice(1).split("").reverse().join("");
    const [t, ...u] = decoded.split("");
    const room_id = u.join("").slice(0, u.length - Number(t));
    if (!room_id || !/^\d+$/.test(room_id)) return url;
    const deeplink = "snssdk1180://live?room_id=" + room_id;
    console.log(`[DEEPLINK] junb shortlink resolved: ${url} -> ${deeplink}`);
    return deeplink;
  } catch (e) {
    console.warn(`[DEEPLINK] junb resolve failed: ${e.message}`);
    return url;
  }
}

async function openDeepLink(url) {
  await prepareDeepLinkState();
  const attempts = Math.max(1, Math.round(config.deeplinkOpenRetries));
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const startedAtMs = Date.now();
    try {
      if (config.deeplinkOpenMode === "mobile_deeplink" || config.deeplinkOpenMode === "wda_open") {
        // WDA /url with bundleId opens the URL directly in TikTok without Safari.
        // Must call WDA directly (not via Appium proxy) so bundleId is forwarded.
        const wdaBase = config.wdaDirectUrl || config.wdaUrl;
        await requestJson(`${wdaBase}/session/${sessionId}/url`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url, bundleId: config.tiktokBundleId }),
        });
      } else {
        if (config.deeplinkOpenMode === "tiktok_first") {
          await activateTikTok();
        }
        await appium("POST", `/session/${sessionId}/url`, { url });
      }
      console.log(
        `[DEEPLINK] opened attempt=${attempt}/${attempts}`
        + ` mode=${config.deeplinkOpenMode} elapsed=${Date.now() - startedAtMs}ms`,
      );
      return true;
    } catch (error) {
      if (config.deeplinkOpenMode === "mobile_deeplink" || config.deeplinkOpenMode === "wda_open") {
        lastError = error;
        console.warn(`[DEEPLINK] wda open failed attempt=${attempt}/${attempts}: ${error.message}`);
        if (config.deeplinkFallbackToUrl) {
          console.warn("[DEEPLINK] fallback /url enabled; this may create Safari tabs");
          await appium("POST", `/session/${sessionId}/url`, { url });
          console.log(
            `[DEEPLINK] opened attempt=${attempt}/${attempts}`
            + ` mode=fallback_url elapsed=${Date.now() - startedAtMs}ms`,
          );
          return true;
        }
        if (isMissingSessionError(error)) throw error;
        await sleep(250);
        continue;
      }
      lastError = error;
      console.warn(`[DEEPLINK] open failed attempt=${attempt}/${attempts}: ${error.message}`);
      if (isMissingSessionError(error)) throw error;
      await sleep(250);
    }
  }
  throw lastError || new Error("open deeplink failed");
}

async function openDeepLinkViaUrlFallback(url) {
  const startedAtMs = Date.now();
  console.warn("[DEEPLINK] foreground not TikTok after mobile: deepLink; trying /url fallback");
  await appium("POST", `/session/${sessionId}/url`, { url });
  console.log(`[DEEPLINK] opened mode=fallback_url elapsed=${Date.now() - startedAtMs}ms`);
  return true;
}

async function acceptOpenInTikTokIfNeeded() {
  const deadline = Date.now() + Math.max(0, config.deeplinkAlertWaitMs);
  let tappedCount = 0;
  async function doneIfTikTokForeground() {
    if (!config.tiktokBundleId) return tappedCount > 0;
    const info = await activeAppInfo();
    return String(info.bundleId || "") === config.tiktokBundleId;
  }
  while (Date.now() < deadline) {
    const selectors = [
      { using: "-ios class chain", value: "**/XCUIElementTypeButton[`label CONTAINS[c] 'Mở trang này' OR name CONTAINS[c] 'Mở trang này' OR label CONTAINS[c] 'TikTok' OR name CONTAINS[c] 'TikTok' OR label CONTAINS[c] 'Open' OR name CONTAINS[c] 'Open' OR label CONTAINS[c] 'Mở' OR name CONTAINS[c] 'Mở'`]" },
      { using: "accessibility id", value: "Mở trang này trong TikTok" },
      { using: "accessibility id", value: "Mở trang này trong \"TikTok\"" },
      { using: "accessibility id", value: "Open" },
      { using: "accessibility id", value: "Mở" },
      { using: "accessibility id", value: "Open in TikTok" },
      { using: "accessibility id", value: "Mở trong TikTok" },
    ];

    for (const selector of selectors) {
      try {
        const elementId = await findElementId(selector);
        if (elementId) {
          await appium("POST", `/session/${sessionId}/element/${elementId}/click`);
          console.log(`Accepted iOS Open in TikTok prompt via ${selector.using}`);
          tappedCount += 1;
          await sleep(config.deeplinkAlertSettleMs);
          if (await doneIfTikTokForeground()) return true;
          if (tappedCount >= config.deeplinkOpenConfirmTaps) return true;
          break;
        }
      } catch {}
    }
    try {
      await appium("POST", `/session/${sessionId}/alert/accept`, {});
      console.log("Accepted native iOS alert fallback");
      tappedCount += 1;
      await sleep(config.deeplinkAlertSettleMs);
      if (await doneIfTikTokForeground()) return true;
      if (tappedCount >= config.deeplinkOpenConfirmTaps) return true;
      continue;
    } catch {}
    await sleep(150);
  }
  return tappedCount > 0;
}

async function findElementId(selector) {
  const found = await appium("POST", `/session/${sessionId}/element`, selector, { timeoutMs: 1500 });
  return found.value?.ELEMENT || found.value?.["element-6066-11e4-a52e-4f735466cecf"] || "";
}

async function clickFirstElement(selectors, label) {
  for (const selector of selectors) {
    try {
      const elementId = await findElementId(selector);
      if (elementId) {
        await appium("POST", `/session/${sessionId}/element/${elementId}/click`);
        console.log(`[UI] clicked ${label} via ${selector.using}`);
        return true;
      }
    } catch {}
  }
  return false;
}

async function activateTikTok() {
  if (!config.tiktokBundleId) return;
  await activateApp(config.tiktokBundleId, "TikTok");
}

async function activateApp(bundleId, label = bundleId) {
  if (!bundleId) return;
  if (!config.preferAppiumAppManagement) {
    try {
      await wda("POST", `/session/${sessionId}/wda/apps/activate`, { bundleId });
      console.log(`[DEEPLINK] activated ${label} via WDA`);
    } catch (error) {
      console.log(`activate ${label} via WDA skipped: ${error.message}`);
    }
    return;
  }
  try {
    await appium("POST", `/session/${sessionId}/execute/sync`, {
      script: "mobile: activateApp",
      args: [{ bundleId }],
    });
  } catch (error) {
    console.log(`activate ${label} skipped: ${error.message}`);
  }
}

async function terminateApp(bundleId) {
  if (!bundleId) return false;
  if (!config.preferAppiumAppManagement) {
    try {
      await wda("POST", `/session/${sessionId}/wda/apps/terminate`, { bundleId });
      console.log(`[DEEPLINK] terminated app ${bundleId} via WDA`);
      return true;
    } catch (error) {
      console.log(`[DEEPLINK] terminate ${bundleId} via WDA skipped: ${error.message}`);
      return false;
    }
  }
  try {
    await appium("POST", `/session/${sessionId}/execute/sync`, {
      script: "mobile: terminateApp",
      args: [{ bundleId }],
    });
    console.log(`[DEEPLINK] terminated app ${bundleId}`);
    return true;
  } catch (error) {
    console.log(`[DEEPLINK] terminate ${bundleId} skipped: ${error.message}`);
    return false;
  }
}

async function prepareDeepLinkState() {
  let changed = false;
  if (config.deeplinkTerminateTikTokBeforeOpen && config.tiktokBundleId) {
    changed = await terminateApp(config.tiktokBundleId) || changed;
  }
  if (config.deeplinkTerminateSafariBeforeOpen) {
    changed = await terminateApp("com.apple.mobilesafari") || changed;
  }
  if (config.deeplinkDismissFloatingOverlay) {
    changed = await dismissFloatingOverlay() || changed;
  }
  if (changed && config.deeplinkPreOpenSettleMs > 0) {
    console.log(`[DEEPLINK] pre-open cleanup settle ${config.deeplinkPreOpenSettleMs}ms`);
    await sleep(config.deeplinkPreOpenSettleMs);
  }
}

async function dismissFloatingOverlay() {
  try {
    await activateApp("com.apple.springboard", "SpringBoard");
    await sleep(250);
    const selectors = [
      { using: "-ios class chain", value: "**/XCUIElementTypeButton[`label CONTAINS[c] 'Close' OR name CONTAINS[c] 'Close' OR label CONTAINS[c] 'Đóng' OR name CONTAINS[c] 'Đóng'`]" },
      { using: "-ios class chain", value: "**/XCUIElementTypeButton[`label CONTAINS[c] 'Picture' OR name CONTAINS[c] 'Picture' OR label CONTAINS[c] 'PiP' OR name CONTAINS[c] 'PiP'`]" },
      { using: "accessibility id", value: "Close" },
      { using: "accessibility id", value: "Đóng" },
      { using: "accessibility id", value: "Stop Picture in Picture" },
      { using: "accessibility id", value: "Close Picture in Picture" },
    ];
    return await clickFirstElement(selectors, "floating overlay close");
  } catch (error) {
    console.log(`[DEEPLINK] dismiss floating overlay skipped: ${error.message}`);
  }
  return false;
}

async function activeAppInfo() {
  if (!config.preferAppiumAppManagement) {
    try {
      const response = await wda("GET", `/session/${sessionId}/wda/activeAppInfo`);
      const val = response.value || {};
      return {
        bundleId: val.bundleId || val.bundleID || val.bundle || "",
        pid: val.pid,
        name: val.name,
        state: val.state,
      };
    } catch (error) {
      console.log(`active app info via WDA skipped: ${error.message}`);
    }
  }
  try {
    const response = await appium("POST", `/session/${sessionId}/execute/sync`, {
      script: "mobile: activeAppInfo",
      args: [],
    });
    return response.value || {};
  } catch (error) {
    console.log(`active app info skipped: ${error.message}`);
    return {};
  }
}

async function recoverTikTokFullscreenAfterDeeplink() {
  if (!config.tiktokBundleId) {
    return { foreground: "unknown", recovered: false };
  }
  const beforeInfo = await activeAppInfo();
  let foreground = String(beforeInfo.bundleId || "");
  if (foreground !== config.tiktokBundleId) {
    return { foreground: foreground || "unknown", recovered: false };
  }

  let recovered = false;
  if (config.deeplinkTerminateSafariAfterOpen) {
    recovered = await terminateApp("com.apple.mobilesafari") || recovered;
  }
  if (config.deeplinkForceActivateTikTokAfterOpen) {
    await activateTikTok();
    recovered = true;
  }
  if (recovered && config.deeplinkFullscreenSettleMs > 0) {
    await sleep(config.deeplinkFullscreenSettleMs);
  }
  const afterInfo = await activeAppInfo();
  foreground = String(afterInfo.bundleId || foreground || "");
  console.log(
    `[DEEPLINK] fullscreen recover recovered=${recovered}`
    + ` foreground_before=${String(beforeInfo.bundleId || "unknown")}`
    + ` foreground_after=${foreground || "unknown"}`,
  );
  return { foreground: foreground || "unknown", recovered };
}

async function tapSafariOpenFallbacks() {
  let rect = cachedViewportRect || {};
  let width = Number(rect.width || 0);
  let height = Number(rect.height || 0);
  if ((width <= 0 || height <= 0) && sessionId) {
    try {
      const r = await appium("GET", `/session/${sessionId}/window/rect`);
      rect = r.value || {};
      width = Number(rect.width || 0);
      height = Number(rect.height || 0);
      if (width > 0) cachedViewportRect = rect;
    } catch {}
  }
  // hardcode iPhone viewport fallback (390x844 logical pts)
  if (width <= 0) width = 390;
  if (height <= 0) height = 844;
  if (config.deeplinkSafariFallbackTaps <= 0) {
    return 0;
  }
  const points = [
    [0.50, 0.88],
    [0.50, 0.93],
    [0.78, 0.90],
  ].slice(0, Math.max(0, Math.round(config.deeplinkSafariFallbackTaps)));
  let tapped = 0;
  for (const [xRatio, yRatio] of points) {
    const info = await activeAppInfo();
    const foreground = String(info.bundleId || "");
    if (config.tiktokBundleId && foreground === config.tiktokBundleId) break;
    if (foreground && foreground !== "com.apple.mobilesafari") {
      break;
    }
    const x = Math.round(width * xRatio);
    const y = Math.round(height * yRatio);
    console.log(`[DEEPLINK] Safari fallback tap Open/Mở at ${x},${y}`);
    await tapAt(x, y);
    tapped += 1;
    await sleep(Math.max(250, config.deeplinkAlertSettleMs));
  }
  return tapped;
}

async function settleDeepLinkToTikTok() {
  let acceptedPrompt = false;
  const deadline = Date.now() + Math.max(1200, config.deeplinkAlertWaitMs + config.deeplinkPostOpenSettleMs);
  let lastBundleId = "";
  while (Date.now() < deadline) {
    const info = await activeAppInfo();
    lastBundleId = String(info.bundleId || "");
    if (!config.tiktokBundleId || lastBundleId === config.tiktokBundleId) {
      return { acceptedPrompt, foreground: lastBundleId || "unknown" };
    }
    const accepted = await acceptOpenInTikTokIfNeeded();
    acceptedPrompt = acceptedPrompt || accepted;
    if (!accepted && lastBundleId === "com.apple.mobilesafari") {
      const fallbackTaps = await tapSafariOpenFallbacks();
      acceptedPrompt = acceptedPrompt || fallbackTaps > 0;
    }
    if (config.deeplinkAlertSettleMs > 0) await sleep(config.deeplinkAlertSettleMs);
    const afterInfo = await activeAppInfo();
    lastBundleId = String(afterInfo.bundleId || lastBundleId || "");
    if (!config.tiktokBundleId || lastBundleId === config.tiktokBundleId) {
      return { acceptedPrompt, foreground: lastBundleId || "unknown" };
    }
    console.log(`[DEEPLINK] foreground=${lastBundleId || "unknown"}, waiting for TikTok/open prompt`);
    await sleep(250);
  }
  return { acceptedPrompt, foreground: lastBundleId || "unknown" };
}

async function dismissTikTokBlockingPrompts(jobUrl) {
  const selectors = [
    { using: "accessibility id", value: "Bỏ qua" },
    { using: "accessibility id", value: "Skip" },
    { using: "accessibility id", value: "Not Now" },
    { using: "accessibility id", value: "Không phải bây giờ" },
    { using: "accessibility id", value: "Để sau" },
    { using: "accessibility id", value: "Close" },
    { using: "accessibility id", value: "Đóng" },
  ];

  let changed = false;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const clicked = await clickFirstElement(selectors, `TikTok blocking prompt attempt=${attempt}`);
    if (!clicked) break;
    changed = true;
    await sleep(500);
  }
  if (changed && jobUrl) {
    console.log("[DEEPLINK] TikTok blocking prompt dismissed; reopening deeplink");
    await openDeepLinkViaUrlFallback(jobUrl);
    await settleDeepLinkToTikTok();
  }
  return changed;
}

async function tapAt(x, y) {
  console.log(`Tapping at ${x},${y}`);
  await appium("POST", `/session/${sessionId}/actions`, {
    actions: [
      {
        type: "pointer",
        id: "finger1",
        parameters: { pointerType: "touch" },
        actions: [
          { type: "pointerMove", duration: 0, x, y },
          { type: "pointerDown", button: 0 },
          { type: "pause", duration: 80 },
          { type: "pointerUp", button: 0 },
        ],
      },
    ],
  });
}

async function scheduledWdaTap(x, y, delayMs) {
  console.log(`Scheduling WDA tap at ${x},${y} after ${delayMs}ms`);
  await requestJson(`${config.wdaUrl}/wda/scheduledTap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ x, y, delayMs }),
  });
}

function openTargetTime(job, nowMs = Date.now()) {
  return timing.openTargetTime(job, nowMs, {
    allowClickAfterFallback: config.allowClickAfterFallback,
    clockSource: config.clockSource,
    log: (message) => console.log(message),
    timezone: localTimezoneLabel(),
  });
}

function openTapRequestTime(targetAtMs, requestLeadMs) {
  return timing.openTapRequestTime(targetAtMs, requestLeadMs);
}

function jobTimeWindow(job, nowMs = Date.now(), minMs = config.liveTimeMinMs, maxMs = config.liveTimeMaxMs) {
  return timing.jobTimeWindow(job, nowMs, minMs, maxMs, {
    allowClickAfterFallback: config.allowClickAfterFallback,
    clockSource: config.clockSource,
    log: (message) => console.log(message),
    timezone: localTimezoneLabel(),
  });
}

function localTimeLabel(timestampMs) {
  return timing.localTimeLabel(timestampMs);
}

async function sleepUntil(timestampMs) {
  while (!stopping) {
    const remaining = timestampMs - Date.now();
    if (remaining <= 0) return;
    await sleep(Math.min(remaining, 1000));
  }
}

async function sleepUntilWithLease(timestampMs, jobId, reason = "waiting") {
  let nextHeartbeatMs = 0;
  while (!stopping) {
    const nowMs = Date.now();
    const remaining = timestampMs - nowMs;
    if (remaining <= 0) return;
    if (jobId && nowMs >= nextHeartbeatMs) {
      await report(jobId, "waiting_time_window", JSON.stringify({
        reason,
        wake_at_ms: timestampMs,
        remaining_ms: remaining,
      })).catch((error) => console.warn(`Job #${jobId}: lease heartbeat failed: ${error.message}`));
      nextHeartbeatMs = nowMs + 15_000;
    }
    await sleep(Math.min(remaining, 1000));
  }
}

async function openButtonPoint() {
  const rect = cachedViewportRect || {};
  const width = Number(rect.width || 0);
  const height = Number(rect.height || 0);
  if (width <= 0 || height <= 0) {
    throw new Error(`Invalid viewport rect: ${JSON.stringify(rect)}`);
  }
  return {
    x: Math.round(width * config.openButtonXRatio),
    y: Math.round(height * config.openButtonYRatio),
    rect,
  };
}

async function detectOpenButtonFromScreenshot(jobId) {
  if (!config.openButtonDetectEnabled) return null;
  try {
    const shot = await capture(jobId, { stage: "before_open_button_detect" });
    const detection = await runJson(config.pythonPath, [
      path.join(__dirname, "detect_open_button.py"),
      "--image", shot.localPath,
    ]);
    if (!detection?.found || !detection.tap) {
      console.log(`Job #${jobId}: Open button detector miss ${JSON.stringify(detection)}`);
      return null;
    }
    const scale = await viewportScale(detection.screen || shot.sourceScreen);
    const point = {
      x: Math.round(Number(detection.tap.x) / scale.x),
      y: Math.round(Number(detection.tap.y) / scale.y),
      rect: scale.rect,
      detection,
      mode: "screenshot_detect",
    };
    console.log(
      `Job #${jobId}: Open button detector hit screenshot=${detection.tap.x},${detection.tap.y}`
      + ` viewport=${point.x},${point.y} score=${detection.score}`,
    );
    return point;
  } catch (error) {
    console.log(`Job #${jobId}: Open button detector error: ${error.message}`);
    return null;
  }
}

async function tapOpenButtonAtDeadline(job) {
  const nowMs = Date.now();
  const schedule = openTargetTime(job, nowMs);
  if (!schedule) {
    console.log(`Job #${job.id}: no TIME/click_after_ms, skip Open button`);
    await report(job.id, "open_time_missing");
    return false;
  }

  console.log([
    `[TIMING] Job #${job.id}`,
    `  target  : ${localTimeLabel(schedule.targetAtMs)}`,
    `  now     : ${localTimeLabel(nowMs)}`,
    `  remaining: ${((schedule.targetAtMs - nowMs) / 1000).toFixed(2)}s`,
    `  tap lead: -${config.openTapRequestLeadMs}ms | post settle: ${config.openPostTapSettleMs}ms`,
  ].join("\n"));

  const remainingBeforePointMs = schedule.targetAtMs - Date.now();
  const point = remainingBeforePointMs >= config.openDetectMinRemainingMs
    ? await detectOpenButtonFromScreenshot(job.id) || await openButtonPoint()
    : await openButtonPoint();
  const requestAtMs = openTapRequestTime(schedule.targetAtMs, config.openTapRequestLeadMs);
  const lateness = Date.now() - schedule.targetAtMs;
  if (lateness > config.openMaxLatenessMs) {
    console.log(`Job #${job.id}: Open deadline missed by ${lateness}ms, skip tap`);
    await report(job.id, "open_deadline_missed", JSON.stringify({ ...schedule, lateness }));
    return false;
  }

  console.log(
    `Job #${job.id}: Open target ${localTimeLabel(schedule.targetAtMs)} `
    + `source=${schedule.source}; mode=scheduled_wda; tap at ${point.x},${point.y}; `
    + `schedule lead=${config.openTapRequestLeadMs}ms`,
  );
  await sleepUntil(requestAtMs);

  const requestedAtMs = Date.now();
  const delayMs = Math.max(
    0,
    schedule.targetAtMs - requestedAtMs,
  );
  console.log(
    `[TIMING] Job #${job.id}: sending WDA scheduledTap`
    + ` | delayMs=${delayMs}ms | expected tap: ${localTimeLabel(requestedAtMs + delayMs)}`
    + ` | target: ${localTimeLabel(schedule.targetAtMs)}`
    + ` | drift: ${requestedAtMs + delayMs - schedule.targetAtMs}ms`,
  );
  try {
    await scheduledWdaTap(point.x, point.y, delayMs);
  } catch (error) {
    if (delayMs > 0) throw error;
    console.warn(`Job #${job.id}: scheduledTap failed at deadline, falling back to immediate session tap: ${error.message}`);
    await tapAt(point.x, point.y);
  }
  await sleepUntil(requestedAtMs + delayMs + config.openPostTapSettleMs);
  const completedAtMs = Date.now();
  const requestOffsetMs = requestedAtMs - schedule.targetAtMs;
  const completedOffsetMs = completedAtMs - schedule.targetAtMs;
  const commandDurationMs = completedAtMs - requestedAtMs;
  console.log(
    `[TIMING] Job #${job.id}: WDA command returned`
    + ` | request offset=${requestOffsetMs}ms vs target`
    + ` | command RTT=${commandDurationMs}ms`
    + ` | completed offset=${completedOffsetMs}ms`,
  );
  await report(job.id, "open_button_tapped", JSON.stringify({
    ...schedule,
    point,
    tap_mode: "scheduled_wda",
    tap_count: 1,
    scheduled_delay_ms: delayMs,
    transport_compensation_ms: config.openTapTransportCompensationMs,
    requested_at_ms: requestedAtMs,
    completed_at_ms: completedAtMs,
    request_offset_ms: requestOffsetMs,
    completed_offset_ms: completedOffsetMs,
    command_duration_ms: commandDurationMs,
  }));
  return true;
}

async function tapTreasure() {
  if (!config.treasureTapEnabled) return;
  await tapAt(config.treasureTapX, config.treasureTapY);
}

function treasureTemplatePaths() {
  return String(config.treasureTemplatePath || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

async function detectTreasure(imagePath) {
  if (!config.treasureDetectEnabled) return null;
  const templates = treasureTemplatePaths();
  let best = null;
  const startedAtMs = Date.now();
  for (const templatePath of templates) {
    const args = [
      path.join(__dirname, "detect_treasure.py"),
      "--image", imagePath,
      "--template", templatePath,
      "--threshold", String(config.treasureThreshold),
      "--min-red-ratio", String(config.treasureMinRedRatio),
      "--min-warm-ratio", String(config.treasureMinWarmRatio),
      "--scales", config.treasureScales,
      "--roi", config.treasureRoi,
    ];
    if (debugMode.shouldWriteImages(config.treasureDebugMode)) {
      args.push("--debug-dir", config.treasureDebugDir);
    }
    try {
      await fs.access(config.treasureMaskPath);
      args.push("--mask", config.treasureMaskPath);
    } catch {}
    const detection = await runJson(config.pythonPath, args);
    detection.detect_elapsed_ms = Date.now() - startedAtMs;
    const detectionRank = detection?.found ? 1 : 0;
    const bestRank = best?.found ? 1 : 0;
    if (
      !best
      || detectionRank > bestRank
      || (
        detectionRank === bestRank
        && Number(detection?.score || 0) > Number(best?.score || 0)
      )
    ) {
      best = detection;
    }
    if (
      detection?.found
      && detection?.timer_label?.found
      && Number(detection?.score || 0) >= config.treasureEarlyExitScore
    ) {
      console.log(
        `Treasure detect early exit template=${templatePath}`
        + ` method=${detection.method || "unknown"} score=${detection.score}`
        + ` elapsed=${detection.detect_elapsed_ms}ms`,
      );
      return detection;
    }
  }
  if (best) best.detect_elapsed_ms = Date.now() - startedAtMs;
  return best;
}

async function appendTreasureDebug(jobId, payload) {
  if (!debugMode.shouldWriteJson(config.treasureDebugMode)) return;
  try {
    await fs.mkdir(config.treasureDebugDir, { recursive: true });
    const line = JSON.stringify({
      ts: new Date().toISOString(),
      device_id: config.deviceId,
      job_id: jobId,
      ...payload,
    });
    await fs.appendFile(path.join(config.treasureDebugDir, `job-${jobId}-scan.jsonl`), `${line}\n`);
  } catch (error) {
    console.warn(`Job #${jobId}: write treasure debug failed: ${error.message}`);
  }
}

async function cleanupCapture(shot) {
  if (debugMode.shouldKeepCapture(config.treasureDebugMode)) return;
  if (!shot?.localPath) return;
  await fs.unlink(shot.localPath).catch(() => {});
}

function runJson(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: __dirname });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(stderr || stdout || `${command} exited ${code}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout || "{}"));
      } catch (error) {
        reject(new Error(`Invalid JSON from ${command}: ${stdout || stderr}`));
      }
    });
  });
}

async function capture(jobId, options = {}) {
  const response = await appium("GET", `/session/${sessionId}/screenshot`);
  const capturedAtMs = Date.now();
  const fullImage = Buffer.from(response.value, "base64");
  const fullMetadata = await sharp(fullImage).metadata();
  const sourceScreen = {
    w: Number(fullMetadata.width || 0),
    h: Number(fullMetadata.height || 0),
  };
  const image = options.topLeftQuarter
    ? (await topLeftQuarter(fullImage)).image
    : fullImage;
  await fs.mkdir(config.captureDir, { recursive: true });
  const filename = `job-${jobId}-${Date.now()}.png`;
  const localPath = path.join(config.captureDir, filename);
  await fs.writeFile(localPath, image);
  return { image, localPath, sourceScreen, capturedAtMs };
}

async function upload(jobId, image, stage = "screenshot") {
  const response = await fetch(`${config.queueUrl}/api/phone/screenshot`, {
    method: "POST",
    headers: {
      "Content-Type": "image/png",
      "X-Job-ID": String(jobId),
      "X-Device-ID": config.deviceId,
      "X-Stage": stage,
    },
    body: image,
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(`${response.status} ${body.error || response.statusText}`);
  }
  return body;
}

async function captureDebugStage(jobId, stage) {
  if (!debugMode.shouldWriteImages(config.treasureDebugMode)) return null;
  try {
    const shot = await capture(jobId, { stage });
    console.log(`[DEBUG CAPTURE] Job #${jobId}: ${stage} saved at ${shot.localPath}`);
    return shot;
  } catch (error) {
    console.warn(`[DEBUG CAPTURE] Job #${jobId}: ${stage} failed: ${error.message}`);
    return null;
  }
}

async function topLeftQuarter(image) {
  const source = sharp(image);
  const metadata = await source.metadata();
  const width = Math.max(1, Math.floor(Number(metadata.width || 1) / 2));
  const height = Math.max(1, Math.floor(Number(metadata.height || 1) / 2));
  const cropped = await source.extract({ left: 0, top: 0, width, height }).png().toBuffer();
  return { image: cropped, width, height };
}

async function detectTreasureBlockingOverlay(image) {
  if (!config.treasureOverlayWaitEnabled) return { found: false };
  try {
    const source = sharp(image).ensureAlpha();
    const { data, info } = await source.raw().toBuffer({ resolveWithObject: true });
    const width = Number(info.width || 0);
    const height = Number(info.height || 0);
    const channels = Number(info.channels || 4);
    if (width <= 0 || height <= 0 || channels < 3) return { found: false };

    const x0 = 0;
    const x1 = Math.min(width, 430);
    const y0 = Math.min(height - 1, 235);
    const y1 = Math.min(height, 370);
    const sampleW = Math.max(1, x1 - x0);
    let pinkPixels = 0;
    let totalPixels = 0;
    let strongRows = 0;
    let firstStrongY = -1;
    let lastStrongY = -1;

    for (let y = y0; y < y1; y += 1) {
      let rowPink = 0;
      for (let x = x0; x < x1; x += 1) {
        const index = (y * width + x) * channels;
        const r = data[index];
        const g = data[index + 1];
        const b = data[index + 2];
        const isPinkBanner =
          r >= 145
          && g <= 130
          && b <= 170
          && r >= g + 35
          && r >= b - 10;
        if (isPinkBanner) {
          rowPink += 1;
          pinkPixels += 1;
        }
        totalPixels += 1;
      }
      if (rowPink / sampleW >= 0.18) {
        strongRows += 1;
        if (firstStrongY < 0) firstStrongY = y;
        lastStrongY = y;
      }
    }

    const ratio = totalPixels > 0 ? pinkPixels / totalPixels : 0;
    const found = strongRows >= 18 && ratio >= 0.08;
    return {
      found,
      ratio: Number(ratio.toFixed(4)),
      strong_rows: strongRows,
      box: found ? { x: x0, y: firstStrongY, w: sampleW, h: lastStrongY - firstStrongY + 1 } : null,
    };
  } catch (error) {
    return { found: false, error: error.message };
  }
}

async function tapCluster(x, y) {
  const spread = Math.max(0, config.treasureTapSpread);
  const points = spread > 0
    ? [[x, y], [x, y + spread], [x + spread, y], [x - spread, y], [x, y - spread]]
    : [[x, y]];
  for (const [px, py] of points) {
    await tapAt(Math.max(0, Math.round(px)), Math.max(0, Math.round(py)));
    await sleep(120);
  }
}

async function viewportScale(screen) {
  const rect = cachedViewportRect || {};
  const width = Number(rect.width || 0);
  const height = Number(rect.height || 0);
  return {
    x: width > 0 ? Number(screen?.w || width) / width : 1,
    y: height > 0 ? Number(screen?.h || height) / height : 1,
    rect,
  };
}

async function tapClusterFromScreenshotPoint(x, y, screen) {
  const scale = await viewportScale(screen);
  const pointX = Math.round(x / scale.x);
  const pointY = Math.round(y / scale.y);
  console.log(`Screenshot tap ${x},${y} -> viewport tap ${pointX},${pointY} scale=${scale.x.toFixed(2)},${scale.y.toFixed(2)}`);
  await tapCluster(pointX, pointY);
}

function detectionScore(detection) {
  return Number(detection?.score || 0);
}

function detectionTapDistance(a, b) {
  const ax = Number(a?.tap?.x);
  const ay = Number(a?.tap?.y);
  const bx = Number(b?.tap?.x);
  const by = Number(b?.tap?.y);
  if (![ax, ay, bx, by].every(Number.isFinite)) return Infinity;
  return Math.hypot(ax - bx, ay - by);
}

async function cleanupCandidate(candidate, keepShot = null) {
  const keepShots = Array.isArray(keepShot) ? keepShot : [keepShot];
  if (!candidate?.shot || keepShots.includes(candidate.shot)) return;
  await cleanupCapture(candidate.shot);
}

function buildTreasureCandidate(detection, shot, previous = null) {
  const now = Date.now();
  const isSameTarget = previous
    && now - previous.lastSeenAtMs <= Math.max(0, config.treasureCandidateTtlMs)
    && detectionTapDistance(previous.detection, detection) <= Math.max(1, config.treasureSameTargetDistance);
  const confirmations = isSameTarget ? previous.confirmations + 1 : 1;
  return {
    detection,
    shot,
    confirmations,
    firstSeenAtMs: isSameTarget ? previous.firstSeenAtMs : now,
    lastSeenAtMs: now,
    score: detectionScore(detection),
  };
}

function candidateTapReady(candidate) {
  if (!candidate?.detection?.found || !candidate?.detection?.tap) return false;
  const frameAgeMs = treasureFrameAgeMs(candidate.shot);
  if (frameAgeMs > Math.max(0, config.treasureMaxFrameAgeMs)) return false;
  if (candidate.score >= config.treasureTapScore) return true;
  return candidate.confirmations >= Math.max(1, Math.floor(config.treasureConfirmFrames));
}

function treasureFrameAgeMs(shot) {
  return shot?.capturedAtMs ? Date.now() - shot.capturedAtMs : 0;
}

function treasureShotFresh(shot) {
  return treasureFrameAgeMs(shot) <= Math.max(0, config.treasureMaxFrameAgeMs);
}

async function detectTreasureConfirmSheet(imagePath) {
  // Detect the "Mở Rương Báu" confirmation bottom sheet:
  // large white area covering bottom ~50% of screen while top half is live video (dark).
  try {
    const source = sharp(imagePath).ensureAlpha();
    const { data, info } = await source.raw().toBuffer({ resolveWithObject: true });
    const w = Number(info.width || 0);
    const h = Number(info.height || 0);
    const ch = Number(info.channels || 4);
    if (w <= 0 || h <= 0) return { found: false };
    // Sample bottom 45% of screen — should be mostly white if sheet is open.
    const y0 = Math.floor(h * 0.55);
    let whitePixels = 0;
    let total = 0;
    for (let y = y0; y < h; y += 4) {
      for (let x = 0; x < w; x += 4) {
        const i = (y * w + x) * ch;
        const r = data[i], g = data[i + 1], b = data[i + 2];
        if (r >= 230 && g >= 230 && b >= 230) whitePixels++;
        total++;
      }
    }
    const ratio = total > 0 ? whitePixels / total : 0;
    // Also check top 40% is NOT white (it's live video).
    let topWhite = 0, topTotal = 0;
    for (let y = 0; y < Math.floor(h * 0.40); y += 4) {
      for (let x = 0; x < w; x += 4) {
        const i = (y * w + x) * ch;
        const r = data[i], g = data[i + 1], b = data[i + 2];
        if (r >= 230 && g >= 230 && b >= 230) topWhite++;
        topTotal++;
      }
    }
    const topRatio = topTotal > 0 ? topWhite / topTotal : 0;
    const found = ratio >= 0.60 && topRatio < 0.25;
    return { found, bottom_white_ratio: Number(ratio.toFixed(3)), top_white_ratio: Number(topRatio.toFixed(3)) };
  } catch {
    return { found: false };
  }
}

async function detectKeyboardOpen(imagePath) {
  // Keyboard (including emoji keyboard) covers bottom ~40% with light gray/white uniform color.
  // Distinguishable from confirm sheet: keyboard has no live video in top half (stream still visible).
  try {
    const source = sharp(imagePath).ensureAlpha();
    const { data, info } = await source.raw().toBuffer({ resolveWithObject: true });
    const w = Number(info.width || 0);
    const h = Number(info.height || 0);
    const ch = Number(info.channels || 4);
    if (w <= 0 || h <= 0) return false;
    // Bottom 40% should be very light (keyboard bg is #f0f0f0 or white).
    const y0 = Math.floor(h * 0.60);
    let lightPixels = 0, total = 0;
    for (let y = y0; y < h; y += 4) {
      for (let x = 0; x < w; x += 4) {
        const i = (y * w + x) * ch;
        const r = data[i], g = data[i + 1], b = data[i + 2];
        if (r >= 200 && g >= 200 && b >= 200) lightPixels++;
        total++;
      }
    }
    const bottomRatio = total > 0 ? lightPixels / total : 0;
    // Top 40% should NOT be light (live video is dark).
    let topLight = 0, topTotal = 0;
    for (let y = 0; y < Math.floor(h * 0.40); y += 4) {
      for (let x = 0; x < w; x += 4) {
        const i = (y * w + x) * ch;
        const r = data[i], g = data[i + 1], b = data[i + 2];
        if (r >= 200 && g >= 200 && b >= 200) topLight++;
        topTotal++;
      }
    }
    const topRatio = topTotal > 0 ? topLight / topTotal : 0;
    return bottomRatio >= 0.70 && topRatio < 0.30;
  } catch { return false; }
}

async function scanTreasure(jobId, options = {}) {
  const configuredDeadline = Date.now() + Math.max(0, config.treasureScanSeconds) * 1000;
  const deadline = Math.min(configuredDeadline, Number(options.deadlineAtMs || configuredDeadline));
  // Always allow at least 2 real detection attempts regardless of deadline.
  const minDetectAttempts = 2;
  let attempt = 0;
  let detectAttempt = 0;
  let hotCandidate = null;
  let bestDetection = null;
  let bestShot = null;
  if (deadline <= Date.now()) {
    return { detection: null, shot: null };
  }
  do {
    attempt += 1;
    // Detect and dismiss the "Mở Rương Báu" confirmation sheet before scanning.
    // It appears as a large white bottom sheet covering ~50% of screen.
    const fullShot = await capture(jobId, { topLeftQuarter: false });
    const confirmSheet = await detectTreasureConfirmSheet(fullShot.image);
    if (confirmSheet.found) {
      console.log(`Job #${jobId}: treasure confirm sheet detected, dismissing (tap top area)`);
      const rect = cachedViewportRect || {};
      const w = Number(rect.width || 390);
      const h = Number(rect.height || 844);
      await tapAt(Math.round(w * 0.5), Math.round(h * 0.25));
      await cleanupCapture(fullShot);
      await sleep(400);
      continue;
    }
    const keyboardOpen = await detectKeyboardOpen(fullShot.image);
    if (keyboardOpen) {
      console.log(`Job #${jobId}: keyboard detected, dismissing before scan`);
      const rect = cachedViewportRect || {};
      const w = Number(rect.width || 390);
      const h = Number(rect.height || 844);
      // Tap center of live video area to close keyboard
      await tapAt(Math.round(w * 0.5), Math.round(h * 0.30));
      await cleanupCapture(fullShot);
      await sleep(500);
      continue;
    }
    await cleanupCapture(fullShot);
    const shot = await capture(jobId, { topLeftQuarter: true });
    const overlay = await detectTreasureBlockingOverlay(shot.image);
    const overlayWaitMs = Math.min(
      config.treasureOverlayWaitMs,
      Math.max(0, deadline - Date.now() - 250),
    );
    const canWaitOverlay = overlay.found && overlayWaitMs >= Math.max(300, config.treasureScanIntervalMs);
    if (canWaitOverlay) {
      console.log(`Job #${jobId}: treasure blocker overlay visible ${JSON.stringify(overlay)}, waiting ${overlayWaitMs}ms`);
      await appendTreasureDebug(jobId, {
        attempt,
        image: shot.localPath,
        captured_at_ms: shot.capturedAtMs,
        source_screen: shot.sourceScreen,
        overlay,
        detection: null,
        skipped_detection: "treasure_blocking_overlay",
      });
      await cleanupCapture(shot);
      await sleep(overlayWaitMs);
      continue;
    }
    detectAttempt += 1;
    const detection = await detectTreasure(shot.localPath);
    if (detection) {
      detection.attempt = attempt;
      detection.scan_image = detection.screen;
      detection.screen = shot.sourceScreen;
      detection.blocking_overlay = overlay;
    }
    console.log(`Job #${jobId}: treasure scan #${attempt} detect#${detectAttempt} ${JSON.stringify(detection)}`);
    await appendTreasureDebug(jobId, {
      attempt,
      image: shot.localPath,
      captured_at_ms: shot.capturedAtMs,
      source_screen: shot.sourceScreen,
      roi: config.treasureRoi,
      threshold: config.treasureThreshold,
      stabilize_delay_ms: config.treasureStabilizeDelayMs,
      scan_interval_ms: config.treasureScanIntervalMs,
      tap_score: config.treasureTapScore,
      confirm_frames: config.treasureConfirmFrames,
      candidate_ttl_ms: config.treasureCandidateTtlMs,
      max_frame_age_ms: config.treasureMaxFrameAgeMs,
      overlay,
      detection,
    });
    if (!bestDetection || Number(detection?.score || 0) > Number(bestDetection?.score || 0)) {
      if (bestShot && bestShot !== shot) await cleanupCapture(bestShot);
      bestDetection = detection;
      bestShot = shot;
    }
    if (detection?.found && detection.tap) {
      const previousCandidate = hotCandidate;
      hotCandidate = buildTreasureCandidate(detection, shot, hotCandidate);
      console.log(
        `Job #${jobId}: treasure candidate score=${hotCandidate.score}`
        + ` confirmations=${hotCandidate.confirmations}/${Math.max(1, Math.floor(config.treasureConfirmFrames))}`
        + ` age=${treasureFrameAgeMs(shot)}ms`,
      );
      await cleanupCandidate(previousCandidate, [hotCandidate.shot, bestShot]);
      if (candidateTapReady(hotCandidate)) {
        console.log(`Job #${jobId}: treasure candidate ready, tapping without extra settle`);
        return {
          detection: {
            ...hotCandidate.detection,
            candidate_confirmations: hotCandidate.confirmations,
            candidate_score: hotCandidate.score,
            candidate_age_ms: treasureFrameAgeMs(hotCandidate.shot),
            candidate_reason: hotCandidate.score >= config.treasureTapScore ? "high_score" : "confirmed_frames",
          },
          shot: hotCandidate.shot,
        };
      }
      // Medium-confidence hits get a very short confirm pass; high-confidence hits tap above.
      await sleep(Math.min(180, Math.max(0, config.treasureScanIntervalMs)));
      continue;
    } else {
      const hotAgeMs = hotCandidate ? Date.now() - hotCandidate.lastSeenAtMs : Infinity;
      if (hotCandidate && hotAgeMs <= Math.max(0, config.treasureCandidateTtlMs) && candidateTapReady(hotCandidate)) {
        console.log(`Job #${jobId}: treasure detector missed one frame, using hot candidate age=${hotAgeMs}ms`);
        await cleanupCapture(shot);
        return {
          detection: {
            ...hotCandidate.detection,
            candidate_confirmations: hotCandidate.confirmations,
            candidate_score: hotCandidate.score,
            candidate_age_ms: treasureFrameAgeMs(hotCandidate.shot),
            candidate_reason: "hot_candidate",
          },
          shot: hotCandidate.shot,
        };
      }
      if (hotCandidate && hotAgeMs > Math.max(0, config.treasureCandidateTtlMs)) {
        await cleanupCandidate(hotCandidate, bestShot);
        hotCandidate = null;
      }
      await cleanupCapture(shot);
    }
    // Always retry at least minDetectAttempts times even if deadline passed.
    const pastDeadline = Date.now() >= deadline;
    if (pastDeadline && detectAttempt >= minDetectAttempts) break;
    if (config.treasureScanIntervalMs > 0) {
      await sleep(config.treasureScanIntervalMs);
    }
  } while (Date.now() < deadline || detectAttempt < minDetectAttempts);
  if (hotCandidate && candidateTapReady(hotCandidate)) {
    if (bestShot && bestShot !== hotCandidate.shot) await cleanupCapture(bestShot);
    return {
      detection: {
        ...hotCandidate.detection,
        candidate_confirmations: hotCandidate.confirmations,
        candidate_score: hotCandidate.score,
        candidate_age_ms: treasureFrameAgeMs(hotCandidate.shot),
        candidate_reason: "deadline_hot_candidate",
      },
      shot: hotCandidate.shot,
    };
  }
  await cleanupCandidate(hotCandidate, bestShot);
  if (bestDetection?.found && bestDetection.tap && treasureShotFresh(bestShot)) {
    return {
      detection: {
        ...bestDetection,
        candidate_reason: "fresh_best_detection",
        candidate_age_ms: treasureFrameAgeMs(bestShot),
      },
      shot: bestShot,
    };
  }
  if (bestDetection?.found && bestDetection.tap) {
    console.log(
      `Job #${jobId}: best treasure detection is stale `
      + `age=${treasureFrameAgeMs(bestShot)}ms max=${config.treasureMaxFrameAgeMs}ms; skip tap`,
    );
    return {
      detection: {
        ...bestDetection,
        found: false,
        stale: true,
        reject_reasons: [...(bestDetection.reject_reasons || []), "stale_frame"],
        candidate_age_ms: treasureFrameAgeMs(bestShot),
      },
      shot: bestShot,
    };
  }
  return { detection: bestDetection, shot: bestShot };
}

function adaptiveTreasureSettleMs(job, nowMs = Date.now()) {
  const schedule = openTargetTime(job, nowMs);
  if (!schedule) return config.screenshotDelayMs;
  const latestTreasureDoneAtMs = schedule.targetAtMs
    - config.openTapRequestLeadMs
    - config.openSafetyReserveMs
    - config.treasureTapBudgetMs;
  const spareBeforeScanMs = latestTreasureDoneAtMs - nowMs;
  if (spareBeforeScanMs <= 300) return 300;
  const desiredSettleMs = Math.max(config.screenshotDelayMs, config.treasureInitialSettleMs);
  return Math.min(desiredSettleMs, Math.max(300, spareBeforeScanMs - 700));
}

function isMissingSessionError(error) {
  const message = String(error?.message || error || "").toLowerCase();
  return message.includes("session does not exist")
    || message.includes("invalid session id")
    || message.includes("no such session")
    || message.includes("fetch failed")
    || message.includes("econnrefused")
    || message.includes("socket hang up")
    || message.includes("connection reset")
    || message.includes("couldn't connect");
}

async function ensureSession() {
  if (!sessionId) {
    await createSession();
    return;
  }
  try {
    await appium("GET", `/session/${sessionId}/window/rect`);
  } catch (error) {
    if (isMissingSessionError(error)) {
      console.log("WDA session expired, recreating before job...");
      sessionId = "";
      cachedViewportRect = null;
      await createSession();
    } else {
      throw error;
    }
  }
}

async function processJob(job, allowSessionRetry = true) {
  const jobStartedAtMs = Date.now();
  const jobUrl = resolveJunbUrl(job.url);
  console.log(`[FLOW] Job #${job.id}: start device=${config.deviceId} opening ${jobUrl}`);
  try {
    await ensureSession();
    try {
      await openDeepLink(jobUrl);
    } catch (error) {
      await report(job.id, "deeplink_open_failed_next_task", JSON.stringify({
        message: error.message,
        mode: config.deeplinkOpenMode,
        fallback_to_url: config.deeplinkFallbackToUrl,
      }));
      console.log(`[FLOW] Job #${job.id}: deeplink open failed without Safari fallback; next task: ${error.message}`);
      return;
    }
    const deeplinkReady = await settleDeepLinkToTikTok();
    let fullscreenReady = await recoverTikTokFullscreenAfterDeeplink();
    if (fullscreenReady.foreground) {
      deeplinkReady.foreground = fullscreenReady.foreground;
    }
    if (
      config.deeplinkRequireTikTokForeground
      && config.deeplinkFallbackToUrl
      && config.tiktokBundleId
      && deeplinkReady.foreground !== config.tiktokBundleId
    ) {
      await openDeepLinkViaUrlFallback(jobUrl);
      const fallbackReady = await settleDeepLinkToTikTok();
      fullscreenReady = await recoverTikTokFullscreenAfterDeeplink();
      deeplinkReady.acceptedPrompt = deeplinkReady.acceptedPrompt || fallbackReady.acceptedPrompt;
      deeplinkReady.foreground = fullscreenReady.foreground || fallbackReady.foreground;
    }
    if (config.deeplinkPostOpenSettleMs > 0) {
      await sleep(config.deeplinkPostOpenSettleMs);
    }
    console.log(
      `[DEEPLINK] ready accepted_prompt=${deeplinkReady.acceptedPrompt}`
      + ` foreground=${deeplinkReady.foreground}`
      + ` fullscreen_recovered=${fullscreenReady.recovered}`
      + ` post_settle=${config.deeplinkPostOpenSettleMs}ms`,
    );
    if (
      config.deeplinkRequireTikTokForeground
      && config.tiktokBundleId
      && deeplinkReady.foreground !== config.tiktokBundleId
      && !(deeplinkReady.foreground === "unknown" && deeplinkReady.acceptedPrompt)
    ) {
      await report(job.id, "deeplink_not_in_tiktok_next_task", JSON.stringify({
        foreground: deeplinkReady.foreground,
        expected: config.tiktokBundleId,
        accepted_prompt: deeplinkReady.acceptedPrompt,
      }));
      console.log(
        `[FLOW] Job #${job.id}: deeplink foreground=${deeplinkReady.foreground}`
        + ` expected=${config.tiktokBundleId}; next task`,
      );
      return;
    }
    await dismissTikTokBlockingPrompts(jobUrl);
    await captureDebugStage(job.id, "after_deeplink_ready");
    await report(job.id, "opened");
    const treasureSettleMs = adaptiveTreasureSettleMs(job);
    if (treasureSettleMs > 0) {
      console.log(`[FLOW] Job #${job.id}: adaptive treasure settle ${treasureSettleMs}ms`);
      await sleep(treasureSettleMs);
    } else {
      console.log(`[FLOW] Job #${job.id}: skip treasure settle; deadline is tight`);
    }
    if (config.treasureTapEnabled) {
      // Treasure tap must finish BEFORE open button scheduledTap — never run 2 WDA commands in parallel.
      // Only run treasure scan if there's enough time before open deadline.
      // Need: scanSeconds + ~2s tap cluster + openTapRequestLeadMs before target.
      const schedule = openTargetTime(job);
      const nowMs = Date.now();
      const remainingMs = schedule ? schedule.targetAtMs - nowMs : Infinity;
      const latestTreasureDoneAtMs = schedule
        ? schedule.targetAtMs - config.openTapRequestLeadMs - config.openSafetyReserveMs
        : Infinity;
      // Spam scan until 3s before open timing — gives enough time for tap cluster.
      const scanStopAtMs = schedule ? schedule.targetAtMs - 3000 : nowMs + config.treasureScanSeconds * 1000;
      const treasureDeadlineAtMs = Math.min(
        nowMs + config.treasureScanSeconds * 1000,
        scanStopAtMs,
      );
      const canRunTreasure = treasureDeadlineAtMs > nowMs + 500;

      let scan = null;
      let treasureReportPromise = Promise.resolve();
      let treasureTapped = false;
      let treasureSkipStatus = "";
      let treasureSkipDetail = "";

      if (canRunTreasure) {
        if (config.treasureDetectEnabled) {
          console.log(
            `[FLOW] Job #${job.id}: treasure scan budget ${Math.max(0, treasureDeadlineAtMs - Date.now())}ms `
            + `remaining_to_open=${schedule ? `${schedule.targetAtMs - Date.now()}ms` : "unknown"}`,
          );
          scan = await scanTreasure(job.id, { deadlineAtMs: treasureDeadlineAtMs });
        } else {
          scan = { detection: null, shot: await capture(job.id) };
        }
        const detection = scan.detection;
        console.log(`Job #${job.id}: treasure detection final ${JSON.stringify(detection)}`);
        if (detection?.found && detection.tap) {
          const tapX = Math.round(Number(detection.tap.x) + config.treasureTapOffsetX);
          const tapY = Math.round(Number(detection.tap.y) + config.treasureTapOffsetY);
          if (config.treasurePreTapDelayMs > 0) {
            await sleep(config.treasurePreTapDelayMs);
          }
          const frameAgeMs = scan.shot?.capturedAtMs ? Date.now() - scan.shot.capturedAtMs : null;
          console.log(`Job #${job.id}: treasure frame age before tap=${frameAgeMs ?? "unknown"}ms`);
          await tapClusterFromScreenshotPoint(tapX, tapY, detection.screen);
          treasureTapped = true;
          treasureReportPromise = report(job.id, "treasure_detected_tapped", JSON.stringify({...detection, tapped: {x: tapX, y: tapY}, spread: config.treasureTapSpread, coordinate_space: "screenshot", frame_age_before_tap_ms: frameAgeMs})).catch(() => {});
          if (config.treasureTapDelayMs > 0) {
            await sleep(config.treasureTapDelayMs);
          }
        } else if (config.treasureDetectEnabled) {
          const fallbackSafe = config.treasureFallbackTapOnMiss
            && Date.now() + config.treasureTapBudgetMs < latestTreasureDoneAtMs;
          if (fallbackSafe) {
            console.log(`Job #${job.id}: treasure not found, fallback tap fixed point ${config.treasureTapX},${config.treasureTapY}`);
            await tapTreasure();
            treasureTapped = true;
            await report(job.id, "treasure_tapped", JSON.stringify({
              fallback: true,
              detection: detection || {},
              point: { x: config.treasureTapX, y: config.treasureTapY },
            }));
            if (config.treasureTapDelayMs > 0) {
              await sleep(config.treasureTapDelayMs);
            }
          } else {
            treasureSkipStatus = "treasure_not_found_next_task";
            treasureSkipDetail = JSON.stringify({ reason: "not_found_or_fallback_unsafe", detection: detection || {} });
            console.log(`Job #${job.id}: treasure not found, fallback unsafe, next task`);
          }
        } else {
          await tapTreasure();
          treasureTapped = true;
          await report(job.id, "treasure_tapped");
        }
      } else {
        treasureSkipStatus = "treasure_scan_skipped_next_task";
        treasureSkipDetail = JSON.stringify({
          reason: "not_enough_time_before_open",
          remaining_ms: remainingMs,
        });
        console.log(
          `Job #${job.id}: treasure scan skipped — only ${(remainingMs / 1000).toFixed(1)}s left before Open safety reserve`,
        );
      }

      if (scan?.shot && debugMode.shouldWriteImages(config.treasureDebugMode)) {
        const uploadedScan = await upload(job.id, scan.shot.image, "treasure_scan_top_left_quarter");
        await report(job.id, "treasure_scan_screenshot_uploaded");
        console.log(
          `Job #${job.id}: treasure scan top-left quarter saved at ${uploadedScan.url}`,
        );
      }
      await treasureReportPromise;
      if (!treasureTapped) {
        const status = treasureSkipStatus || "treasure_not_found_next_task";
        const detail = treasureSkipDetail || JSON.stringify({ reason: "treasure_not_tapped" });
        await report(job.id, status, detail);
        console.log(`[FLOW] Job #${job.id}: ${status}; next task total=${Date.now() - jobStartedAtMs}ms`);
        return;
      }

      console.log(`[FLOW] Job #${job.id}: treasure tapped, waiting for timed Open button tap`);
      const openTapped = await tapOpenButtonAtDeadline(job);
      if (!openTapped) {
        console.log(`[FLOW] Job #${job.id}: treasure tapped but Open button was not tapped; next task`);
        return;
      }

      console.log(
        `[FLOW] Job #${job.id}: Open button tap scheduled;`
        + ` post_settle=${config.openPostTapSettleMs}ms capture=${config.openAfterTapCapture}`,
      );
      if (config.openAfterTapCapture) {
        try {
          if (config.openResultWaitMs > 0) await sleep(config.openResultWaitMs);
          const afterOpen = await capture(job.id);
          const uploadedAfterOpen = await upload(job.id, afterOpen.image, "after_open_button_tap");
          await report(job.id, "after_open_tap_screenshot_uploaded");
          console.log(`Job #${job.id}: screenshot after Open tap saved at ${uploadedAfterOpen.url}`);
        } catch (error) {
          console.warn(`Job #${job.id}: after Open tap screenshot skipped: ${error.message}`);
        }
      }
      await report(job.id, "done");
      console.log(`[FLOW] Job #${job.id}: done after treasure + Open tap total=${Date.now() - jobStartedAtMs}ms`);
      return;
    }
    await report(job.id, "done");
    console.log(`[FLOW] Job #${job.id}: done total=${Date.now() - jobStartedAtMs}ms`);
  } catch (error) {
    if (allowSessionRetry && isMissingSessionError(error)) {
      console.log(`Job #${job.id}: WDA session expired, creating a new session`);
      sessionId = "";
      cachedViewportRect = null;
      await createSession();
      return processJob(job, false);
    }
    console.error(`Job #${job.id} failed: ${error.message}`);
    await report(job.id, "failed", error.message).catch(() => {});
  }
}

async function shutdown() {
  if (stopping) return;
  stopping = true;
  if (sessionId) {
    await appium("DELETE", `/session/${sessionId}`).catch(() => {});
  }
}

// Greedy scheduler: pick the best job from all pending, prioritising those
// whose target is 10-15 s away (ideal window). If none is ideal, pick the
// earliest upcoming job (smallest remaining > minMs) so we waste as little
// time as possible, then sleep until we are inside the ideal window before
// running. This maximises treasure chests per 30-second task cycle.
function jobPassesClientFilter(job) {
  const rewards = extractRewardSignals(job);
  const mode = config.filterRewardMode;
  const selectedRewards = rewards.filter((reward) => (
    mode === "all"
    || mode === reward.type
    || (mode === "both" && rewards.some((item) => item.type === "box") && rewards.some((item) => item.type === "bag"))
  ));
  if (mode !== "all" && selectedRewards.length === 0) {
    return { pass: false, reason: `reward mode ${mode} not matched` };
  }

  const needsReward = config.filterMaxViews > 0
    || config.filterMinBox1 > 0
    || config.filterMinBox2 > 0
    || config.filterMinRate > 0
    || mode !== "all";
  if (needsReward && selectedRewards.length === 0) {
    return { pass: false, reason: "missing reward signal" };
  }

  const noteNeedles = splitNeedles(config.filterNoteContains);
  if (noteNeedles.length) {
    const noteText = String(extractNote(job) || "").toLowerCase();
    const fullText = jobText(job).toLowerCase();
    const matched = noteNeedles.some((needle) => noteText.includes(needle) || fullText.includes(needle));
    if (!matched) return { pass: false, reason: `note missing ${noteNeedles.join("|")}` };
  }
  if (!needsReward) return { pass: true, reason: "" };

  for (const reward of selectedRewards.length ? selectedRewards : rewards) {
    if (config.filterMaxViews > 0 && Number.isFinite(reward.views) && reward.views > config.filterMaxViews) {
      continue;
    }
    if (config.filterMinBox1 > 0 && Number.isFinite(reward.left) && reward.left < config.filterMinBox1) {
      continue;
    }
    if (config.filterMinBox2 > 0 && Number.isFinite(reward.right) && reward.right < config.filterMinBox2) {
      continue;
    }
    if (config.filterMinRate > 0 && Number.isFinite(reward.rate) && reward.rate < config.filterMinRate) {
      continue;
    }
    return { pass: true, reason: "" };
  }

  const reward = selectedRewards[0] || rewards[0] || {};
  if (config.filterMaxViews > 0 && Number.isFinite(reward.views) && reward.views > config.filterMaxViews) {
    return { pass: false, reason: `views ${reward.views} > max ${config.filterMaxViews}` };
  }
  if (config.filterMinBox1 > 0 && Number.isFinite(reward.left) && reward.left < config.filterMinBox1) {
    return { pass: false, reason: `${reward.type || "reward"}1 ${reward.left} < min ${config.filterMinBox1}` };
  }
  if (config.filterMinBox2 > 0 && Number.isFinite(reward.right) && reward.right < config.filterMinBox2) {
    return { pass: false, reason: `${reward.type || "reward"}2 ${reward.right} < min ${config.filterMinBox2}` };
  }
  if (config.filterMinRate > 0 && Number.isFinite(reward.rate) && reward.rate < config.filterMinRate) {
    return { pass: false, reason: `rate ${reward.rate} < min ${config.filterMinRate}` };
  }
  return { pass: false, reason: "reward filter not matched" };
}

function extractRewardSignals(job) {
  const payload = job?.payload || {};
  const signal = payload.box_signal || {};
  const text = jobText(job);
  const parsed = parseRewardSignals(text);
  if (parsed.length) return parsed;

  const rawBox = String(signal.box || payload.box || "");
  const [left, right] = rawBox.split("/").map((value) => Number(value));
  if (!Number.isFinite(left) || !Number.isFinite(right)) return [];
  return [{
    type: normalizeRewardType(signal.reward_type || signal.type || payload.reward_type || payload.type || "box"),
    left,
    right,
    rate: Number(signal.rate ?? payload.rate ?? NaN),
    views: Number(signal.views ?? payload.views ?? NaN),
  }];
}

function parseRewardSignals(text) {
  const rewards = [];
  const rewardRe = /(?:🎁|🟡|🟪)?\s*(BOX|BAG)\s*:\s*(\d+)\s*\/\s*(\d+)/gi;
  for (const match of String(text || "").matchAll(rewardRe)) {
    rewards.push({
      type: normalizeRewardType(match[1]),
      left: Number(match[2]),
      right: Number(match[3]),
      rate: parseNumberMatch(text, /📈\s*Rate\s*:\s*(\d+(?:\.\d+)?)/i),
      views: parseNumberMatch(text, /👀\s*(\d+)/),
    });
  }
  return rewards;
}

function normalizeRewardType(value) {
  return String(value || "").trim().toLowerCase() === "bag" ? "bag" : "box";
}

function parseNumberMatch(text, regex) {
  const match = String(text || "").match(regex);
  return match ? Number(match[1]) : NaN;
}

function extractNote(job) {
  const signal = job?.payload?.box_signal || {};
  if (signal.note) return signal.note;
  const text = jobText(job);
  const match = text.match(/(?:📝|💬)\s*([^\r\n]+)/);
  return match ? match[1].trim() : "";
}

function jobText(job) {
  if (typeof job?.message === "string") return job.message;
  return String(job?.message?.text || "");
}

function splitNeedles(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim().replace(/^['"]+|['"]+$/g, "").toLowerCase())
    .filter(Boolean);
}

function queueUrlFromItem(item) {
  const payload = item?.payload || {};
  const candidates = [
    item?.url,
    payload.url,
    payload.link,
    payload.deeplink,
    payload.deep_link,
    payload.live_url,
    payload.room_url,
    item?.message?.text,
  ];
  for (const value of candidates) {
    const match = String(value || "").match(/(?:https?:\/\/|tiktok:\/\/)[^\s<>'"]+/i);
    if (match) return match[0];
  }
  return "";
}

function queueItemToPhoneJob(item, generatedAt = "") {
  const payload = item?.payload || {};
  const text = String(item?.message?.text || "");
  const url = queueUrlFromItem(item);
  if (!item?.id || !url) return null;
  return {
    id: Number(item.id),
    url,
    time: String(payload.TIME || payload.time || text || ""),
    message: text,
    click_after_ms: Number(payload.click_after_ms || item.click_after_ms || 0),
    payload,
    received_at_ms: Date.now(),
    server_generated_at: generatedAt,
  };
}

async function latestPendingQueueJob() {
  const url = new URL(`${config.queueUrl}/api/queue`);
  url.searchParams.set("limit", "25");
  url.searchParams.set("statuses", "pending");
  const snapshot = await requestJson(url);
  for (const item of snapshot.items || []) {
    const job = queueItemToPhoneJob(item, snapshot.generated_at || "");
    if (!job) continue;
    const filterResult = jobPassesClientFilter(job);
    if (filterResult.pass) return job;
  }
  return null;
}

async function pickInitialJob() {
  const job = await pickBestJob(0);
  if (job) console.log(`Initial scheduler claimed pending job #${job.id}`);
  return job;
}

async function pickBestJob(afterId) {
  const url = new URL(`${config.queueUrl}/api/phone/next-job`);
  // Always let the server choose the best currently-pending job. If a job was
  // claimed and later failed, it keeps the same id; using a monotonically
  // increasing after_id would make this worker ignore its retry forever.
  url.searchParams.set("after_id", "0");
  url.searchParams.set("wait", String(config.pollWaitSeconds));
  url.searchParams.set("device_id", config.deviceId);
  const response = await requestJson(url);
  if (!response.job) return null;
  const job = {
    ...response.job,
    received_at_ms: Date.now(),
    server_generated_at: response.generated_at || "",
  };
  const filterResult = jobPassesClientFilter(job);
  if (!filterResult.pass) {
    console.log(`Job #${job.id}: skipped by client filter — ${filterResult.reason}`);
    return { _filtered: true, id: job.id, reason: filterResult.reason };
  }
  return job;
}

function shouldPreemptFirstJob(currentJob, candidateJob) {
  if (!candidateJob || !currentJob) return false;
  if (Number(candidateJob.id || 0) <= Number(currentJob.id || 0)) return false;
  const nowMs = Date.now();
  const currentWindow = jobTimeWindow(currentJob, nowMs);
  const candidateWindow = jobTimeWindow(candidateJob, nowMs);
  if (candidateWindow.state === "missing" || candidateWindow.state === "late") return false;
  if (currentWindow.state === "missing" || currentWindow.state === "late") return true;
  if (candidateWindow.state === "ready") return true;
  return Number(candidateWindow.remainingMs || Infinity) + 1000 < Number(currentWindow.remainingMs || Infinity);
}

async function waitForWindow(job, allowFirstPreempt) {
  let currentJob = job;
  while (!stopping) {
    const timeWindow = jobTimeWindow(currentJob);
    if (timeWindow.state !== "early") {
      return { job: currentJob, timeWindow };
    }
    const waitMs = timeWindow.remainingMs - config.liveTimeMaxMs;
    if (waitMs <= 0) {
      return { job: currentJob, timeWindow: jobTimeWindow(currentJob) };
    }

    console.log(
      `Job #${currentJob.id}: TIME ${(timeWindow.remainingMs / 1000).toFixed(1)}s away; `
      + `sleeping ${(waitMs / 1000).toFixed(1)}s to reach window`
      + (allowFirstPreempt ? " (first job can be replaced)" : ""),
    );
    const wakeAtMs = Date.now() + waitMs;
    let nextHeartbeatMs = 0;
    while (!stopping && Date.now() < wakeAtMs) {
      const nowMs = Date.now();
      if (nowMs >= nextHeartbeatMs) {
        await report(currentJob.id, "waiting_time_window", JSON.stringify({
          reason: "early_time_window",
          wake_at_ms: wakeAtMs,
          remaining_ms: wakeAtMs - nowMs,
        })).catch((error) => console.warn(`Job #${currentJob.id}: lease heartbeat failed: ${error.message}`));
        nextHeartbeatMs = nowMs + 15_000;
      }
      await sleep(Math.min(1000, Math.max(0, wakeAtMs - Date.now())));
    }
  }
  return { job: currentJob, timeWindow: jobTimeWindow(currentJob) };
}

async function main() {
  if (config.liveTimeMinMs > config.liveTimeMaxMs) {
    throw new Error("LIVE_TIME_MIN_SECONDS must be <= LIVE_TIME_MAX_SECONDS");
  }
  await measureWdaRtt();
  await createSession();
  if (process.env.MANUAL_QUEUE_JOB_JSON) {
    const job = JSON.parse(process.env.MANUAL_QUEUE_JOB_JSON);
    console.log(`[MANUAL] Running queue job #${job.id}`);
    await processJob(job);
    return;
  }
  console.log(`[DEBUG PATHS] controller=${__dirname}`);
  console.log(`[DEBUG PATHS] captures=${config.captureDir}`);
  console.log(`[DEBUG PATHS] treasure_debug=${config.treasureDebugDir}`);
  console.log(
    `Clock source: ${config.clockSource} (${localTimezoneLabel()}) | now=${localTimeLabel(Date.now())}`,
  );
  console.log(
    `Live Time window: ${config.liveTimeMinMs / 1000}-${config.liveTimeMaxMs / 1000}s`
    + ` | click_after fallback=${config.allowClickAfterFallback ? "on" : "off"}`
    + ` | treasure debug=${config.treasureDebugMode}`
    + " | greedy scheduler active",
  );
  let afterId = 0;
  let firstJobCanPreempt = true;
  while (!stopping) {
    try {
      let job = firstJobCanPreempt ? await pickInitialJob() : await pickBestJob(afterId);
      if (!job) continue;

      afterId = Math.max(afterId, Number(job.id) || 0);

      // Job was filtered out client-side (views/box/rate)
      if (job._filtered) {
        await report(job.id, "client_filter_skipped", job.reason || "client filter").catch(() => {});
        firstJobCanPreempt = false;
        continue;
      }

      let timeWindow = jobTimeWindow(job);

      if (timeWindow.state === "missing") {
        // No TIME info — run immediately
        console.log(`Job #${job.id}: TIME missing, running immediately`);
        firstJobCanPreempt = false;
        await processJob(job);
      } else if (timeWindow.state === "late") {
        const detail = `TIME is ${(timeWindow.remainingMs / 1000).toFixed(1)}s away (past late threshold)`;
        console.log(`Job #${job.id}: ${detail}; skipped`);
        await report(job.id, "time_window_skipped", detail).catch(() => {});
        firstJobCanPreempt = false;
      } else if (timeWindow.state === "early") {
        const waited = await waitForWindow(job, firstJobCanPreempt);
        if (stopping) break;
        job = waited.job;
        timeWindow = waited.timeWindow;
        afterId = Math.max(afterId, Number(job.id) || 0);
        if (timeWindow.state === "late") {
          const detail = `TIME is ${(timeWindow.remainingMs / 1000).toFixed(1)}s away after waiting`;
          console.log(`Job #${job.id}: ${detail}; skipped`);
          await report(job.id, "time_window_skipped", detail).catch(() => {});
          continue;
        }
        console.log(`Job #${job.id}: entering window, running`);
        firstJobCanPreempt = false;
        await processJob(job);
      } else {
        // state === "ready" — ideal configured window
        console.log(`Job #${job.id}: in ideal window (${(timeWindow.remainingMs / 1000).toFixed(1)}s), running`);
        firstJobCanPreempt = false;
        await processJob(job);
      }

      if (config.runOnce) {
        console.log("RUN_ONCE=true, stopping after one job");
        break;
      }
    } catch (error) {
      if (!stopping) {
        console.error(`Worker error: ${error.message}`);
        await sleep(3000);
      }
    }
  }
}

module.exports = { jobTimeWindow, localTimeLabel, openTapRequestTime, openTargetTime };

if (require.main === module) {
  process.on("SIGINT", () => shutdown().finally(() => process.exit(0)));
  process.on("SIGTERM", () => shutdown().finally(() => process.exit(0)));

  main()
    .catch((error) => {
      console.error(error.stack || error.message);
      process.exitCode = 1;
    })
    .finally(shutdown);
}
