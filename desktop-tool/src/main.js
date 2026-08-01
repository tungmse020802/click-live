const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain } = require("electron");
const path = require("path");
const fs = require("fs");
const {
  createDesktopToolServer,
  normalizeOpenUrl,
  decodeHtmlUrl,
  DEFAULT_PORT,
} = require("./server");
const { startDesktopPoller } = require("./poll");
const { desktopLogin } = require("./auth");
const { loadSettings, saveSettings, adjustDelayOffset } = require("./settings");
const { clickScreenPoint, warmUpWinClickHelper, shutdownWinClickHelper } = require("./desktop-click");
const { pickPointOnScreen } = require("./pick-point");
const { ensureAccessibility } = require("./accessibility");
const {
  computeCountdownSchedule,
  computeClickFireDelayMs,
  waitUntilClickTarget,
  resolveClickExecutionLeadMs,
} = require("./junb-url");
const {
  ensureCountdownOverlay,
  setCountdownOverlay,
  clearCountdownOverlay,
  destroyCountdownOverlay,
} = require("./countdown-overlay");
const { envFilePath, isPackaged } = require("./paths");

function loadDotEnv() {
  const envPath = envFilePath();
  if (!fs.existsSync(envPath)) return;
  for (const line of fs.readFileSync(envPath, "utf-8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const idx = trimmed.indexOf("=");
    if (idx <= 0) continue;
    const key = trimmed.slice(0, idx).trim();
    const value = trimmed.slice(idx + 1).trim();
    if (!(key in process.env)) process.env[key] = value;
  }
}

loadDotEnv();

if (process.platform === "win32") {
  app.setAppUserModelId("com.clicklive.desktop-tool");
}

const PORT = Number(process.env.DESKTOP_TOOL_PORT) || DEFAULT_PORT;
const QUEUE_URL = process.env.DESKTOP_TOOL_QUEUE_URL || "";
const POLL_MS = Number(process.env.DESKTOP_TOOL_POLL_MS) || 2000;

const jobEntries = new Map();
/** Chỉ job mở cuối cùng được auto-click. */
let activeJobKey = null;
let activeClickTimer = null;
/** Tăng mỗi lần mở job — timing/click chỉ áp dụng cho seq mới nhất. */
let openSequence = 0;
/** Overlay đếm giờ — cập nhật khi offset đổi. */
let activeOverlayTiming = null;
let tray = null;
let settingsWindow = null;
let stopPoller = null;

let gotSingleInstanceLock = true;
if (isPackaged()) {
  gotSingleInstanceLock = app.requestSingleInstanceLock();
  if (!gotSingleInstanceLock) {
    console.error(
      "Desktop-tool da chay.\n"
      + "  Dong ban portable cu hoac chay scripts\\stop-windows.bat"
    );
    app.quit();
  } else {
    app.on("second-instance", () => {
      showSettingsWindow();
      if (settingsWindow && !settingsWindow.isDestroyed()) {
        if (settingsWindow.isMinimized()) settingsWindow.restore();
        settingsWindow.focus();
      }
    });
  }
}

function syncCountdownOverlay() {
  if (!activeOverlayTiming) {
    clearCountdownOverlay();
    return;
  }
  const settings = loadSettings();
  const offsetMs = Number(settings.delayOffsetMs) || 0;
  const { schedule, fireDelayMs, scheduledAt } = activeOverlayTiming;
  let targetAtMs;
  if (schedule.endTimeMs) {
    targetAtMs = schedule.endTimeMs + offsetMs;
  } else {
    const lead = schedule.executionLeadMs ?? resolveClickExecutionLeadMs();
    targetAtMs = scheduledAt + Math.max(0, Number(fireDelayMs) || 0) + lead;
  }
  setCountdownOverlay({ active: true, targetAtMs });
}

function clearOverlayTiming() {
  activeOverlayTiming = null;
  clearCountdownOverlay();
}

function cancelActiveClickTimer() {
  if (activeClickTimer) {
    clearTimeout(activeClickTimer);
    activeClickTimer = null;
  }
}

function beginOpenSequence() {
  openSequence += 1;
  cancelActiveClickTimer();
  clearOverlayTiming();
  return openSequence;
}

function isLatestOpenSequence(seq) {
  return seq === openSequence;
}

function isActiveLatestJob(urlKey, seq) {
  if (!isLatestOpenSequence(seq)) return false;
  const latest = getLatestEntry();
  return latest?.urlKey === urlKey && activeJobKey === urlKey;
}

function getLatestEntry() {
  let latest = null;
  for (const entry of jobEntries.values()) {
    if (!latest || entry.openedAt > latest.openedAt) latest = entry;
  }
  return latest;
}

function notifySchedule(payload) {
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.webContents.send("countdown-schedule", payload);
  }
}

