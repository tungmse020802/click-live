const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, shell } = require("electron");
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
const { clickScreenPoint, warmUpWinClickHelper, shutdownWinClickHelper, isWinClickHelperReady } = require("./desktop-click");
const { pickPointOnScreen } = require("./pick-point");
const { ensureAccessibility } = require("./accessibility");
const {
  computeCountdownSchedule,
  computeClickFireDelayMs,
  waitUntilTimestamp,
  clickDisplayTargetMs,
  clickExecuteAtMs,
  resolveClickExecutionLeadMs,
  isScheduleTooStale,
  scheduleStaleMs,
} = require("./junb-url");
const { recordClickOutcome, getClickLeadStats } = require("./click-lead");
const {
  ensureCountdownOverlay,
  setCountdownOverlay,
  clearCountdownOverlay,
  destroyCountdownOverlay,
} = require("./countdown-overlay");
const { envFilePath, isPackaged } = require("./paths");
const { clickLog, clickLogWarn, clickLogError, resolveLogsDir, logFilePath, setLogUiListener, getRecentUiLogs, clearUiLogs } = require("./click-log");
const {
  nextClickGeneration,
  currentClickGeneration,
  isCurrentClickGeneration,
  abortClickWait,
  registerClickWaitAbort,
  clearClickWaitAbort,
} = require("./click-scheduler");

const MAX_JOB_ENTRIES = 32;

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
/** Task click đang chạy — hủy khi có job mới. */
let activeClickTask = null;
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
  const { schedule, scheduledAt } = activeOverlayTiming;
  let targetAtMs;
  if (schedule.endTimeMs) {
    targetAtMs = clickDisplayTargetMs(schedule.endTimeMs, offsetMs);
  } else {
    const lead = schedule.executionLeadMs ?? resolveClickExecutionLeadMs();
    targetAtMs = scheduledAt + Math.max(0, Number(schedule.clickWaitMs) || 0) + lead;
  }
  setCountdownOverlay({ active: true, targetAtMs });
  clickLog("overlay", "countdown overlay sync", {
    targetAtMs,
    endTimeMs: schedule.endTimeMs,
    remainingMs: targetAtMs ? Math.max(0, targetAtMs - Date.now()) : null,
  });
}

function clearOverlayTiming() {
  activeOverlayTiming = null;
  clearCountdownOverlay();
}

function cancelActiveClickTask() {
  activeClickTask = null;
  abortClickWait();
}

function pruneJobEntries() {
  if (jobEntries.size <= MAX_JOB_ENTRIES) return;
  const sorted = [...jobEntries.entries()].sort((a, b) => b[1].openedAt - a[1].openedAt);
  jobEntries.clear();
  for (const [key, entry] of sorted.slice(0, MAX_JOB_ENTRIES)) {
    jobEntries.set(key, entry);
  }
}

function resolveClickPoint(settings) {
  const px = Math.round(Number(settings?.clickX));
  const py = Math.round(Number(settings?.clickY));
  if (!Number.isFinite(px) || !Number.isFinite(py)) {
    throw new Error("Chưa cấu hình tọa độ click (X/Y)");
  }
  if (px < 0 || py < 0) {
    throw new Error(`Tọa độ click không hợp lệ: ${px},${py}`);
  }
  return { x: px, y: py };
}

