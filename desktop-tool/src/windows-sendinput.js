/**
 * Windows click: SetCursorPos + mouse_event (nút) — SendInput từ Electron thường chỉ di chuột.
 */

const fs = require("fs");
const path = require("path");

const MOUSEEVENTF_LEFTDOWN = 0x0002;
const MOUSEEVENTF_LEFTUP = 0x0004;

const CURSOR_TOLERANCE_PX = 3;

let initialized = false;
let initError = null;
let koffi = null;
let SetCursorPos = null;
let GetCursorPos = null;
let MouseEvent = null;
let GetDoubleClickTime = null;

function isDoubleClickEnabled() {
  const v = String(process.env.DESKTOP_CLICK_DOUBLE ?? "true").trim().toLowerCase();
  return v !== "0" && v !== "false" && v !== "no";
}

function clickSettleMs() {
  const env = Number(process.env.DESKTOP_CLICK_SETTLE_MS);
  if (Number.isFinite(env) && env >= 0) return Math.round(env);
  return 20;
}

function clickStepMs() {
  const env = Number(process.env.DESKTOP_CLICK_STEP_MS);
  if (Number.isFinite(env) && env >= 0) return Math.round(env);
  return 12;
}

function doubleClickGapMs() {
  const env = Number(process.env.DESKTOP_CLICK_DOUBLE_GAP_MS);
  if (Number.isFinite(env) && env >= 0) return Math.round(env);
  try {
    if (GetDoubleClickTime) {
      const sys = GetDoubleClickTime();
      if (Number.isFinite(sys) && sys > 0) {
        return Math.max(40, Math.min(180, Math.round(sys / 3)));
      }
    }
  } catch {
    /* ignore */
  }
  return 60;
}

function resolveKoffiModule() {
  const candidates = ["koffi"];

  try {
    const { app } = require("electron");
    if (app) {
      candidates.push(
        path.join(process.resourcesPath, "app.asar.unpacked", "node_modules", "koffi"),
        path.join(process.resourcesPath, "node_modules", "koffi"),
      );
    }
  } catch {
    /* outside Electron */
  }

  candidates.push(path.join(__dirname, "..", "node_modules", "koffi"));

  let lastErr = null;
  for (const candidate of candidates) {
    try {
      if (candidate === "koffi") {
        return require("koffi");
      }
      if (fs.existsSync(path.join(candidate, "package.json"))) {
        return require(candidate);
      }
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr || new Error("Cannot find module 'koffi'");
}

function toAbsoluteCoord(coord, origin, span) {
  if (span <= 1) return 0;
  const normalized = (coord - origin) * 65535.0 / (span - 1);
  if (normalized < 0) return 0;
  if (normalized > 65535) return 65535;
  return Math.round(normalized);
}

function sleepMs(ms) {
  const wait = Math.max(0, Math.round(ms));
  if (wait <= 0) return;
  const end = Date.now() + wait;
  while (Date.now() < end) {
    /* busy-wait — chính xác hơn setTimeout cho chuỗi click */
  }
}

function initWindowsSendInput() {
  if (process.platform !== "win32") return false;
  if (initialized) return true;

  try {
    koffi = resolveKoffiModule();
    const user32 = koffi.load("user32.dll");

    koffi.struct("POINT", {
      x: "long",
      y: "long",
    });

    SetCursorPos = user32.func("bool __stdcall SetCursorPos(int32 x, int32 y)");
    GetCursorPos = user32.func("bool __stdcall GetCursorPos(_Out_ POINT *lpPoint)");
    MouseEvent = user32.func(
      "void __stdcall mouse_event(uint32 dwFlags, uint32 dx, uint32 dy, uint32 dwData, uintptr_t dwExtraInfo)"
    );
    GetDoubleClickTime = user32.func("uint32 __stdcall GetDoubleClickTime()");

    try {
      const setDpiAware = user32.func("bool __stdcall SetProcessDPIAware()");
      setDpiAware();
    } catch {
      /* optional */
    }

    initialized = true;
    initError = null;
    return true;
  } catch (err) {
    initError = err;
    return false;
  }
}

function readCursorPos() {
  const point = { x: 0, y: 0 };
  if (!GetCursorPos(point)) {
    return null;
  }
  return { x: point.x, y: point.y };
}

function pressButton(down) {
  const flag = down ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP;
  MouseEvent(flag, 0, 0, 0, 0);
}

function performButtonClicks() {
  sleepMs(clickSettleMs());
  pressButton(true);
  sleepMs(clickStepMs());
  pressButton(false);
  if (isDoubleClickEnabled()) {
    sleepMs(doubleClickGapMs());
    pressButton(true);
    sleepMs(clickStepMs());
    pressButton(false);
  }
}

function clickAt(px, py) {
  if (!initWindowsSendInput()) {
    return {
      ok: false,
      detail: initError ? String(initError.message || initError) : "mouse-init-not-ready",
    };
  }

  try {
    if (!SetCursorPos(px, py)) {
      return { ok: false, detail: "setcursorpos-failed" };
    }

    performButtonClicks();

    const pt = readCursorPos();
    if (!pt) {
      return { ok: false, detail: "getcursorpos-failed" };
    }
    if (Math.abs(pt.x - px) > CURSOR_TOLERANCE_PX || Math.abs(pt.y - py) > CURSOR_TOLERANCE_PX) {
      return {
        ok: false,
        detail: `cursor-at:${pt.x},${pt.y}`,
        actualX: pt.x,
        actualY: pt.y,
      };
    }

    return { ok: true, actualX: pt.x, actualY: pt.y };
  } catch (err) {
    return { ok: false, detail: String(err.message || err) };
  }
}

function pingLatencyMs() {
  if (!initWindowsSendInput()) {
    throw new Error("Mouse API not initialized");
  }
  const started = Date.now();
  readCursorPos();
  return Date.now() - started;
}

function isWindowsSendInputReady() {
  return initialized;
}

function getInitError() {
  return initError ? String(initError.message || initError) : null;
}

module.exports = {
  CURSOR_TOLERANCE_PX,
  toAbsoluteCoord,
  initWindowsSendInput,
  clickAt,
  pingLatencyMs,
  readCursorPos,
  isWindowsSendInputReady,
  getInitError,
  isDoubleClickEnabled,
};
