"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("wdaPanel", {
  getConfig: () => ipcRenderer.invoke("config:get"),
  saveConfig: (config) => ipcRenderer.invoke("config:save", config),
  saveDevice: (deviceId, patch) => ipcRenderer.invoke("device:save", deviceId, patch),
  scan: () => ipcRenderer.invoke("agent:scan"),
  startDevice: (deviceId) => ipcRenderer.invoke("agent:startDevice", deviceId),
  stopDevice: (deviceId) => ipcRenderer.invoke("agent:stopDevice", deviceId),
  startAll: () => ipcRenderer.invoke("agent:startAll"),
  stopAll: () => ipcRenderer.invoke("agent:stopAll"),
  openUrl: (deviceId, url) => ipcRenderer.invoke("agent:openUrl", deviceId, url),
  health: () => ipcRenderer.invoke("agent:health"),
  refresh: () => ipcRenderer.invoke("agent:refresh"),
  queueList: (options) => ipcRenderer.invoke("queue:list", options),
  queueDispatch: (jobId, deviceId) => ipcRenderer.invoke("queue:dispatch", jobId, deviceId),
  queueMarkDone: (jobId, note) => ipcRenderer.invoke("queue:markDone", jobId, note),
  setupStatus: () => ipcRenderer.invoke("setup:status"),
  macStatus: () => ipcRenderer.invoke("setup:macStatus"),
  detectSigning: () => ipcRenderer.invoke("setup:detectSigning"),
  buildIpa: (options) => ipcRenderer.invoke("setup:buildIpa", options),
  openDriverDownload: () => ipcRenderer.invoke("setup:openDriverDownload"),
  installWda: (deviceId) => ipcRenderer.invoke("setup:installWda", deviceId),
  installWdaAll: () => ipcRenderer.invoke("setup:installWdaAll"),
  checkWdaInstalledAll: () => ipcRenderer.invoke("setup:checkWdaInstalledAll"),
  assignDetected: () => ipcRenderer.invoke("setup:assignDetected"),
  udidExports: () => ipcRenderer.invoke("setup:udidExports"),
  exportUdid: (format) => ipcRenderer.invoke("setup:exportUdid", format),
  onState: (callback) => ipcRenderer.on("agent:state", (_event, state) => callback(state)),
  onLog: (callback) => ipcRenderer.on("agent:log", (_event, line) => callback(line)),
});
