const { app } = require("electron");
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

module.exports = {
  isPackaged,
  envFilePath,
  windowsClickHelperPath,
};
