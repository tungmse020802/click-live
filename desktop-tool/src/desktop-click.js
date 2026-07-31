const { execFile, spawn } = require("child_process");
const { promisify } = require("util");
const fs = require("fs");
const os = require("os");
const path = require("path");

const execFileAsync = promisify(execFile);

let winClickHelper = null;
let winClickReady = null;
let winClickQueue = Promise.resolve();

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

function helperScriptPath() {
  return path.join(__dirname, "windows-click-helper.ps1");
}

function ensureWinClickHelper() {
  if (winClickHelper && !winClickHelper.killed) {
    return Promise.resolve();
  }
  if (winClickReady) return winClickReady;

  winClickReady = new Promise((resolve, reject) => {
    const ps1 = helperScriptPath();
    if (!fs.existsSync(ps1)) {
      winClickReady = null;
      reject(new Error("windows-click-helper.ps1 not found"));
      return;
    }

    const child = spawn("powershell.exe", [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-Sta",
      "-File",
      ps1,
    ], {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });

    let buffer = "";
    const timer = setTimeout(() => {
      try { child.kill(); } catch { /* ignore */ }
      winClickReady = null;
      reject(new Error("Windows click helper startup timeout"));
    }, 15000);

    const fail = (err) => {
      clearTimeout(timer);
      winClickReady = null;
      winClickHelper = null;
      reject(err);
    };

    child.stdout.on("data", (chunk) => {
      buffer += chunk.toString();
      if (buffer.includes("ready")) {
        clearTimeout(timer);
        winClickHelper = child;
        resolve();
      }
    });

    child.stderr.on("data", (chunk) => {
      const msg = chunk.toString().trim();
      if (msg) console.warn("win-click-helper:", msg);
    });

    child.on("error", fail);
    child.on("exit", () => {
      winClickHelper = null;
      winClickReady = null;
    });
  });

  return winClickReady;
}

function clickViaHelper(px, py) {
  return new Promise((resolve, reject) => {
    if (!winClickHelper || winClickHelper.killed) {
      reject(new Error("Windows click helper not running"));
      return;
    }

    let buffer = "";
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("Windows click timeout"));
    }, 3000);

    const onData = (chunk) => {
      buffer += chunk.toString();
      if (buffer.includes("ok")) {
        cleanup();
        resolve({ method: "powershell-helper", x: px, y: py });
      } else if (buffer.includes("err")) {
        cleanup();
        reject(new Error("Windows click helper rejected input"));
      }
    };

    const cleanup = () => {
      clearTimeout(timer);
      winClickHelper.stdout.off("data", onData);
    };

    winClickHelper.stdout.on("data", onData);
    winClickHelper.stdin.write(`${px},${py}\n`);
  });
}

async function clickScreenPointWindowsFallback(px, py) {
  const script = [
    "$sig = @'",
    "[DllImport(\"user32.dll\")] public static extern bool SetCursorPos(int X, int Y);",
    "[DllImport(\"user32.dll\")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint cButtons, uint dwExtraInfo);",
    "'@",
    '$null = Add-Type -MemberDefinition $sig -Name WinMouse -Namespace ClickLive -PassThru',
    `[ClickLive.WinMouse]::SetCursorPos(${px}, ${py}) | Out-Null`,
    "[ClickLive.WinMouse]::mouse_event(0x0002, 0, 0, 0, 0)",
    "[ClickLive.WinMouse]::mouse_event(0x0004, 0, 0, 0, 0)",
    "",
  ].join("\r\n");

  const ps1 = path.join(os.tmpdir(), `click-live-click-${process.pid}-${Date.now()}.ps1`);
  fs.writeFileSync(ps1, script, "utf8");

  try {
    await execFileAsync("powershell.exe", [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      ps1,
    ]);
  } catch (err) {
    const detail = String(err.stderr || err.message || err).trim();
    throw new Error(detail || "Windows click failed");
  } finally {
    try {
      fs.unlinkSync(ps1);
    } catch {
      /* ignore */
    }
  }

  return { method: "powershell", x: px, y: py };
}

async function clickScreenPointWindowsInner(px, py) {
  try {
    await ensureWinClickHelper();
    return await clickViaHelper(px, py);
  } catch (err) {
    console.warn("Windows click helper failed, fallback:", err.message || err);
    return clickScreenPointWindowsFallback(px, py);
  }
}

function clickScreenPointWindows(px, py) {
  const task = winClickQueue
    .catch(() => {})
    .then(() => clickScreenPointWindowsInner(px, py));
  winClickQueue = task.catch(() => {});
  return task;
}

function warmUpWinClickHelper() {
  if (process.platform !== "win32") return Promise.resolve();
  return ensureWinClickHelper().catch((err) => {
    console.warn("Windows click helper warmup failed:", err.message || err);
  });
}

function shutdownWinClickHelper() {
  if (winClickHelper && !winClickHelper.killed) {
    try {
      winClickHelper.stdin.write("quit\n");
    } catch {
      /* ignore */
    }
    try {
      winClickHelper.kill();
    } catch {
      /* ignore */
    }
  }
  winClickHelper = null;
  winClickReady = null;
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
        "Chua cai cliclick. Chay: brew install cliclick — roi bat quyen Accessibility cho Electron."
      );
    }
    if (/Accessibility|assistive|not permitted|-25212|AXError/i.test(detail)) {
      throw new Error(
        "Thieu quyen Accessibility. System Settings → Privacy → Accessibility → bat cho Electron."
      );
    }
    throw new Error(detail || "Khong click duoc desktop");
  }
}

async function clickScreenPoint(x, y) {
  const px = Math.round(Number(x));
  const py = Math.round(Number(y));
  if (!Number.isFinite(px) || !Number.isFinite(py)) {
    throw new Error("Toa do click khong hop le");
  }

  if (process.platform === "win32") {
    return clickScreenPointWindows(px, py);
  }
  if (process.platform === "darwin") {
    return clickScreenPointDarwin(px, py);
  }
  throw new Error(`Desktop click chua ho tro nen tang: ${process.platform}`);
}

module.exports = {
  clickScreenPoint,
  resolveCliclickBin,
  warmUpWinClickHelper,
  shutdownWinClickHelper,
};
