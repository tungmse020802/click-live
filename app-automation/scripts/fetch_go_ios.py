#!/usr/bin/env python3
"""Download go-ios binaries into app-automation/resources/bin/."""

from __future__ import annotations

import io
import platform
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
VERSION = "v1.0.143"
ASSETS = {
    "darwin": ("go-ios-mac.zip", "ios"),
    "windows": ("go-ios-win.zip", "ios.exe"),
    "linux": ("go-ios-linux.zip", "ios"),
}


def main() -> int:
    system = platform.system().lower()
    if system not in ASSETS:
        print(f"Unsupported OS: {system}", file=sys.stderr)
        return 1
    asset_name, binary_name = ASSETS[system]
    out_dir = ROOT / "resources" / "bin" / ("darwin" if system == "darwin" else system if system != "windows" else "windows")
    if system == "windows":
        out_dir = ROOT / "resources" / "bin" / "windows"
    elif system == "linux":
        out_dir = ROOT / "resources" / "bin" / "linux"
    else:
        out_dir = ROOT / "resources" / "bin" / "darwin"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / binary_name

    api = f"https://api.github.com/repos/danielpaulus/go-ios/releases/tags/{VERSION}"
    print(f"Fetching release {VERSION}…")
    with urlopen(Request(api, headers={"Accept": "application/vnd.github+json", "User-Agent": "app-automation"})) as resp:
        import json

        release = json.loads(resp.read().decode("utf-8"))
    assets = {row["name"]: row["browser_download_url"] for row in release.get("assets", [])}
    url = assets.get(asset_name)
    if not url:
        print(f"Asset not found: {asset_name}", file=sys.stderr)
        return 1
    print(f"Downloading {url}")
    with urlopen(Request(url, headers={"User-Agent": "app-automation"})) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        member = next((n for n in names if n.endswith(binary_name) or n.endswith("ios") or n.endswith("ios.exe")), None)
        if not member:
            print(f"Binary not in zip: {names}", file=sys.stderr)
            return 1
        with zf.open(member) as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out)
    dest.chmod(0o755)
    print(f"Installed {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
