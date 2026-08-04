const fs = require("fs");
const path = require("path");

const MAX_UI_LOGS = 250;
const uiBuffer = [];
let uiListener = null;

let logsDirCache = null;

function resolveLogsDir() {
  if (logsDirCache) return logsDirCache;

  const envDir = String(process.env.DESKTOP_TOOL_LOG_DIR || "").trim();
  if (envDir) {
    logsDirCache = path.resolve(envDir);
    return logsDirCache;
  }

  try {
    const { app } = require("electron");
    if (app?.getPath) {
      logsDirCache = path.join(app.getPath("userData"), "logs");
      return logsDirCache;
    }
  } catch {
    /* chạy ngoài Electron */
  }

  logsDirCache = path.join(__dirname, "..", "logs");
  return logsDirCache;
}

function logFilePath(forDate = new Date()) {
  const y = forDate.getFullYear();
  const m = String(forDate.getMonth() + 1).padStart(2, "0");
  const d = String(forDate.getDate()).padStart(2, "0");
  return path.join(resolveLogsDir(), `click-${y}-${m}-${d}.log`);
}

function setLogUiListener(listener) {
  uiListener = typeof listener === "function" ? listener : null;
}

function getRecentUiLogs(limit = MAX_UI_LOGS) {
  const n = Math.max(1, Math.min(MAX_UI_LOGS, Number(limit) || MAX_UI_LOGS));
  return uiBuffer.slice(-n);
}

function clearUiLogs() {
  uiBuffer.length = 0;
}

function pushUiBuffer(record) {
  uiBuffer.push(record);
  while (uiBuffer.length > MAX_UI_LOGS) uiBuffer.shift();
  if (uiListener) {
    try {
      uiListener(record);
    } catch {
      /* ignore UI push errors */
    }
  }
}

function writeEntry(entry) {
  const record = {
    ts: new Date().toISOString(),
    pid: process.pid,
    platform: process.platform,
    ...entry,
  };
  const line = JSON.stringify(record);
  const event = record.event || record.level || "?";
  const msg = record.msg || "";
  const extra = record.data != null ? record.data : null;
  const consoleLine = `${record.ts} [${event}] ${msg}`;

  if (record.level === "error") {
    console.error(consoleLine, extra != null ? extra : "");
  } else if (record.level === "warn") {
    console.warn(consoleLine, extra != null ? extra : "");
  } else {
    console.log(consoleLine, extra != null ? extra : "");
  }

  pushUiBuffer(record);

  try {
    fs.mkdirSync(resolveLogsDir(), { recursive: true });
    fs.appendFileSync(logFilePath(), `${line}\n`, "utf8");
  } catch (err) {
    console.warn("click-log write failed:", err.message || err);
  }
}

function clickLog(event, msg, data = null) {
  writeEntry({ level: "info", event, msg, data });
}

function clickLogWarn(event, msg, data = null) {
  writeEntry({ level: "warn", event, msg, data });
}

function clickLogError(event, msg, data = null) {
  writeEntry({ level: "error", event, msg, data });
}

module.exports = {
  resolveLogsDir,
  logFilePath,
  clickLog,
  clickLogWarn,
  clickLogError,
  setLogUiListener,
  getRecentUiLogs,
  clearUiLogs,
};
