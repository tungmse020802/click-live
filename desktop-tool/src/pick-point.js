const { BrowserWindow, screen, ipcMain } = require("electron");
const path = require("path");

function pickPointOnScreen() {
  return new Promise((resolve, reject) => {
    const display = screen.getPrimaryDisplay();
    const { x, y, width, height } = display.bounds;
    const win = new BrowserWindow({
      x,
      y,
      width,
      height,
      transparent: true,
      frame: false,
      alwaysOnTop: true,
      skipTaskbar: true,
      resizable: false,
      movable: false,
      focusable: true,
      hasShadow: false,
      webPreferences: {
        nodeIntegration: true,
        contextIsolation: false,
      },
    });

    let settled = false;
    const finish = (fn) => {
      if (settled) return;
      settled = true;
      cleanup();
      if (!win.isDestroyed()) win.close();
      fn();
    };

    const onDone = (_event, point) => {
      if (_event.sender !== win.webContents) return;
      finish(() => resolve(point));
    };
    const onCancel = (_event) => {
      if (_event.sender !== win.webContents) return;
      finish(() => reject(new Error("Đã huỷ chọn điểm")));
    };

    const cleanup = () => {
      ipcMain.removeListener("pick-point-done", onDone);
      ipcMain.removeListener("pick-point-cancel", onCancel);
    };

    ipcMain.on("pick-point-done", onDone);
    ipcMain.on("pick-point-cancel", onCancel);
    win.on("closed", () => {
      finish(() => reject(new Error("Đã huỷ chọn điểm")));
    });

    win.setAlwaysOnTop(true, "screen-saver");
    win.loadFile(path.join(__dirname, "..", "ui", "pick-point.html"));
    win.show();
  });
}

module.exports = {
  pickPointOnScreen,
};
