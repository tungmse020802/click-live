/**
 * Windows click qua SendInput trực tiếp trong Electron main (koffi).
 */

const fs = require("fs");
const path = require("path");

const INPUT_MOUSE = 0;
const MOUSEEVENTF_LEFTDOWN = 0x0002;
const MOUSEEVENTF_LEFTUP = 0x0004;

const CURSOR_TOLERANCE_PX = 3;

let initialized = false;
let initError = null;
let koffi = null;
let INPUT = null;
let inputSize = 0;
let SendInput = null;
let SetCursorPos = null;
let GetCursorPos = null;

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

function makeMouseButtonEvent(flags) {
  return {
    type: INPUT_MOUSE,
    u: {
      mi: {
        dx: 0,
        dy: 0,
        mouseData: 0,
        dwFlags: flags,
        time: 0,
        dwExtraInfo: 0,
      },
    },
  };
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

    const MOUSEINPUT = koffi.struct("MOUSEINPUT", {
      dx: "long",
      dy: "long",
      mouseData: "uint32",
      dwFlags: "uint32",
      time: "uint32",
      dwExtraInfo: "uintptr_t",
    });

    const KEYBDINPUT = koffi.struct("KEYBDINPUT", {
      wVk: "uint16",
      wScan: "uint16",
      dwFlags: "uint32",
      time: "uint32",
      dwExtraInfo: "uintptr_t",
    });

    const HARDWAREINPUT = koffi.struct("HARDWAREINPUT", {
      uMsg: "uint32",
      wParamL: "uint16",
      wParamH: "uint16",
    });

    INPUT = koffi.struct("INPUT", {
      type: "uint32",
      u: koffi.union({
        mi: MOUSEINPUT,
        ki: KEYBDINPUT,
        hi: HARDWAREINPUT,
      }),
    });

    inputSize = koffi.sizeof(INPUT);
    SendInput = user32.func(
      "uint32 __stdcall SendInput(uint32 cInputs, INPUT *pInputs, int32 cbSize)"
    );
    SetCursorPos = user32.func("bool __stdcall SetCursorPos(int32 x, int32 y)");
    GetCursorPos = user32.func("bool __stdcall GetCursorPos(_Out_ POINT *lpPoint)");

    try {
      const setDpiAware = user32.func("bool SetProcessDPIAware()");
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

function sendRelativeClick() {
  const events = [
    makeMouseButtonEvent(MOUSEEVENTF_LEFTDOWN),
    makeMouseButtonEvent(MOUSEEVENTF_LEFTUP),
  ];
  return SendInput(events.length, events, inputSize);
}

function clickAt(px, py) {
  if (!initWindowsSendInput()) {
    return {
      ok: false,
      detail: initError ? String(initError.message || initError) : "sendinput-not-initialized",
    };
  }

  try {
    if (!SetCursorPos(px, py)) {
      return { ok: false, detail: "setcursorpos-failed" };
    }

    const sent = sendRelativeClick();
    if (sent !== 2) {
      return { ok: false, detail: `sendinput:${sent}` };
    }

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
    throw new Error("SendInput not initialized");
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
};
