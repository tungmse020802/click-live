const { BrowserWindow, screen } = require("electron");
const path = require("path");

const OVERLAY_WIDTH = 320;
const OVERLAY_HEIGHT = 100;
const OVERLAY_MARGIN = 10;

let overlayWindow = null;
let overlayState = { active: false, targetAtMs: null };
let overlayPageReady = false;

function overlayPosition() {
  const display = screen.getPrimaryDisplay();
  const { x, y } = display.bounds;
  return {
    x: x + OVERLAY_MARGIN,
    y: y + OVERLAY_MARGIN,
  };
}

function pushOverlayState() {
  if (!overlayWindow || overlayWindow.isDestroyed()) return;
  if (!overlayPageReady || overlayWindow.webContents.isLoading()) return;
  try {
    overlayWindow.webContents.send("countdown-overlay:update", overlayState);
  } catch (err) {
    console.warn("countdown overlay push failed:", err.message || err);
  }
}

function showOverlayWindow() {
  if (!overlayWindow || overlayWindow.isDestroyed()) return;
  if (process.platform === "darwin") {
    overlayWindow.showInactive();
  } else {
    overlayWindow.show();
  }
  overlayWindow.setAlwaysOnTop(true, "screen-saver", 1);
}

function ensureCountdownOverlay() {
  if (overlayWindow && !overlayWindow.isDestroyed()) return overlayWindow;

  const { x, y } = overlayPosition();
  overlayWindow = new BrowserWindow({
    x,
    y,
    width: OVERLAY_WIDTH,
    height: OVERLAY_HEIGHT,
    transparent: true,
    backgroundColor: "#00000000",
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    closable: false,
    focusable: false,
    hasShadow: false,
    show: false,
    thickFrame: false,
    ...(process.platform === "darwin" ? { type: "panel" } : {}),
    ...(process.platform === "win32" ? { roundedCorners: false } : {}),
    webPreferences: {
      preload: path.join(__dirname, "countdown-overlay-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  overlayPageReady = false;

  overlayWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  overlayWindow.setAlwaysOnTop(true, "screen-saver", 1);
  overlayWindow.setIgnoreMouseEvents(true, { forward: true });

  overlayWindow.loadFile(path.join(__dirname, "..", "ui", "countdown-overlay.html"));
  overlayWindow.webContents.on("did-finish-load", () => {
    if (!overlayWindow || overlayWindow.isDestroyed()) return;
    overlayPageReady = true;
    showOverlayWindow();
    pushOverlayState();
  });
  overlayWindow.webContents.on("did-fail-load", (_event, code, desc) => {
    console.error("countdown overlay load failed:", code, desc);
  });

  overlayWindow.on("closed", () => {
    overlayWindow = null;
    overlayPageReady = false;
  });

  return overlayWindow;
}

/** @param {{ targetAtMs?: number | null, active?: boolean }} state */
function setCountdownOverlay(state = {}) {
  ensureCountdownOverlay();
  if (state.active === false) {
    overlayState = { active: false, targetAtMs: null };
  } else {
    overlayState = {
      active: true,
      targetAtMs: Number(state.targetAtMs) || null,
    };
    showOverlayWindow();
  }
  pushOverlayState();
}

function clearCountdownOverlay() {
  setCountdownOverlay({ active: false });
}

function destroyCountdownOverlay() {
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.destroy();
  }
  overlayWindow = null;
  overlayState = { active: false, targetAtMs: null };
}

module.exports = {
  ensureCountdownOverlay,
  setCountdownOverlay,
  clearCountdownOverlay,
  destroyCountdownOverlay,
};
