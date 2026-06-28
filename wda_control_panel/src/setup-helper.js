"use strict";

const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const { spawn } = require("node:child_process");
const { shell } = require("electron");
const {
  resolveGoIosPath,
  resolveIpaPath,
  resolveWdaProjectPath,
  resolveDerivedDataPath,
  pathExists,
} = require("./paths");

const APPLE_ITUNES_DOWNLOAD_URL = "https://www.apple.com/itunes/download/win64";

function run(command, args, options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env,
      shell: process.platform === "win32",
    });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk) => { stdout += chunk; });
    child.stderr?.on("data", (chunk) => { stderr += chunk; });
    child.on("error", (error) => resolve({ ok: false, stdout, stderr: error.message, code: -1 }));
    child.on("close", (code) => resolve({ ok: code === 0, stdout, stderr, code }));
  });
}

function parseJson(text, fallback) {
  try { return JSON.parse(text); } catch { return fallback; }
}

async function checkAppleMobileDeviceService() {
  if (process.platform !== "win32") {
    return { ok: true, detail: "Apple Mobile Device driver check is Windows-only" };
  }
  const result = await run("sc", ["query", "Apple Mobile Device Service"]);
  if (!result.ok) {
    return {
      ok: false,
      detail: "Apple Mobile Device Service not installed. Install iTunes from apple.com, not Microsoft Store.",
      installUrl: APPLE_ITUNES_DOWNLOAD_URL,
    };
  }
  const running = /STATE\s*:\s*\d+\s+RUNNING/i.test(result.stdout);
  return {
    ok: running,
    detail: running
      ? "Apple Mobile Device Service is running"
      : "Apple Mobile Device Service exists but is not running. Open services.msc and start it.",
    installUrl: APPLE_ITUNES_DOWNLOAD_URL,
  };
}

async function openDriverDownload() {
  await shell.openExternal(APPLE_ITUNES_DOWNLOAD_URL);
  return { ok: true };
}

async function checkGoIos(config = {}) {
  const bin = resolveGoIosPath(config);
  const result = await run(bin, ["--version"]);
  return {
    ok: result.ok,
    path: bin,
    detail: result.ok ? (result.stdout || result.stderr).trim() : result.stderr || result.stdout,
  };
}

async function checkBundledIpa(config = {}) {
  const ipaPath = resolveIpaPath(config);
  return {
    ok: pathExists(ipaPath),
    path: ipaPath,
    detail: pathExists(ipaPath)
      ? "WebDriverAgentRunner.ipa is present"
      : `Missing IPA at ${ipaPath}. Copy the Mac build output here before packaging.`,
  };
}

async function installWdaIpa(device, config = {}) {
  if (!device?.udid) throw new Error("device.udid is required");
  const ipaPath = resolveIpaPath(config);
  if (!pathExists(ipaPath)) throw new Error(`WDA IPA is missing: ${ipaPath}`);
  const bin = resolveGoIosPath(config);
  const args = ["install", "--path", ipaPath, `--udid=${device.udid}`];
  const result = await run(bin, args);
  if (!result.ok) {
    throw new Error(result.stderr || result.stdout || `ios install exited ${result.code}`);
  }
  return {
    ok: true,
    udid: device.udid,
    stdout: result.stdout,
    stderr: result.stderr,
  };
}

async function listInstalledApps(device, config = {}) {
  if (!device?.udid) throw new Error("device.udid is required");
  const bin = resolveGoIosPath(config);
  const result = await run(bin, ["apps", `--udid=${device.udid}`]);
  if (!result.ok) {
    return { ok: false, apps: [], detail: result.stderr || result.stdout };
  }
  const apps = parseApps(result.stdout);
  return { ok: true, apps, detail: `${apps.length} app(s)` };
}

function parseApps(output) {
  const lines = String(output).split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const payloads = lines
    .filter((line) => line.startsWith("{") || line.startsWith("["))
    .map((line) => parseJson(line, null))
    .filter(Boolean);
  const data = payloads.find(Array.isArray)
    || payloads.find((entry) => Array.isArray(entry?.apps));
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.apps)) return data.apps;
  return lines
    .filter((line) => !line.startsWith("{") && !line.startsWith("["))
    .map((line) => ({ bundleId: line.split(/\s+/)[0] }));
}

function hasWdaInstalled(apps, bundleId) {
  const needle = bundleId || "com.facebook.WebDriverAgentRunner.xctrunner";
  return apps.some((app) => {
    const value = app.bundleId || app.BundleIdentifier || app.CFBundleIdentifier || app.identifier || String(app);
    return value === needle || String(value).includes("WebDriverAgentRunner");
  });
}

async function checkXcode() {
  if (process.platform !== "darwin") {
    return { ok: false, detail: "Xcode is macOS-only" };
  }
  const result = await runCollect("xcodebuild", ["-version"]);
  if (!result.ok) {
    return { ok: false, detail: result.stderr || result.stdout || "xcodebuild not found" };
  }
  return { ok: true, detail: result.stdout.split(/\r?\n/)[0] };
}

