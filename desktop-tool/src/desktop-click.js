const { execFile } = require("child_process");
const { promisify } = require("util");
const fs = require("fs");
const path = require("path");

const execFileAsync = promisify(execFile);

function resolveCliclickBin() {
  const envBin = String(process.env.DESKTOP_CLICLICK_BIN || "").trim();
  if (envBin && fs.existsSync(envBin)) return envBin;

  const bundled = path.join(__dirname, "..", "resources", "bin", "darwin", "cliclick");
  if (fs.existsSync(bundled)) return bundled;

  const pathCandidates = [
    "/opt/homebrew/bin/cliclick",
    "/usr/local/bin/cliclick",
  ];
  for (const candidate of pathCandidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return "cliclick";
}

async function clickScreenPointWindows(px, py) {
  const script = [
    "Add-Type @\"",
    "using System;",
    "using System.Runtime.InteropServices;",
    "public class WinMouse {",
    "  [DllImport(\"user32.dll\")] public static extern bool SetCursorPos(int X, int Y);",
    "  [DllImport(\"user32.dll\")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint cButtons, uint dwExtraInfo);",
    "}",
    "\"@",
    `[WinMouse]::SetCursorPos(${px}, ${py}) | Out-Null`,
    "Start-Sleep -Milliseconds 30",
    "[WinMouse]::mouse_event(0x0002, 0, 0, 0, 0)",
    "[WinMouse]::mouse_event(0x0004, 0, 0, 0, 0)",
  ].join("; ");

  await execFileAsync("powershell.exe", [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    script,
  ]);
  return { method: "powershell", x: px, y: py };
}

async function clickScreenPointDarwin(px, py) {
  const cliclick = resolveCliclickBin();
  try {
    await execFileAsync(cliclick, [`c:${px},${py}`]);
    return { method: "cliclick", x: px, y: py };
  } catch (err) {
    const detail = String(err.stderr || err.message || err).trim();
    if (/could not be found|ENOENT/i.test(detail) || err.code === "ENOENT") {
      throw new Error(
        "Chưa cài cliclick. Chạy: brew install cliclick — rồi bật quyền Accessibility cho Electron/Click Live Desktop Tool."
      );
    }
    if (/Accessibility|assistive|not permitted|-25212|AXError/i.test(detail)) {
      throw new Error(
        "Thiếu quyền Accessibility. System Settings → Privacy & Security → Accessibility → bật cho Electron (hoặc Click Live Desktop Tool), rồi thử lại."
      );
    }
    throw new Error(detail || "Không click được desktop");
  }
}

async function clickScreenPoint(x, y) {
  const px = Math.round(Number(x));
  const py = Math.round(Number(y));
  if (!Number.isFinite(px) || !Number.isFinite(py)) {
    throw new Error("Tọa độ click không hợp lệ");
  }

  if (process.platform === "win32") {
    return clickScreenPointWindows(px, py);
  }
  if (process.platform === "darwin") {
    return clickScreenPointDarwin(px, py);
  }
  throw new Error(`Desktop click chưa hỗ trợ nền tảng: ${process.platform}`);
}

module.exports = {
  clickScreenPoint,
  resolveCliclickBin,
};
