"use strict";

const Store = require("electron-store");

const DEFAULT_DEVICES = Array.from({ length: 20 }, (_value, index) => ({
  deviceId: `iphone-${String(index + 1).padStart(2, "0")}`,
  name: "",
  udid: "",
  port: 8100 + index,
  enabled: index === 0,
}));

const defaults = {
  launcherTool: process.platform === "darwin" ? "macos" : "go-ios",
  goIosPath: "",
  pymobiledevice3Path: "pymobiledevice3",
  wdaBundleId: "com.clicklive.WebDriverAgentRunner.xctrunner",
  wdaIpaPath: "",
  wdaProjectPath: "",
  derivedDataPath: "",
  appleTeamId: "",
  signingIdentity: "",
  queueUrl: "http://103.38.237.7:8787",
  automationEnabled: true,
  automationControllerPath: "",
  pythonPath: "",
  queuePollWaitSeconds: 25,
  liveTimeMinSeconds: 20,
  liveTimeMaxSeconds: 30,
  openTapRequestLeadMs: 2500,
  openTapTransportCompensationMs: 0,
  openMaxLatenessMs: 1500,
  filterMaxViews: 0,
  filterRewardMode: "all",
  filterMinBox1: 0,
  filterMinBox2: 0,
  filterMinRate: 0,
  filterNoteContains: "",
  devices: DEFAULT_DEVICES,
};

class DeviceStore {
  constructor() {
    this.store = new Store({ name: "wda-control-panel-devices", defaults });
  }

  get() {
    const value = normalizeConfig({ ...defaults, ...this.store.store });
    const stored = this.store.store || {};
    if (settingsNeedMigration(stored, value)) {
      this.store.set(value);
    }
    return value;
  }

  save(config) {
    const next = normalizeConfig({ ...this.get(), ...config });
    this.store.set(next);
    return this.get();
  }

  saveDevice(deviceId, patch) {
    const current = this.get();
    current.devices = current.devices.map((device) => (
      device.deviceId === deviceId ? { ...device, ...patch } : device
    ));
    return this.save(current);
  }
}

function normalizeConfig(config) {
  const next = { ...defaults, ...config };
  next.devices = normalizeDevices(next.devices);

  next.queuePollWaitSeconds = positiveNumber(next.queuePollWaitSeconds, defaults.queuePollWaitSeconds);
  next.liveTimeMinSeconds = migrateOldNumber(
    next.liveTimeMinSeconds,
    defaults.liveTimeMinSeconds,
    [13, 15],
  );
  next.liveTimeMaxSeconds = migrateOldNumber(
    next.liveTimeMaxSeconds,
    defaults.liveTimeMaxSeconds,
    [20, 25, 40],
  );
  next.openTapRequestLeadMs = migrateOldNumber(
    next.openTapRequestLeadMs,
    defaults.openTapRequestLeadMs,
    [1100, 1200],
  );
  next.openTapTransportCompensationMs = migrateOldNumber(
    next.openTapTransportCompensationMs,
    defaults.openTapTransportCompensationMs,
    [200, 400],
  );
  next.openMaxLatenessMs = nonNegativeNumber(next.openMaxLatenessMs, defaults.openMaxLatenessMs);
  next.filterMaxViews = nonNegativeNumber(next.filterMaxViews, defaults.filterMaxViews);
  next.filterRewardMode = normalizeRewardMode(next.filterRewardMode);
  next.filterMinBox1 = nonNegativeNumber(next.filterMinBox1, defaults.filterMinBox1);
  next.filterMinBox2 = nonNegativeNumber(next.filterMinBox2, defaults.filterMinBox2);
  next.filterMinRate = nonNegativeNumber(next.filterMinRate, defaults.filterMinRate);
  next.filterNoteContains = String(next.filterNoteContains || "").trim();

  if (next.liveTimeMinSeconds > next.liveTimeMaxSeconds) {
    next.liveTimeMinSeconds = defaults.liveTimeMinSeconds;
    next.liveTimeMaxSeconds = defaults.liveTimeMaxSeconds;
  }
  return next;
}

function settingsNeedMigration(stored, normalized) {
  return JSON.stringify(normalizeComparable(stored)) !== JSON.stringify(normalizeComparable(normalized));
}

function normalizeComparable(value) {
  const next = { ...value };
  delete next.devices;
  return next;
}

function normalizeRewardMode(value) {
  const mode = String(value || "").trim().toLowerCase();
  return ["all", "bag", "box", "both"].includes(mode) ? mode : defaults.filterRewardMode;
}

function positiveNumber(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : fallback;
}

function nonNegativeNumber(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : fallback;
}

function migrateOldNumber(value, fallback, oldValues) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return fallback;
  return oldValues.includes(number) ? fallback : number;
}

function normalizeDevices(devices) {
  const input = Array.isArray(devices) ? devices : [];
  const byId = new Map(input.map((device) => [device.deviceId, device]));
  return DEFAULT_DEVICES.map((fallback) => {
    const device = byId.get(fallback.deviceId) || {};
    return {
      ...fallback,
      ...device,
      port: Number(device.port || fallback.port),
      enabled: Boolean(device.enabled),
    };
  });
}

module.exports = { DeviceStore, DEFAULT_DEVICES };
