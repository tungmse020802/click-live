const fs = require("fs");
const path = require("path");
const { app } = require("electron");

const DEFAULTS = {
  autoClickEnabled: true,
  clickX: 960,
  clickY: 540,
  /** Cộng vào mốc 0.0s (ms). Âm = click sớm (đồng hồ còn 0.09s…). Nút ±0.01s = ±10ms */
  delayOffsetMs: 0,
  /** Chờ mặc định nếu tin không có TIME */
  defaultWaitMs: 0,
  /** Queue server + desktop login (ưu tiên hơn .env sau khi đăng nhập) */
  queueUrl: "",
  queueUsername: "",
  pullToken: "",
};

let cache = null;
let settingsFilePath = null;

function resolveSettingsPath() {
  if (!settingsFilePath) {
    settingsFilePath = path.join(app.getPath("userData"), "settings.json");
  }
  return settingsFilePath;
}

function loadSettings() {
  if (cache) return { ...cache };
  try {
    const raw = fs.readFileSync(resolveSettingsPath(), "utf-8");
    cache = { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    cache = { ...DEFAULTS };
  }
  return { ...cache };
}

function saveSettings(partial) {
  const next = { ...loadSettings(), ...partial };
  cache = next;
  fs.mkdirSync(path.dirname(resolveSettingsPath()), { recursive: true });
  fs.writeFileSync(resolveSettingsPath(), `${JSON.stringify(next, null, 2)}\n`, "utf-8");
  return { ...next };
}

function adjustDelayOffset(deltaMs) {
  const current = loadSettings();
  return saveSettings({ delayOffsetMs: Math.round(current.delayOffsetMs + deltaMs) });
}

module.exports = {
  DEFAULTS,
  loadSettings,
  saveSettings,
  adjustDelayOffset,
};
