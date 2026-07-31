const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktopTool", {
  getSettings: () => ipcRenderer.invoke("settings:get"),
  saveSettings: (partial) => ipcRenderer.invoke("settings:save", partial),
  adjustDelay: (deltaMs) => ipcRenderer.invoke("settings:adjust-delay", deltaMs),
  pickPoint: () => ipcRenderer.invoke("settings:pick-point"),
  testClick: () => ipcRenderer.invoke("settings:test-click"),
  ensureAccessibility: () => ipcRenderer.invoke("settings:ensure-accessibility"),
  getSession: () => ipcRenderer.invoke("auth:session"),
  fetchUsers: (queueUrl) => ipcRenderer.invoke("auth:fetch-users", queueUrl),
  login: (payload) => ipcRenderer.invoke("auth:login", payload),
  logout: () => ipcRenderer.invoke("auth:logout"),
  onSchedule: (callback) => {
    ipcRenderer.on("countdown-schedule", (_event, payload) => callback(payload));
  },
});
