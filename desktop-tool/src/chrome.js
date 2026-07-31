const { execFile, spawn } = require("child_process");
const { promisify } = require("util");
const fs = require("fs");
const path = require("path");

const execFileAsync = promisify(execFile);

const CHROME_APP = process.env.DESKTOP_CHROME_APP || "Google Chrome";
const CHROME_BIN =
  process.env.DESKTOP_CHROME_BIN ||
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
/** Incognito tránh localStorage app_link (TikTok @junb...) từ Chrome thường */
const USE_INCOGNITO = process.env.DESKTOP_CHROME_INCOGNITO !== "false";

function escapeAppleScript(value) {
  return String(value || "")
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"');
}

function resolveChromeBin() {
  const envBin = String(process.env.DESKTOP_CHROME_BIN || "").trim();
  if (envBin && fs.existsSync(envBin)) return envBin;

  if (process.platform === "win32") {
    const candidates = [
      path.join(process.env.PROGRAMFILES || "C:\\Program Files", "Google", "Chrome", "Application", "chrome.exe"),
      path.join(process.env["PROGRAMFILES(X86)"] || "C:\\Program Files (x86)", "Google", "Chrome", "Application", "chrome.exe"),
      path.join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "Application", "chrome.exe"),
    ];
    for (const candidate of candidates) {
      if (candidate && fs.existsSync(candidate)) return candidate;
    }
    return "chrome.exe";
  }

  if (process.platform === "linux") {
    const candidates = [
      "/usr/bin/google-chrome",
      "/usr/bin/google-chrome-stable",
      "/usr/bin/chromium-browser",
      "/usr/bin/chromium",
    ];
    for (const candidate of candidates) {
      if (fs.existsSync(candidate)) return candidate;
    }
    return "google-chrome";
  }

  if (fs.existsSync(CHROME_BIN)) return CHROME_BIN;
  return CHROME_BIN;
}

function chromeBinReady(bin) {
  if (fs.existsSync(bin)) return bin;
  if (process.platform === "win32" && !bin.includes("\\") && !bin.includes("/")) {
    throw new Error(
      `Không tìm thấy Google Chrome (${bin}). Cài Chrome hoặc thêm vào .env:\nDESKTOP_CHROME_BIN=C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe`
    );
  }
  if (process.platform !== "win32" && bin.includes("/") && !fs.existsSync(bin)) {
    throw new Error(`Không tìm thấy Chrome tại: ${bin}`);
  }
  return bin;
}

function spawnDetached(bin, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(bin, args, {
      detached: true,
      stdio: "ignore",
      windowsHide: true,
    });
    child.once("error", (err) => {
      reject(new Error(`${err.message} (bin=${bin})`));
    });
    child.once("spawn", () => {
      child.unref();
      resolve();
    });
  });
}

/** Windows: fallback qua cmd start khi spawn trực tiếp thất bại (PATH / quyền). */
function spawnWindowsCmdStart(bin, args) {
  return spawnDetached("cmd.exe", ["/c", "start", "", bin, ...args]);
}

async function runOsascript(script) {
  const { stdout } = await execFileAsync("osascript", ["-e", script]);
  return stdout.trim();
}

function buildWindowsChromeArgs(url) {
  const cleanUrl = String(url || "").trim();
  const flags = ["--no-first-run", "--no-default-browser-check"];
  if (USE_INCOGNITO) {
    // Trên Windows, truyền URL trực tiếp ổn định hơn --new-tab (Chrome tự mở tab mới).
    return [...flags, "--incognito", cleanUrl];
  }
  return [...flags, "--new-tab", cleanUrl];
}

async function spawnChrome(args) {
  const bin = chromeBinReady(resolveChromeBin());
  try {
    await spawnDetached(bin, args);
    return;
  } catch (err) {
    if (process.platform !== "win32") throw err;
    console.warn("Chrome spawn direct failed, retry cmd start:", err.message);
    await spawnWindowsCmdStart(bin, args);
  }
}