function beginOpenSequence() {
  openSequence += 1;
  cancelActiveClickTask();
  nextClickGeneration();
  /* Giữ overlay cũ đến khi job mới syncCountdownOverlay — tránh nháy mất đồng hồ khi burst link */
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
    clickLog("skip", `skip schedule seq=${seq}`, { seq, openSequence });
    console.log(`Skip schedule seq=${seq} — job cuối là seq=${openSequence}`);
    return presetSchedule;
  }

  cancelActiveClickTask();
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
    clickLog("skip", `skip timing after resolve seq=${seq}`, { seq, openSequence });
    console.log(`Skip timing seq=${seq} sau resolve — tab cuối seq=${openSequence}`);
    return schedule;
  }

  if (schedule.clickWaitMs <= 0 && !schedule.endTimeMs) {
    clearOverlayTiming();
    return schedule;
  }

  const key = jobId != null ? String(jobId) : urlKey;
  const offsetMs = Number(settings.delayOffsetMs) || 0;

  if (schedule.endTimeMs && isScheduleTooStale(schedule.endTimeMs, offsetMs)) {
    const staleMs = scheduleStaleMs(schedule.endTimeMs, offsetMs);
    clickLogWarn("skip", `job #${key} quá hạn — không click`, {
      jobId: key,
      source: schedule.source,
      staleMs,
      offsetMs,
      endTimeMs: schedule.endTimeMs,
    });
    clearOverlayTiming();
    notifySchedule({
      type: "error",
      jobId: key,
      error: `Quá hạn ${(staleMs / 1000).toFixed(1)}s — tăng poll hoặc giảm DESKTOP_CLICK_MAX_STALE_MS`,
    });
    return schedule;
  }

  const fireDelayMs = schedule.endTimeMs
    ? computeClickFireDelayMs(schedule, offsetMs)
    : Math.max(0, Number(schedule.clickWaitMs) || 0);

  const scheduledAt = Date.now();
  activeOverlayTiming = { schedule, scheduledAt };
  syncCountdownOverlay();

  if (!settings.autoClickEnabled) return schedule;

  const displaySec = schedule.endTimeMs
    ? ((clickDisplayTargetMs(schedule.endTimeMs, offsetMs) - Date.now()) / 1000).toFixed(2)
    : null;

  const sec = (fireDelayMs / 1000).toFixed(2);
  const label = schedule.endTimeMs
    ? `${schedule.source === "thanhtai_end_time" ? "thanhtai" : schedule.source === "junb_end_time" ? "junb" : schedule.source === "server_end_time" ? "server" : schedule.source === "queued_click_after" ? "queue+after" : schedule.source === "message_clock" ? "TIME" : schedule.source} @ ${displaySec}s (offset ${offsetMs >= 0 ? "+" : ""}${(offsetMs / 1000).toFixed(2)}s)`
    : (timeLabel || `${sec}s`);

  const execLead = schedule.executionLeadMs ?? resolveClickExecutionLeadMs();
  const displayTargetMs = schedule.endTimeMs
    ? clickDisplayTargetMs(schedule.endTimeMs, offsetMs)
    : null;

  notifySchedule({
    type: "scheduled",
    jobId: key,
    waitMs: fireDelayMs,
    closeWaitMs: schedule.closeWaitMs,
    timeLabel: label,
    endTimeMs: schedule.endTimeMs,
    offsetMs,
    leadMs: execLead,
    source: schedule.source,
    fireDelayMs,
    displayTargetMs,
    displayRemainingMs: displaySec != null ? Math.round(Number(displaySec) * 1000) : null,
  });

  const executeAtMsPlanned = schedule.endTimeMs
    ? clickExecuteAtMs(schedule.endTimeMs, offsetMs)
    : scheduledAt + Math.max(0, Number(schedule.clickWaitMs) || 0) + execLead;

  clickLog("schedule", `job #${key} scheduled`, {
    jobId: key,
    urlKey,
    seq,
    source: schedule.source,
    endTimeMs: schedule.endTimeMs,
    displayTargetMs,
    executeAtMs: executeAtMsPlanned,
    fireDelayMs,
    offsetMs,
    leadMs: execLead,
    clickWaitMs: schedule.clickWaitMs,
    timeLabel: label,
    autoClickEnabled: settings.autoClickEnabled,
  });

  const clickTask = {};
  activeClickTask = clickTask;
  const clickGen = currentClickGeneration();
  const shouldAbort = () => (
    activeClickTask !== clickTask
    || !isCurrentClickGeneration(clickGen)
    || !isActiveLatestJob(urlKey, seq)
  );

  (async () => {
    let finalExecuteAtMs = null;
    let waitAbortLocal = null;
    try {
      while (!shouldAbort()) {
        const latest = loadSettings();
        const liveOffset = Number(latest.delayOffsetMs) || 0;
        let executeAtMs;
        if (schedule.endTimeMs) {
          executeAtMs = clickExecuteAtMs(schedule.endTimeMs, liveOffset);
        } else {
          const lead = schedule.executionLeadMs ?? resolveClickExecutionLeadMs();
          executeAtMs = scheduledAt + Math.max(0, Number(schedule.clickWaitMs) || 0) + lead;
        }
        if (!executeAtMs) return;

        let waitAborted = false;
        waitAbortLocal = () => { waitAborted = true; };
        registerClickWaitAbort(waitAbortLocal);

        const ok = await waitUntilTimestamp(executeAtMs, {
          shouldAbort: () => waitAborted || shouldAbort(),
        });
        clearClickWaitAbort(waitAbortLocal);
        waitAbortLocal = null;

        if (!ok || shouldAbort()) {
          clickLog("skip", `skip click job #${key} cancelled`, {
            jobId: key, seq, executeAtMs, clickGen,
          });
          console.log(`Skip click job #${key} — job mới hơn hoặc đã hủy`);
          return;
        }
        finalExecuteAtMs = executeAtMs;
        const waitEndedAt = Date.now();
        clickLog("wait", `job #${key} wait done`, {
          jobId: key,
          executeAtMs,
          waitEndedAt,
          driftMs: waitEndedAt - executeAtMs,
          offsetMs: liveOffset,
          clickGen,
        });
        notifySchedule({
          type: "wait",
          jobId: key,
          driftMs: waitEndedAt - executeAtMs,
          offsetMs: liveOffset,
          executeAtMs,
        });
        break;
      }

      if (shouldAbort() || !isCurrentClickGeneration(clickGen)) {
        clickLog("skip", `skip click job #${key} stale generation`, { jobId: key, clickGen });
        return;
      }

      if (process.platform === "darwin") ensureAccessibility(true);
      const latest = loadSettings();
      const { x: clickX, y: clickY } = resolveClickPoint(latest);

      if (shouldAbort() || !isCurrentClickGeneration(clickGen)) {
        clickLog("skip", `skip click job #${key} before invoke`, { jobId: key, clickGen });
        return;
      }

      const clickInvokeAt = Date.now();
      const result = await clickScreenPoint(clickX, clickY);

      if (shouldAbort() || !isCurrentClickGeneration(clickGen)) {
        clickLog("skip", `skip click job #${key} after invoke (stale)`, {
          jobId: key,
          clickGen,
          x: result.x,
          y: result.y,
        });
        return;
      }

      const clickedAt = Date.now();
      const displayTarget = schedule.endTimeMs
        ? clickDisplayTargetMs(schedule.endTimeMs, Number(latest.delayOffsetMs) || 0)
        : null;
      const execLeadDone = schedule.executionLeadMs ?? resolveClickExecutionLeadMs();
      notifySchedule({
        type: "clicked",
        jobId: key,
        x: result.x,
        y: result.y,
        method: result.method,
        clickedAt,
        endTimeMs: schedule.endTimeMs,
        displayTargetMs: displayTarget,
        driftFromDisplayMs: displayTarget != null ? clickedAt - displayTarget : null,
        overlayRemainingMs: displayTarget != null ? displayTarget - clickInvokeAt : null,
        source: schedule.source,
        clickDurationMs: result.durationMs,
        offsetMs: latest.delayOffsetMs,
        leadMs: execLeadDone,
      });
      clickLog("click", `job #${key} clicked`, {
        jobId: key,
        clickGen,
        x: result.x,
        y: result.y,
        method: result.method,
        clickDurationMs: result.durationMs,
        invokeDelayMs: finalExecuteAtMs != null ? clickInvokeAt - finalExecuteAtMs : null,
        driftFromDisplayMs: displayTarget != null ? clickedAt - displayTarget : null,
        source: schedule.source,
        offsetMs: latest.delayOffsetMs,
        leadMs: execLeadDone,
        endTimeMs: schedule.endTimeMs,
        displayTargetMs: displayTarget,
        clickedAt,
      });
      if (displayTarget != null && result.durationMs != null) {
        const beforeLead = execLeadDone;
        recordClickOutcome({
          clickDurationMs: result.durationMs,
          driftFromDisplayMs: clickedAt - displayTarget,
        });
        const leadStats = getClickLeadStats();
        if (leadStats.leadMs !== beforeLead) {
          clickLog("lead", "adaptive lead adjusted", leadStats);
        }
      }
      console.log(
        `Desktop click job #${key} at ${result.x},${result.y} (${result.method})`
        + ` source=${schedule.source} offset=${latest.delayOffsetMs}ms lead=${execLeadDone}ms`
        + (result.durationMs != null ? ` clickMs=${result.durationMs}` : "")
      );
      clearOverlayTiming();
    } catch (err) {
      clickLogError("click", `job #${key} failed`, {
        jobId: key,
        clickGen,
        error: String(err.message || err),
        source: schedule.source,
      });
      console.error("Desktop click failed:", err.message || err);
      notifySchedule({ type: "error", jobId: key, error: String(err.message || err) });
      clearOverlayTiming();
    } finally {
      if (waitAbortLocal) clearClickWaitAbort(waitAbortLocal);
      if (activeClickTask === clickTask) activeClickTask = null;
    }
  })();

  console.log(
    `Click job active (${urlKey}) source=${schedule.source}`
    + ` fire≈${displaySec ?? sec}s offset=${offsetMs}ms lead=${schedule.executionLeadMs ?? "?"}ms`
  );
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
  pruneJobEntries();

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