async function scheduleDesktopClick({
  urlKey,
  url,
  schedule: presetSchedule = null,
  clickAfterMs = 0,
  jobId = null,
  timeLabel = "",
  queuedAtMs = null,
  endTimeMs: presetEndTimeMs = null,
  openSequence: seq = 0,
} = {}) {
  const settings = loadSettings();

  if (!isLatestOpenSequence(seq)) {
    console.log(`Skip schedule seq=${seq} — job cuối là seq=${openSequence}`);
    return presetSchedule;
  }

  cancelActiveClickTimer();
  activeJobKey = urlKey;

  const schedule = presetSchedule || await computeCountdownSchedule(url, {
    clickAfterMs,
    delayOffsetMs: settings.delayOffsetMs,
    defaultWaitMs: settings.defaultWaitMs,
    tabCloseAfterEndMs: 0,
    timeLabel,
    queuedAtMs,
    endTimeMs: presetEndTimeMs,
  });

  if (!isLatestOpenSequence(seq)) {
    console.log(`Skip timing seq=${seq} sau resolve — tab cuối seq=${openSequence}`);
    return schedule;
  }

  if (schedule.clickWaitMs <= 0 && !schedule.endTimeMs) return schedule;

  const key = jobId != null ? String(jobId) : urlKey;
  const offsetMs = Number(settings.delayOffsetMs) || 0;
  const fireDelayMs = schedule.endTimeMs
    ? computeClickFireDelayMs(schedule, offsetMs)
    : Math.max(0, Number(schedule.clickWaitMs) || 0);

  activeOverlayTiming = { schedule, fireDelayMs, scheduledAt: Date.now() };
  syncCountdownOverlay();

  if (!settings.autoClickEnabled) return schedule;

  const displaySec = schedule.endTimeMs
    ? ((schedule.endTimeMs - Date.now() + offsetMs) / 1000).toFixed(2)
    : null;

  const sec = (fireDelayMs / 1000).toFixed(2);
  const label = schedule.endTimeMs
    ? `${schedule.source === "thanhtai_end_time" ? "thanhtai" : schedule.source === "junb_end_time" ? "junb" : schedule.source === "server_end_time" ? "server" : schedule.source === "queued_click_after" ? "queue+after" : schedule.source} click @ ${displaySec}s (offset ${offsetMs >= 0 ? "+" : ""}${(offsetMs / 1000).toFixed(2)}s)`
    : (timeLabel || `${sec}s`);

  notifySchedule({
    type: "scheduled",
    jobId: key,
    waitMs: fireDelayMs,
    closeWaitMs: schedule.closeWaitMs,
    timeLabel: label,
    endTimeMs: schedule.endTimeMs,
    offsetMs,
    displayRemainingMs: displaySec != null ? Math.round(Number(displaySec) * 1000) : null,
  });

  activeClickTimer = setTimeout(async () => {
    activeClickTimer = null;
    if (!isActiveLatestJob(urlKey, seq)) {
      console.log(`Skip click job #${key} — chỉ job cuối (seq=${openSequence})`);
      return;
    }
    try {
      const latest = loadSettings();
      if (schedule.endTimeMs) {
        await waitUntilClickTarget(schedule.endTimeMs, latest.delayOffsetMs, {
          shouldAbort: () => !isActiveLatestJob(urlKey, seq),
        });
      }
      if (!isActiveLatestJob(urlKey, seq)) {
        console.log(`Skip click job #${key} sau chờ timing — job mới hơn`);
        return;
      }
      if (process.platform === "darwin") ensureAccessibility(true);
      const result = await clickScreenPoint(latest.clickX, latest.clickY);
      notifySchedule({
        type: "clicked",
        jobId: key,
        x: result.x,
        y: result.y,
        method: result.method,
      });
      console.log(`Desktop click job #${key} at ${result.x},${result.y} (${result.method}) offset=${latest.delayOffsetMs}ms`);
      clearOverlayTiming();
    } catch (err) {
      console.error("Desktop click failed:", err.message || err);
      notifySchedule({ type: "error", jobId: key, error: String(err.message || err) });
      clearOverlayTiming();
    }
  }, fireDelayMs);

  console.log(`Click job active (${urlKey}) fire in ${fireDelayMs}ms (display≈${displaySec ?? "?"}s + offset ${offsetMs}ms, lead ${schedule.executionLeadMs ?? "?"}ms)`);
  return schedule;
}

