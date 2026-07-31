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
const { openChromeUrl, focusChromeTab, closeChromeTab, CHROME_APP } = require("./chrome");
const { loadSettings, saveSettings, adjustDelayOffset } = require("./settings");
const { clickScreenPoint, warmUpWinClickHelper, shutdownWinClickHelper } = require("./desktop-click");
const { pickPointOnScreen } = require("./pick-point");
const { ensureAccessibility } = require("./accessibility");
const { computeCountdownSchedule } = require("./junb-url");

function loadDotEnv() {
  const envPath = path.join(__dirname, "..", ".env");
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

const PORT = Number(process.env.DESKTOP_TOOL_PORT) || DEFAULT_PORT;
const QUEUE_URL = process.env.DESKTOP_TOOL_QUEUE_URL || "";
const PULL_TOKEN = process.env.DESKTOP_TOOL_PULL_TOKEN || "";
const POLL_MS = Number(process.env.DESKTOP_TOOL_POLL_MS) || 2000;
const TAB_CLOSE_AFTER_END_MS = Number(process.env.DESKTOP_TAB_CLOSE_AFTER_END_MS) || 30_000;

const openEntries = new Map();
const clickTimers = new Map();
let tray = null;
let settingsWindow = null;
let stopPoller = null;

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    showSettingsWindow();
  });
}

function notifySchedule(payload) {
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.webContents.send("countdown-schedule", payload);
  }
}

function clearEntryTimers(entry) {
  if (entry?.closeTimer) clearTimeout(entry.closeTimer);
  if (entry?.jobId != null && clickTimers.has(String(entry.jobId))) {
    clearTimeout(clickTimers.get(String(entry.jobId)));
    clickTimers.delete(String(entry.jobId));
  }
}

async function scheduleDesktopClick({ url, clickAfterMs = 0, jobId = null, timeLabel = "" } = {}) {
  const settings = loadSettings();
  if (!settings.autoClickEnabled) return null;

  const schedule = await computeCountdownSchedule(url, {
    clickAfterMs,
    delayOffsetMs: settings.delayOffsetMs,
    defaultWaitMs: settings.defaultWaitMs,
    tabCloseAfterEndMs: TAB_CLOSE_AFTER_END_MS,
  });

  if (schedule.clickWaitMs <= 0 && !schedule.endTimeMs) return schedule;

  const key = jobId != null ? String(jobId) : `open-${Date.now()}`;
  if (clickTimers.has(key)) clearTimeout(clickTimers.get(key));

  const sec = (schedule.clickWaitMs / 1000).toFixed(2);
  const label = schedule.endTimeMs
    ? `${schedule.source === "thanhtai_end_time" ? "thanhtai" : "junb"} 0.0s + offset (${sec}s)`
    : (timeLabel || `${sec}s`);

  notifySchedule({
    type: "scheduled",
    jobId: key,
    waitMs: schedule.clickWaitMs,
    closeWaitMs: schedule.closeWaitMs,
    timeLabel: label,
    endTimeMs: schedule.endTimeMs,
  });

  const timer = setTimeout(async () => {
    clickTimers.delete(key);
    try {
      ensureAccessibility(true);
      const latest = loadSettings();
      const result = await clickScreenPoint(latest.clickX, latest.clickY);
      notifySchedule({
        type: "clicked",
        jobId: key,
        x: result.x,
        y: result.y,
        method: result.method,
      });
      console.log(`Desktop click job #${key} at ${result.x},${result.y} (${result.method})`);
    } catch (err) {
      console.error("Desktop click failed:", err.message || err);
      notifySchedule({ type: "error", jobId: key, error: String(err.message || err) });
    }
  }, schedule.clickWaitMs);

  clickTimers.set(key, timer);
  console.log(`Click at countdown 0.0s in ${schedule.clickWaitMs}ms, close tab in ${schedule.closeWaitMs}ms (job ${key})`);
  return schedule;
}