/** Mở tab mới trong cửa sổ Chrome đầu tiên (không tạo cửa sổ mới). */
async function openChromeTabDarwin(url, { incognito = false } = {}) {
  const theUrl = escapeAppleScript(url);
  const ensureWindow = incognito
    ? `
      set hasIncognito to false
      repeat with w in windows
        if mode of w is "incognito" then
          set hasIncognito to true
          exit repeat
        end if
      end repeat
      if hasIncognito is false then
        return "need_window"
      end if
    `
    : `
      if (count of windows) = 0 then
        make new window
      end if
    `;

  const openInWindow = incognito
    ? `
      repeat with w in windows
        if mode of w is "incognito" then
          tell w
            make new tab with properties {URL:"${theUrl}"}
            set active tab index to (count of tabs)
          end tell
          set index of w to 1
          activate
          return "opened"
        end if
      end repeat
    `
    : `
      tell window 1
        make new tab with properties {URL:"${theUrl}"}
        set active tab index to (count of tabs)
      end tell
      set index of window 1 to 1
      activate
    `;

  const script = `
    tell application "${CHROME_APP}"
      ${ensureWindow}
      ${openInWindow}
    end tell
  `;

  try {
    const result = await runOsascript(script);
    if (incognito && result === "need_window") {
      await spawnChrome([ "--incognito", url]);
      await new Promise((resolve) => setTimeout(resolve, 800));
      await openChromeTabDarwin(url, { incognito: true });
      return;
    }
    if (!incognito || result === "opened") return;
  } catch {
    /* fall through to CLI */
  }

  const args = incognito ? ["--incognito", "--new-tab", url] : ["--new-tab", url];
  await spawnChrome(args);
}

async function focusChromeTab(url) {
  if (process.platform !== "darwin") return "focused";

  const theUrl = escapeAppleScript(url);
  const script = `
    tell application "${CHROME_APP}"
      set theUrl to "${theUrl}"
      repeat with w in windows
        set ti to 1
        repeat with t in tabs of w
          set tabUrl to URL of t as text
          if tabUrl is theUrl or tabUrl starts with theUrl then
            set active tab index of w to ti
            set index of w to 1
            activate
            return "focused"
          end if
          set ti to ti + 1
        end repeat
      end repeat
    end tell
    return "missing"
  `;
  return runOsascript(script);
}

async function openChromeUrl(url) {
  const target = String(url || "").trim();
  if (!target) throw new Error("Missing url");

  if (process.platform === "darwin") {
    await openChromeTabDarwin(target, { incognito: USE_INCOGNITO });
    return;
  }

  if (process.platform === "win32") {
    await spawnChrome(buildWindowsChromeArgs(target));
    console.log(`Chrome opened (Windows): ${target.slice(0, 96)}${target.length > 96 ? "…" : ""}`);
    return;
  }

  const args = USE_INCOGNITO
    ? ["--incognito", "--new-tab", target]
    : ["--new-tab", target];
  await spawnChrome(args);
}

async function closeChromeTab(url) {
  if (process.platform !== "darwin") return;

  const theUrl = escapeAppleScript(url);
  const script = `
    tell application "${CHROME_APP}"
      set theUrl to "${theUrl}"
      repeat with w in windows
        set ti to (count of tabs of w)
        repeat with i from 1 to ti
          set t to tab i of w
          set tabUrl to URL of t as text
          if tabUrl is theUrl or tabUrl starts with theUrl then
            close t
            return "closed"
          end if
        end repeat
      end repeat
    end tell
  `;
  try {
    await runOsascript(script);
  } catch {
    /* tab may already be closed */
  }
}

module.exports = {
  CHROME_APP,
  resolveChromeBin,
  openChromeUrl,
  focusChromeTab,
  closeChromeTab,
};