async function openCountdownTab({
  url,
  jobId = null,
  clickAfterMs = 0,
  timeLabel = "",
  queuedAtMs = null,
  endTimeMs: presetEndTimeMs = null,
} = {}) {
  const seq = beginOpenSequence();
  const cleanUrl = decodeHtmlUrl(url);
  const urlKey = normalizeOpenUrl(cleanUrl) || cleanUrl;
  const settings = loadSettings();

  const existing = jobEntries.get(urlKey);
  const entry = existing || {
    url: cleanUrl,
    urlKey,
    jobId,
    openedAt: Date.now(),
    openSequence: seq,
  };
  entry.openedAt = Date.now();
  entry.jobId = jobId;
  entry.openSequence = seq;
  jobEntries.set(urlKey, entry);
  activeJobKey = urlKey;

  const schedule = await computeCountdownSchedule(cleanUrl, {
    clickAfterMs,
    delayOffsetMs: settings.delayOffsetMs,
    defaultWaitMs: settings.defaultWaitMs,
    tabCloseAfterEndMs: 0,
    timeLabel,
    queuedAtMs,
    endTimeMs: presetEndTimeMs,
  });

  if (!isLatestOpenSequence(seq)) {
    console.log(`Bỏ timing job seq=${seq} — job cuối seq=${openSequence}`);
    return { tabId: urlKey, deduplicated: Boolean(existing), skipped: true, schedule };
  }

  scheduleDesktopClick({
    urlKey,
    url: cleanUrl,
    schedule,
    clickAfterMs,
    jobId,
    timeLabel,
    queuedAtMs,
    endTimeMs: presetEndTimeMs,
    openSequence: seq,
  }).catch((err) => {
    console.warn("Schedule click failed:", err.message || err);
  });

  console.log(`Countdown overlay seq=${seq}${existing ? " (dedup)" : ""}`);
  return { tabId: urlKey, deduplicated: Boolean(existing), schedule };
}

function getPollerCredentials() {
  const settings = loadSettings();
  const queueUrl = (
    settings.queueUrl
    || process.env.DESKTOP_TOOL_QUEUE_URL
    || QUEUE_URL
    || ""
  ).trim();
  const queueUsername = String(settings.queueUsername || "").trim();
  const pullToken = String(settings.pullToken || "").trim();
  return { queueUrl, pullToken, queueUsername };
}

function restartPoller() {
  if (stopPoller) stopPoller();
  const { queueUrl, pullToken, queueUsername } = getPollerCredentials();
  stopPoller = startDesktopPoller({
    queueUrl,
    pullToken,
    queueUsername,
    intervalMs: POLL_MS,
    onOpen: openCountdownTab,
  });
  if (queueUrl && pullToken && queueUsername) {
    console.log(`Polling queue ${queueUrl} as ${queueUsername} every ${POLL_MS}ms`);
  } else {
    console.warn("Desktop poller disabled — mở app → Tài khoản queue → chọn user và đăng nhập");
  }
}

function registerIpcHandlers() {
  ipcMain.handle("settings:get", () => loadSettings());
  ipcMain.handle("settings:save", (_event, partial) => saveSettings(partial || {}));
  ipcMain.handle("settings:adjust-delay", async (_event, deltaMs) => {
    const result = adjustDelayOffset(Number(deltaMs) || 0);
    syncCountdownOverlay();
    return result;
  });
  ipcMain.handle("settings:pick-point", async () => {
    if (settingsWindow && !settingsWindow.isDestroyed()) settingsWindow.hide();
    try {
      return await pickPointOnScreen();
    } finally {
      if (settingsWindow && !settingsWindow.isDestroyed()) settingsWindow.show();
    }
  });
  ipcMain.handle("settings:test-click", async () => {
    ensureAccessibility(true);
    const settings = loadSettings();
    return clickScreenPoint(settings.clickX, settings.clickY);
  });
  ipcMain.handle("settings:ensure-accessibility", async () => ensureAccessibility(true));
  ipcMain.handle("auth:session", () => {
    const creds = getPollerCredentials();
    return {
      loggedIn: Boolean(creds.pullToken && creds.queueUsername),
      queueUsername: creds.queueUsername,
      queueUrl: creds.queueUrl,
    };
  });
  ipcMain.handle("auth:fetch-users", async (_event, queueUrl) => {
    const base = String(
      queueUrl
      || loadSettings().queueUrl
      || process.env.DESKTOP_TOOL_QUEUE_URL
      || QUEUE_URL
      || ""
    ).trim();
    const { fetchQueueUsers } = require("./auth");
    return fetchQueueUsers(base);
  });
  ipcMain.handle("auth:login", async (_event, payload = {}) => {
    const queueUrl = String(
      payload.queueUrl
      || loadSettings().queueUrl
      || process.env.DESKTOP_TOOL_QUEUE_URL
      || QUEUE_URL
      || ""
    ).trim();
    const data = await desktopLogin(queueUrl, payload.username, payload.password);
    saveSettings({
      queueUrl,
      queueUsername: String(data.username || payload.username || "").trim(),
      pullToken: String(data.pull_token || "").trim(),
    });
    restartPoller();
    return {
      ok: true,
      username: String(data.username || payload.username || "").trim(),
      queueUrl,
    };
  });
  ipcMain.handle("auth:logout", async () => {
    saveSettings({ queueUsername: "", pullToken: "" });
    restartPoller();
    return { ok: true };
  });
}

