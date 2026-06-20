"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { app } = require("electron");

const DEFAULT_WDA_PROJECT_PATH = path.resolve(
  __dirname,
  "..",
  "..",
  "ios_wda_controller",
  "node_modules",
  "appium-xcuitest-driver",
  "node_modules",
  "appium-webdriveragent",
  "WebDriverAgent.xcodeproj",
);

const DEFAULT_DERIVED_DATA_PATH = path.join(os.homedir(), ".wda-control-panel", "DerivedData");

function projectRoot() {
  if (app?.isPackaged) return process.resourcesPath;
  return path.resolve(__dirname, "..");
}

function resourcePath(...parts) {
  return path.join(projectRoot(), "resources", ...parts);
}

function bundledGoIosPath() {
  const platformDir = process.platform === "win32"
    ? "windows"
    : process.platform === "darwin"
      ? "darwin"
      : "linux";
  const binary = process.platform === "win32" ? "ios.exe" : "ios";
  return resourcePath("bin", platformDir, binary);
}

function bundledIpaPath() {
  return resourcePath("ipa", "WebDriverAgentRunner.ipa");
}

function pathExists(target) {
  try {
    fs.accessSync(target);
    return true;
  } catch {
    return false;
  }
}

function resolveGoIosPath(config = {}) {
  if (config.goIosPath && config.goIosPath !== "ios") return config.goIosPath;
  const bundled = bundledGoIosPath();
  if (pathExists(bundled)) return bundled;
  return "ios";
}

function resolveIpaPath(config = {}) {
  if (config.wdaIpaPath && pathExists(config.wdaIpaPath)) return config.wdaIpaPath;
  const bundled = bundledIpaPath();
  if (pathExists(bundled)) return bundled;
  return config.wdaIpaPath || bundled;
}

function resolveWdaProjectPath(config = {}) {
  if (config.wdaProjectPath && pathExists(config.wdaProjectPath)) return config.wdaProjectPath;
  if (pathExists(DEFAULT_WDA_PROJECT_PATH)) return DEFAULT_WDA_PROJECT_PATH;
  return config.wdaProjectPath || DEFAULT_WDA_PROJECT_PATH;
}

function resolveDerivedDataPath(config = {}) {
  return config.derivedDataPath || DEFAULT_DERIVED_DATA_PATH;
}

module.exports = {
  projectRoot,
  resourcePath,
  bundledGoIosPath,
  bundledIpaPath,
  pathExists,
  resolveGoIosPath,
  resolveIpaPath,
  resolveWdaProjectPath,
  resolveDerivedDataPath,
  DEFAULT_WDA_PROJECT_PATH,
  DEFAULT_DERIVED_DATA_PATH,
};
