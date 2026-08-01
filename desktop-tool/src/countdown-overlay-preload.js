const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("countdownOverlay", {
  onUpdate(callback) {
    ipcRenderer.on("countdown-overlay:update", (_event, payload) => {
      callback(payload || { active: false });
    });
  },
});