function showSettingsWindow() {
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.show();
    settingsWindow.focus();
    return;
  }

  settingsWindow = new BrowserWindow({
    width: 460,
    height: 760,
    minWidth: 400,
    minHeight: 520,
    show: true,
    autoHideMenuBar: true,
    title: "Click Live Desktop Tool",
    webPreferences: {
      preload: path.join(__dirname, "settings-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  settingsWindow.loadFile(path.join(__dirname, "..", "ui", "settings.html"));
  settingsWindow.on("closed", () => {
    settingsWindow = null;
  });
  settingsWindow.webContents.on("did-fail-load", (_event, code, desc) => {
    console.error("Settings UI load failed:", code, desc);
  });
}

async function startServer() {
  const { port } = await createDesktopToolServer({
    port: PORT,
    onOpen: openCountdownTab,
    getSettings: loadSettings,
  });
  console.log(`Desktop-tool API http://127.0.0.1:${port}`);
  if (isPackaged()) {
    console.log(`Config: ${envFilePath()}`);
  }
  console.log("Đếm giờ: overlay góc trái trên — không mở Chrome countdown");
  return port;
}

function createTrayImage() {
  const size = 16;
  const bytes = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const i = (y * size + x) * 4;
      bytes[i] = 59;
      bytes[i + 1] = 130;
      bytes[i + 2] = 246;
      bytes[i + 3] = 255;
    }
  }
  return nativeImage.createFromBuffer(bytes, { width: size, height: size });
}

function createTray(port) {
  try {
    const icon = createTrayImage();
    tray = new Tray(icon);
  } catch (err) {
    console.warn("Tray icon failed (app vẫn chạy — dùng cửa sổ cài đặt):", err.message || err);
    return;
  }
  tray.setToolTip("Click Live Desktop Tool");

  const rebuild = () => {
    const jobs = jobEntries.size;
    const { queueUsername } = getPollerCredentials();
    const userLabel = queueUsername ? ` · ${queueUsername}` : "";
    tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: `API :${port}`, enabled: false },
        { label: `Queue${userLabel}`, enabled: false },
        { label: `Job đang chờ: ${jobs}`, enabled: false },
        { type: "separator" },
        { label: "Cài đặt đếm giờ & click", click: () => showSettingsWindow() },
        { type: "separator" },
        { label: "Thoát", click: () => app.quit() },
      ])
    );
  };

  tray.on("click", () => showSettingsWindow());
  rebuild();
  setInterval(rebuild, 3000);
}

process.on("uncaughtException", (err) => {
  console.error("uncaughtException:", err);
});
process.on("unhandledRejection", (err) => {
  console.error("unhandledRejection:", err);
});

app.whenReady().then(async () => {
  if (!gotSingleInstanceLock) return;

  registerIpcHandlers();

  try {
    const port = await startServer();
    ensureCountdownOverlay();
    showSettingsWindow();
    try {
      createTray(port);
    } catch (err) {
      console.warn("Tray failed:", err.message || err);
    }
    restartPoller();
    warmUpWinClickHelper();
  } catch (err) {
    if (err && err.code === "EADDRINUSE") {
      console.error(`Port ${PORT} đang được dùng — tắt desktop-tool cũ hoặc đổi DESKTOP_TOOL_PORT trong .env`);
    } else {
      console.error("Desktop-tool startup failed:", err);
    }
    app.quit();
    return;
  }

  app.on("activate", () => showSettingsWindow());
});

app.on("window-all-closed", (event) => {
  event.preventDefault();
});

app.on("before-quit", () => {
  shutdownWinClickHelper();
  if (stopPoller) stopPoller();
  cancelActiveClickTimer();
  destroyCountdownOverlay();
  jobEntries.clear();
  activeJobKey = null;
  activeOverlayTiming = null;
});
