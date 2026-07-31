const { execFile } = require("child_process");
const { promisify } = require("util");

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

async function runOsascript(script) {
  const { stdout } = await execFileAsync("osascript", ["-e", script]);
  return stdout.trim();
}

async function focusChromeTab(url) {
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
      await execFileAsync(CHROME_BIN, ["--incognito", url]);
      return;
    }
    await execFileAsync("open", ["-a", CHROME_APP, url]);
    return;
  }
  await execFileAsync("xdg-open", [url]);
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
  openChromeUrl,
  focusChromeTab,
  closeChromeTab,
};
