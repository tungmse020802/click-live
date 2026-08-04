/**
 * Windows click qua SendInput trực tiếp trong Electron main (koffi).
 * Không spawn PowerShell — ổn định latency và tránh false-positive "ok".
 */

const INPUT_MOUSE = 0;
const MOUSEEVENTF_MOVE = 0x0001;
const MOUSEEVENTF_LEFTDOWN = 0x0002;
const MOUSEEVENTF_LEFTUP = 0x0004;
const MOUSEEVENTF_ABSOLUTE = 0x8000;
const MOUSEEVENTF_VIRTUALDESK = 0x4000;

const SM_XVIRTUALSCREEN = 76;
const SM_YVIRTUALSCREEN = 77;
const SM_CXVIRTUALSCREEN = 78;
const SM_CYVIRTUALSCREEN = 79;

const CURSOR_TOLERANCE_PX = 3;

let initialized = false;
let initError = null;
let koffi = null;
let INPUT = null;
let inputSize = 0;
let SendInput = null;
let GetCursorPos = null;
let GetSystemMetrics = null;

function toAbsoluteCoord(coord, origin, span) {
  if (span <= 1) return 0;
  const normalized = (coord - origin) * 65535.0 / (span - 1);
  if (normalized < 0) return 0;
  if (normalized > 65535) return 65535;
  return Math.round(normalized);
}

function initWindowsSendInput() {
  if (process.platform !== "win32") return false;
  if (initialized) return true;
  if (initError) return false;

  try {
    koffi = require("koffi");
    const user32 = koffi.load("user32.dll");

    const POINT = koffi.struct("POINT", {
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

    INPUT = koffi.struct("INPUT", {
      type: "uint32",
      mi: MOUSEINPUT,
    });

    inputSize = koffi.sizeof(INPUT);
    SendInput = user32.func("uint32 SendInput(uint32 nInputs, INPUT *pInputs, int32 cbSize)");
    GetCursorPos = user32.func("bool GetCursorPos(_Out_ POINT *lpPoint)");
    GetSystemMetrics = user32.func("int32 GetSystemMetrics(int32 nIndex)");

    try {
      const setDpiAware = user32.func("bool SetProcessDPIAware()");
      setDpiAware();
    } catch {
      /* optional */
    }

    initialized = true;
    return true;
  } catch (err) {
    initError = err;
    return false;
  }
}

function readCursorPos() {
  const pt = koffi.alloc("POINT");
  if (!GetCursorPos(pt)) {
    return null;
  }
  const decoded = koffi.decode(pt, "POINT");
  return { x: decoded.x, y: decoded.y };
}

function readVirtualScreen() {
  return {
    x: GetSystemMetrics(SM_XVIRTUALSCREEN),
    y: GetSystemMetrics(SM_YVIRTUALSCREEN),
    width: GetSystemMetrics(SM_CXVIRTUALSCREEN),
    height: GetSystemMetrics(SM_CYVIRTUALSCREEN),
  };
}

function buildClickInputs(px, py) {
  const screen = readVirtualScreen();
  if (screen.width <= 0 || screen.height <= 0) {
    return { error: "virtual-screen-metrics" };
  }

  const absX = toAbsoluteCoord(px, screen.x, screen.width);
  const absY = toAbsoluteCoord(py, screen.y, screen.height);
  const INPUT_3 = koffi.array(INPUT, 3);
  const inputs = new INPUT_3();

  inputs[0] = {
    type: INPUT_MOUSE,
    mi: {
      dx: absX,
      dy: absY,
      mouseData: 0,
      dwFlags: MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
      time: 0,
      dwExtraInfo: 0,
    },
  };
  inputs[1] = {
    type: INPUT_MOUSE,
    mi: {
      dx: 0,
      dy: 0,
      mouseData: 0,
      dwFlags: MOUSEEVENTF_LEFTDOWN,
      time: 0,
      dwExtraInfo: 0,
    },
  };
  inputs[2] = {
    type: INPUT_MOUSE,
    mi: {
      dx: 0,
      dy: 0,
      mouseData: 0,
      dwFlags: MOUSEEVENTF_LEFTUP,
      time: 0,
      dwExtraInfo: 0,
    },
  };

  return { inputs, screen };
}

function clickAt(px, py) {
  if (!initWindowsSendInput()) {
    return {
      ok: false,
      detail: initError ? String(initError.message || initError) : "sendinput-not-initialized",
    };
  }

  const built = buildClickInputs(px, py);
  if (built.error) {
    return { ok: false, detail: built.error };
  }

  const sent = SendInput(3, built.inputs, inputSize);
  if (sent !== 3) {
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
  INPUT_MOUSE,
  MOUSEEVENTF_MOVE,
  MOUSEEVENTF_LEFTDOWN,
  MOUSEEVENTF_LEFTUP,
  MOUSEEVENTF_ABSOLUTE,
  MOUSEEVENTF_VIRTUALDESK,
  SM_XVIRTUALSCREEN,
  SM_YVIRTUALSCREEN,
  SM_CXVIRTUALSCREEN,
  SM_CYVIRTUALSCREEN,
  CURSOR_TOLERANCE_PX,
  toAbsoluteCoord,
  initWindowsSendInput,
  clickAt,
  pingLatencyMs,
  readCursorPos,
  readVirtualScreen,
  isWindowsSendInputReady,
  getInitError,
};
