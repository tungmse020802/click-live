const { BrowserWindow, screen } = require("electron");
const path = require("path");

const OVERLAY_WIDTH = 320;
const OVERLAY_HEIGHT = 100;
const OVERLAY_MARGIN = 10;

let overlayWindow = null;
let overlayState = { active: false, targetAtMs: null };

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
  overlayWindow.webContents.send("countdown-overlay:update", overlayState);
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
    ...(process.platform === "darwin" ? { type: "panel" } : {}),
    webPreferences: {
      preload: path.join(__dirname, "countdown-overlay-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  overlayWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  overlayWindow.setAlwaysOnTop(true, "screen-saver", 1);
  overlayWindow.setIgnoreMouseEvents(true, { forward: true });

  overlayWindow.loadFile(path.join(__dirname, "..", "ui", "countdown-overlay.html"));
  overlayWindow.webContents.on("did-finish-load", () => {
    if (!overlayWindow || overlayWindow.isDestroyed()) return;
    overlayWindow.showInactive();
    pushOverlayState();
  });

  overlayWindow.on("closed", () => {
    overlayWindow = null;
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
