#!/usr/bin/env node
"use strict";

// Download go-ios prebuilt binaries for Windows (.exe) and macOS into
// resources/bin/<platform>/ so the Electron app can ship a fully bundled
// fleet without asking the user to install go-ios manually.
//
// Versions are pinned to keep installs reproducible. Update GO_IOS_VERSION
// when a new release fixes iOS support; the panel will pick up the new
// binary on the next install.

const fs = require("node:fs/promises");
const fsSync = require("node:fs");
const path = require("node:path");
const { pipeline } = require("node:stream/promises");
const { Readable } = require("node:stream");
const zlib = require("node:zlib");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");

const execFileAsync = promisify(execFile);

const GO_IOS_VERSION = process.env.GO_IOS_VERSION || "v1.0.143";
const TARGETS = [
  {
    platform: "windows",
    asset: "go-ios-win.zip",
    binaryName: "ios.exe",
  },
  {
    platform: "darwin",
    asset: `go-ios-mac.zip`,
    binaryName: "ios",
  },
  {
    platform: "linux",
    asset: `go-ios-linux.zip`,
    binaryName: "ios",
    optional: true,
  },
];

const ROOT = path.resolve(__dirname, "..");
const BIN_ROOT = path.join(ROOT, "resources", "bin");

async function fileExists(target) {
  try {
    await fs.access(target);
    return true;
  } catch {
    return false;
  }
}

async function fetchAsset(url, destPath) {
  console.log(`-> downloading ${url}`);
  const response = await fetch(url, { redirect: "follow" });
  if (!response.ok || !response.body) {
    throw new Error(`HTTP ${response.status} fetching ${url}`);
  }
  await fs.mkdir(path.dirname(destPath), { recursive: true });
  await pipeline(Readable.fromWeb(response.body), fsSync.createWriteStream(destPath));
}

async function releaseAssets() {
  const url = `https://api.github.com/repos/danielpaulus/go-ios/releases/tags/${GO_IOS_VERSION}`;
  const response = await fetch(url, {
    headers: { Accept: "application/vnd.github+json" },
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} fetching ${url}`);
  }
  const body = await response.json();
  return new Map((body.assets || []).map((asset) => [asset.name, asset.browser_download_url]));
}

async function unzip(zipPath, outDir) {
  await fs.mkdir(outDir, { recursive: true });
  if (process.platform === "win32") {
    const ps = `Expand-Archive -Path "${zipPath}" -DestinationPath "${outDir}" -Force`;
    await execFileAsync("powershell.exe", ["-NoProfile", "-Command", ps]);
  } else {
    await execFileAsync("unzip", ["-o", zipPath, "-d", outDir]);
  }
}

async function downloadTarget(target, assets) {
  const outDir = path.join(BIN_ROOT, target.platform);
  const binPath = path.join(outDir, target.binaryName);
  if (await fileExists(binPath)) {
    console.log(`go-ios already present at ${binPath}, skipping`);
    return;
  }
  const url = assets.get(target.asset)
    || `https://github.com/danielpaulus/go-ios/releases/download/${GO_IOS_VERSION}/${target.asset}`;
  const zipPath = path.join(outDir, target.asset);
  try {
    await fetchAsset(url, zipPath);
    await unzip(zipPath, outDir);
    if (process.platform !== "win32") {
      try { await fs.chmod(binPath, 0o755); } catch {}
    }
    await fs.unlink(zipPath).catch(() => {});
    console.log(`Installed ${target.platform} go-ios -> ${binPath}`);
  } catch (error) {
    if (target.optional) {
      console.warn(`(optional) ${target.platform} download failed: ${error.message}`);
    } else {
      throw error;
    }
  }
}

async function main() {
  await fs.mkdir(BIN_ROOT, { recursive: true });
  const assets = await releaseAssets();
  for (const target of TARGETS) {
    await downloadTarget(target, assets);
  }
  console.log("All required go-ios binaries ready under resources/bin/");
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
