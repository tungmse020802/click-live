"use strict";

const fs = require("node:fs/promises");
const path = require("node:path");
const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const { FleetAgent } = require("./fleet-agent");
const { DeviceStore } = require("./device-store");

let mainWindow;
let agent;
const store = new DeviceStore();

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 820,
    minWidth: 1120,
    minHeight: 680,
    title: "WDA Control Panel",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, "index.html"));
}

function send(channel, payload) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send(channel, payload);
}

app.whenReady().then(() => {
  agent = new FleetAgent({
    store,
    onState: (state) => send("agent:state", state),
    onLog: (line) => send("agent:log", line),
  });

  ipcMain.handle("config:get", () => store.get());
  ipcMain.handle("config:save", (_event, nextConfig) => {
    const saved = store.save(nextConfig || {});
    agent.refreshFromStore();
    return saved;
  });
  ipcMain.handle("device:save", (_event, deviceId, patch) => {
    const saved = store.saveDevice(deviceId, patch || {});
    agent.refreshFromStore();
    return saved;
  });

  ipcMain.handle("agent:scan", () => agent.scanDetected());
  ipcMain.handle("agent:startDevice", (_event, deviceId) => agent.startDevice(deviceId));
  ipcMain.handle("agent:stopDevice", (_event, deviceId) => agent.stopDevice(deviceId));
  ipcMain.handle("agent:startAll", () => agent.startAllEnabled());
  ipcMain.handle("agent:stopAll", () => agent.stopAll());
  ipcMain.handle("agent:openUrl", (_event, deviceId, url) => agent.openUrlOnDevice(deviceId, url));
  ipcMain.handle("agent:health", () => agent.healthCheckAll());
  ipcMain.handle("agent:refresh", () => agent.snapshot());
  ipcMain.handle("queue:list", (_event, options) => agent.fetchQueue(options || {}));
  ipcMain.handle("queue:dispatch", (_event, jobId, deviceId) => agent.dispatchQueueItem(jobId, deviceId));
  ipcMain.handle("queue:markDone", (_event, jobId, note) => agent.markQueueItemDone(jobId, note));

  ipcMain.handle("setup:status", () => agent.setupStatus());
  ipcMain.handle("setup:macStatus", () => agent.macSetupStatus());
  ipcMain.handle("setup:detectSigning", () => agent.detectSigning());
  ipcMain.handle("setup:buildIpa", (_event, options) => agent.buildIpa(options || {}));
  ipcMain.handle("setup:openDriverDownload", () => agent.openDriverDownload());
  ipcMain.handle("setup:installWda", (_event, deviceId) => agent.installWda(deviceId));
  ipcMain.handle("setup:installWdaAll", () => agent.installWdaAll());
  ipcMain.handle("setup:checkWdaInstalledAll", () => agent.checkWdaInstalledAll());
  ipcMain.handle("setup:assignDetected", () => agent.assignDetectedToSlots());
  ipcMain.handle("setup:udidExports", () => agent.buildUdidExports());
  ipcMain.handle("setup:exportUdid", async (_event, format) => {
    const exports = agent.buildUdidExports();
    if (!exports.count) throw new Error("No detected devices to export. Run Scan USB first.");
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const defaults = {
      internal: { name: `udids-internal-${stamp}.csv`, body: exports.internalCsv },
      developer: { name: `udids-developer-portal-${stamp}.csv`, body: exports.developerCsv },
      txt: { name: `udids-${stamp}.txt`, body: exports.udidsTxt },
    };
    const target = defaults[format] || defaults.developer;
    const result = await dialog.showSaveDialog(mainWindow, {
      title: "Save UDID export",
      defaultPath: target.name,
      filters: [
        { name: "CSV", extensions: ["csv"] },
        { name: "Text", extensions: ["txt"] },
        { name: "All Files", extensions: ["*"] },
      ],
    });
    if (result.canceled || !result.filePath) return { canceled: true };
    await fs.writeFile(result.filePath, target.body, "utf8");
    return { canceled: false, filePath: result.filePath, count: exports.count };
  });

  createWindow();
  (async () => {
    try {
      await agent.scanDetected();
    } catch (error) {
      send("agent:log", `Initial scan failed: ${error.message}`);
    }
    try {
      await agent.startAllEnabled();
    } catch (error) {
      send("agent:log", `Auto start failed: ${error.message}`);
    }
  })();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", async (event) => {
  if (agent) {
    event.preventDefault();
    await agent.stopAll();
    app.exit(0);
  }
});