async function checkWdaProject(config = {}) {
  const projectPath = resolveWdaProjectPath(config);
  return {
    ok: pathExists(projectPath),
    path: projectPath,
    detail: pathExists(projectPath)
      ? `Found WebDriverAgent.xcodeproj at ${projectPath}`
      : `Missing project. Run \`npm install\` inside ios_wda_controller, or set Settings → WDA project path.`,
  };
}

async function detectSigningIdentities() {
  if (process.platform !== "darwin") return { ok: false, identities: [], detail: "macOS only" };
  const result = await runCollect("security", ["find-identity", "-v", "-p", "codesigning"]);
  if (!result.ok) return { ok: false, identities: [], detail: result.stderr };
  const identities = [];
  for (const line of result.stdout.split(/\r?\n/)) {
    const match = line.match(/^\s*\d+\)\s+([A-F0-9]{40})\s+"([^"]+)"/);
    if (!match) continue;
    const fullName = match[2];
    const teamMatch = fullName.match(/\(([A-Z0-9]{10})\)/);
    identities.push({
      hash: match[1],
      name: fullName,
      teamId: teamMatch ? teamMatch[1] : "",
    });
  }
  return { ok: true, identities, detail: `${identities.length} identity(ies)` };
}

async function buildWdaIpa(options = {}) {
  if (process.platform !== "darwin") throw new Error("buildWdaIpa is macOS-only");
  const projectPath = resolveWdaProjectPath(options);
  if (!pathExists(projectPath)) throw new Error(`WebDriverAgent project missing: ${projectPath}`);
  const teamId = options.appleTeamId;
  if (!teamId) throw new Error("appleTeamId is required to sign the IPA");
  const outDir = options.outDir || path.join(os.tmpdir(), "wda-ipa-build");
  const derivedDataPath = resolveDerivedDataPath(options);
  await fs.mkdir(outDir, { recursive: true });
  await fs.mkdir(derivedDataPath, { recursive: true });
  const archivePath = path.join(outDir, "WebDriverAgent.xcarchive");
  const exportDir = path.join(outDir, "export");
  const exportOptionsPath = path.join(outDir, "exportOptions.plist");
  const onProgress = options.onProgress || (() => {});

  // Reset stale build artifacts so signing identity changes always take effect.
  await fs.rm(archivePath, { recursive: true, force: true });
  await fs.rm(exportDir, { recursive: true, force: true });

  await fs.writeFile(exportOptionsPath, exportOptionsPlist(teamId), "utf8");

  // Step 1: build-for-testing so xcodebuild test-without-building can launch
  // WDA later from the same DerivedData. We do this BEFORE archive so the
  // resulting xctestrun matches the signed IPA bundle.
  onProgress("build-for-testing", "running");
  await runStreaming("xcodebuild", [
    "-project", projectPath,
    "-scheme", "WebDriverAgentRunner",
    "-destination", "generic/platform=iOS",
    "-derivedDataPath", derivedDataPath,
    "CODE_SIGN_STYLE=Automatic",
    `DEVELOPMENT_TEAM=${teamId}`,
    "build-for-testing",
  ], onProgress);

  onProgress("archive", "running");
  await runStreaming("xcodebuild", [
    "-project", projectPath,
    "-scheme", "WebDriverAgentRunner",
    "-configuration", options.configuration || "Release",
    "-destination", "generic/platform=iOS",
    "-archivePath", archivePath,
    "-derivedDataPath", derivedDataPath,
    "CODE_SIGN_STYLE=Automatic",
    `DEVELOPMENT_TEAM=${teamId}`,
    "archive",
  ], onProgress);

  onProgress("export", "running");
  await runStreaming("xcodebuild", [
    "-exportArchive",
    "-archivePath", archivePath,
    "-exportPath", exportDir,
    "-exportOptionsPlist", exportOptionsPath,
  ], onProgress);

  const exportedFiles = await fs.readdir(exportDir);
  const ipa = exportedFiles.find((file) => file.endsWith(".ipa"));
  if (!ipa) throw new Error(`Export finished but no .ipa was produced inside ${exportDir}`);
  const sourcePath = path.join(exportDir, ipa);
  const finalDir = options.copyTo || path.join(path.resolve(__dirname, ".."), "resources", "ipa");
  await fs.mkdir(finalDir, { recursive: true });
  const finalPath = path.join(finalDir, "WebDriverAgentRunner.ipa");
  await fs.copyFile(sourcePath, finalPath);
  onProgress("done", "ok");
  return { ipaPath: finalPath, archivePath, exportDir, derivedDataPath };
}