async function openCountdownTab({
  url,
  jobId = null,
  clickAfterMs = 0,
  timeLabel = "",
} = {}) {
  const cleanUrl = decodeHtmlUrl(url);
  const urlKey = normalizeOpenUrl(cleanUrl) || cleanUrl;
  const settings = loadSettings();
  const schedule = await computeCountdownSchedule(cleanUrl, {
    clickAfterMs,
    delayOffsetMs: settings.delayOffsetMs,
    defaultWaitMs: settings.defaultWaitMs,
    tabCloseAfterEndMs: TAB_CLOSE_AFTER_END_MS,
  });

  const existing = openEntries.get(urlKey);
  if (existing) {
    clearEntryTimers(existing);
    focusChromeTab(existing.url).catch((err) => {
      console.warn("Chrome focus failed:", err.message || err);
    });
    existing.closeTimer = setTimeout(() => {
      closeChromeTab(existing.url).finally(() => openEntries.delete(urlKey));
    }, schedule.closeWaitMs);
    existing.openedAt = Date.now();
    existing.jobId = jobId;
    scheduleDesktopClick({ url: cleanUrl, clickAfterMs, jobId, timeLabel }).catch((err) => {
      console.warn("Schedule click failed:", err.message || err);
    });
    return { tabId: urlKey, deduplicated: true, schedule };
  }

  openChromeUrl(cleanUrl).catch((err) => {
    console.error("Chrome open failed:", err.message || err);
  });

  const closeTimer = setTimeout(() => {
    closeChromeTab(cleanUrl).finally(() => openEntries.delete(urlKey));
  }, schedule.closeWaitMs);

  openEntries.set(urlKey, {
    url: cleanUrl,
    urlKey,
    jobId,
    closeTimer,
    openedAt: Date.now(),
  });

  scheduleDesktopClick({ url: cleanUrl, clickAfterMs, jobId, timeLabel }).catch((err) => {
    console.warn("Schedule click failed:", err.message || err);
  });
  console.log(`Opened countdown — close ${(schedule.closeWaitMs / 1000).toFixed(1)}s after open (≈30s sau 0.0s)`);
  return { tabId: urlKey, deduplicated: false, schedule };
}

function registerIpcHandlers() {
  ipcMain.handle("settings:get", () => loadSettings());
  ipcMain.handle("settings:save", (_event, partial) => saveSettings(partial || {}));
  ipcMain.handle("settings:adjust-delay", (_event, deltaMs) => adjustDelayOffset(Number(deltaMs) || 0));
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
}

function showSettingsWindow() {
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.show();
    settingsWindow.focus();
    return;
  }

  settingsWindow = new BrowserWindow({
    width: 460,
    height: 680,
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
}

async function startServer() {
  const { port } = await createDesktopToolServer({
    port: PORT,
    onOpen: openCountdownTab,
    getSettings: loadSettings,
  });
  console.log(`Desktop-tool API http://127.0.0.1:${port}`);
  console.log(`Chrome: ${CHROME_APP} — click lúc 0.0s, đóng tab +30s sau 0.0s`);
  return port;
}

function createTray(port) {
  const icon = nativeImage.createEmpty();
  tray = new Tray(icon);
  tray.setToolTip("Click Live Desktop Tool");

  const rebuild = () => {
    const tabs = openEntries.size;
    tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: `API :${port}`, enabled: false },
        { label: `Chrome tab: ${tabs}`, enabled: false },
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

app.whenReady().then(async () => {
  if (!gotSingleInstanceLock) return;

  registerIpcHandlers();

  try {
    const port = await startServer();
    createTray(port);
    showSettingsWindow();
    const queueUrl = process.env.DESKTOP_TOOL_QUEUE_URL || QUEUE_URL;
    const pullToken = process.env.DESKTOP_TOOL_PULL_TOKEN || PULL_TOKEN;
    stopPoller = startDesktopPoller({
      queueUrl,
      pullToken,
      intervalMs: POLL_MS,
      onOpen: openCountdownTab,
    });
    if (queueUrl && pullToken) {
      console.log(`Polling queue ${queueUrl} every ${POLL_MS}ms`);
    }
    warmUpWinClickHelper();
  } catch (err) {
    if (err && err.code === "EADDRINUSE") {
      console.error(`Port ${PORT} đang được dùng — desktop-tool có thể đã chạy.`);
    } else {
      console.error(err);
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
  for (const entry of openEntries.values()) {
    clearEntryTimers(entry);
  }
  for (const timer of clickTimers.values()) {
    clearTimeout(timer);
  }
  openEntries.clear();
  clickTimers.clear();
});