function broadcastClickLog(record) {
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.webContents.send("click-log", record);
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
    const { x, y } = resolveClickPoint(settings);
    const result = await clickScreenPoint(x, y);
    clickLog("click", "test click", {
      x: result.x,
      y: result.y,
      method: result.method,
      clickDurationMs: result.durationMs,
    });
    const clickedAt = Date.now();
    notifySchedule({
      type: "clicked",
      jobId: "test",
      x: result.x,
      y: result.y,
      method: result.method,
      clickedAt,
      displayTargetMs: null,
      driftFromDisplayMs: null,
      isTest: true,
      clickDurationMs: result.durationMs,
    });
    return result;
  });
  ipcMain.handle("settings:ensure-accessibility", async () => ensureAccessibility(true));
  ipcMain.handle("logs:get-recent", (_event, limit) => ({
    logs: getRecentUiLogs(limit),
    logsDir: resolveLogsDir(),
    logFile: logFilePath(),
  }));
  ipcMain.handle("logs:clear", () => {
    clearUiLogs();
    return { ok: true };
  });
  ipcMain.handle("logs:open-folder", async () => {
    const dir = resolveLogsDir();
    fs.mkdirSync(dir, { recursive: true });
    await shell.openPath(dir);
    return { ok: true, path: dir };
  });
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
    width: 520,
    height: 920,
    minWidth: 420,
    minHeight: 640,
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
  clickLog("startup", "desktop-tool started", {
    port,
    logsDir: resolveLogsDir(),
    logFile: logFilePath(),
    leadMs: resolveClickExecutionLeadMs(),
    leadStats: getClickLeadStats(),
    pollMs: POLL_MS,
  });
  console.log(`Click logs: ${logFilePath()}`);
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

  setLogUiListener(broadcastClickLog);
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
    if (process.platform === "win32") {
      setInterval(() => {
        if (!isWinClickHelperReady()) {
          warmUpWinClickHelper();
        }
      }, 60_000);
    }
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
  cancelActiveClickTask();
  destroyCountdownOverlay();
  jobEntries.clear();
  activeJobKey = null;
  activeOverlayTiming = null;
});
