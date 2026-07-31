const { execFile, spawn } = require("child_process");
const { promisify } = require("util");
const fs = require("fs");
const os = require("os");
const path = require("path");

const execFileAsync = promisify(execFile);

const CHROME_APP = process.env.DESKTOP_CHROME_APP || "Google Chrome";
const CHROME_BIN =
  process.env.DESKTOP_CHROME_BIN ||
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
/** Incognito tránh localStorage app_link (TikTok @junb...) từ Chrome thường */
const USE_INCOGNITO = process.env.DESKTOP_CHROME_INCOGNITO !== "false";

const chromeSessionsByUrl = new Map();

function escapeAppleScript(value) {
  return String(value || "")
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"');
}

function urlSessionKey(url) {
  return String(url || "").trim().split("#")[0];
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

async function runOsascript(script) {
  const { stdout } = await execFileAsync("osascript", ["-e", script]);
  return stdout.trim();
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
  if (process.platform === "darwin") {
    if (USE_INCOGNITO) {
      await execFileAsync(resolveChromeBin(), ["--incognito", url]);
      return;
    }
    await execFileAsync("open", ["-a", CHROME_APP, url]);
    return;
  }

  if (process.platform === "win32") {
    const bin = resolveChromeBin();
    const profileDir = path.join(os.tmpdir(), `click-live-chrome-${Date.now()}`);
    fs.mkdirSync(profileDir, { recursive: true });
    const args = USE_INCOGNITO
      ? ["--incognito", `--user-data-dir=${profileDir}`, "--new-window", url]
      : ["--new-window", url];
    const child = spawn(bin, args, { detached: true, stdio: "ignore", windowsHide: true });
    child.unref();
    chromeSessionsByUrl.set(urlSessionKey(url), { pid: child.pid, profileDir });
    return;
  }

  await execFileAsync("xdg-open", [url]);
}

async function closeChromeTab(url) {
  if (process.platform === "win32") {
    const session = chromeSessionsByUrl.get(urlSessionKey(url));
    if (session?.pid) {
      try {
        await execFileAsync("taskkill", ["/PID", String(session.pid), "/T", "/F"]);
      } catch {
        /* tab may already be closed */
      }
      chromeSessionsByUrl.delete(urlSessionKey(url));
      if (session.profileDir) {
        try {
          fs.rmSync(session.profileDir, { recursive: true, force: true });
        } catch {
          /* ignore */
        }
      }
    }
    return;
  }

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