async function scanCoreDevices() {
  if (process.platform !== "darwin") {
    return { ok: false, devices: [], detail: "scanCoreDevices is macOS-only" };
  }
  const tmpJson = path.join(os.tmpdir(), `devicectl-list-${process.pid}.json`);
  const result = await runCollect("xcrun", ["devicectl", "list", "devices", "--json-output", tmpJson]);
  if (!result.ok) {
    return { ok: false, devices: [], detail: result.stderr || result.stdout };
  }
  let payload;
  try {
    const text = await fs.readFile(tmpJson, "utf8");
    payload = JSON.parse(text);
  } catch (error) {
    return { ok: false, devices: [], detail: `Cannot parse devicectl JSON: ${error.message}` };
  } finally {
    fs.unlink(tmpJson).catch(() => {});
  }
  const rows = (payload?.result?.devices || [])
    .filter((entry) => /iPhone|iPad/i.test(entry?.hardwareProperties?.deviceType || ""))
    .map((entry) => {
      const hw = entry.hardwareProperties || {};
      const props = entry.deviceProperties || {};
      const conn = entry.connectionProperties || {};
      const pairing = conn.pairingState || "unknown";
      const tunnelState = conn.tunnelState || "unknown";
      const status = tunnelState === "unavailable"
        ? "unavailable"
        : (pairing === "paired" ? "connected" : pairing);
      return {
        udid: hw.udid || entry.identifier || "",
        identifier: entry.identifier || "",
        name: props.name || hw.deviceType || "iPhone",
        version: props.osVersionNumber || "",
        productType: hw.productType || "",
        developerMode: props.developerModeStatus || "unknown",
        pairing,
        tunnelState,
        status,
      };
    })
    .filter((entry) => entry.udid);
  return { ok: true, devices: rows, detail: `${rows.length} device(s)` };
}

async function installViaDevicectl(device, ipaPath, options = {}) {
  if (process.platform !== "darwin") throw new Error("installViaDevicectl is macOS-only");
  if (!device?.udid) throw new Error("device.udid is required");
  if (!pathExists(ipaPath)) throw new Error(`IPA not found: ${ipaPath}`);
  const args = [
    "devicectl",
    "device",
    "install",
    "app",
    "--device", device.udid,
    ipaPath,
  ];
  const onProgress = options.onProgress || (() => {});
  await runStreaming("xcrun", args, onProgress);
  return { ok: true, udid: device.udid, ipaPath };
}

async function launchAppViaDevicectl(device, bundleId, options = {}) {
  if (process.platform !== "darwin") throw new Error("launchAppViaDevicectl is macOS-only");
  if (!device?.udid) throw new Error("device.udid is required");
  if (!bundleId) throw new Error("bundleId is required");
  const args = [
    "devicectl",
    "device",
    "process",
    "launch",
    "--device", device.udid,
    bundleId,
  ];
  if (options.environmentArgs) {
    for (const [key, value] of Object.entries(options.environmentArgs)) {
      args.push("--environment-variables", `${key}=${value}`);
    }
  }
  const result = await runCollect("xcrun", args);
  if (!result.ok) {
    throw new Error(result.stderr || result.stdout || "devicectl launch failed");
  }
  return { ok: true, stdout: result.stdout };
}

function exportOptionsPlist(teamId) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key>
  <string>development</string>
  <key>teamID</key>
  <string>${teamId}</string>
  <key>signingStyle</key>
  <string>automatic</string>
  <key>compileBitcode</key>
  <false/>
  <key>stripSwiftSymbols</key>
  <true/>
  <key>thinning</key>
  <string>&lt;none&gt;</string>
</dict>
</plist>
`;
}

function runCollect(command, args, options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env,
      shell: process.platform === "win32",
    });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk) => { stdout += chunk; });
    child.stderr?.on("data", (chunk) => { stderr += chunk; });
    child.on("error", (error) => resolve({ ok: false, stdout, stderr: error.message, code: -1 }));
    child.on("close", (code) => resolve({ ok: code === 0, stdout, stderr, code }));
  });
}

function runStreaming(command, args, onProgress) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] });
    let lastLine = "";
    const handle = (chunk) => {
      const text = String(chunk);
      lastLine = text.split(/\r?\n/).filter((line) => line.trim()).slice(-1)[0] || lastLine;
      onProgress?.(command, lastLine);
    };
    child.stdout.on("data", handle);
    child.stderr.on("data", handle);
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${command} ${args[0] || ""} exited ${code} (${lastLine || "no output"})`));
    });
  });
}

module.exports = {
  APPLE_ITUNES_DOWNLOAD_URL,
  checkAppleMobileDeviceService,
  openDriverDownload,
  checkGoIos,
  checkBundledIpa,
  installWdaIpa,
  listInstalledApps,
  hasWdaInstalled,
  checkXcode,
  checkWdaProject,
  detectSigningIdentities,
  buildWdaIpa,
  scanCoreDevices,
  installViaDevicectl,
  launchAppViaDevicectl,
};
