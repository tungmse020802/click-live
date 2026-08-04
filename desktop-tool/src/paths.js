const { app } = require("electron");
const fs = require("fs");
const path = require("path");

function isPackaged() {
  return app.isPackaged;
}

/** .env: dev = desktop-tool/.env; bản đóng gói = cạnh .exe / cạnh thư mục .app */
function envFilePath() {
  if (!isPackaged()) {
    return path.join(__dirname, "..", ".env");
  }
  if (process.platform === "darwin") {
    return path.join(path.dirname(process.execPath), "..", "..", "..", ".env");
  }
  return path.join(path.dirname(process.execPath), ".env");
}

function windowsClickHelperPath() {
  if (isPackaged()) {
    return path.join(process.resourcesPath, "windows-click-helper.ps1");
  }
  return path.join(__dirname, "windows-click-helper.ps1");
}

function windowsClickNativeHelperPath() {
  if (isPackaged()) {
    return path.join(process.resourcesPath, "bin", "click-helper.exe");
  }
  const candidates = [
    path.join(__dirname, "..", "resources", "bin", "win32", "click-helper.exe"),
    path.join(__dirname, "..", "click-helper", "click-helper.exe"),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return candidates[0];
}

module.exports = {
  isPackaged,
  envFilePath,
  windowsClickHelperPath,
  windowsClickNativeHelperPath,
};
