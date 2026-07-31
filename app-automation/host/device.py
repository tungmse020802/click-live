from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx


LogFn = Callable[[str], None]
ROOT = Path(__file__).resolve().parent.parent


def _default_log(message: str) -> None:
    print(message, flush=True)


@dataclass
class DeviceInfo:
    udid: str
    name: str = ""
    version: str = ""
    product_type: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class GoIosError(RuntimeError):
    pass


def bundled_go_ios_path() -> Path:
    system = platform.system().lower()
    if system == "darwin":
        return ROOT / "resources" / "bin" / "darwin" / "ios"
    if system == "windows":
        return ROOT / "resources" / "bin" / "windows" / "ios.exe"
    return ROOT / "resources" / "bin" / "linux" / "ios"


def default_wda_ipa_path() -> Path:
    return ROOT / "resources" / "ipa" / "WebDriverAgentRunner.ipa"


class DeviceManager:
    """Standalone iPhone control via bundled go-ios + WebDriverAgent HTTP.

    No Appium. No Xcode. No dependency on wda_control_panel / ios_wda_controller.
    """

    def __init__(
        self,
        go_ios_path: str = "",
        udid: str = "",
        wda_port: int = 8100,
        wda_bundle_id: str = "com.clicklive.WebDriverAgentRunner.xctrunner",
        wda_testrunner_bundle_id: str = "",
        wda_xctestconfig: str = "WebDriverAgentRunner.xctest",
        tunnel_userspace: bool = True,
        wda_ipa_path: str = "",
        log: LogFn | None = None,
    ) -> None:
        self.binary = self._resolve_binary(go_ios_path)
        self.udid = (udid or "").strip()
        self.wda_port = int(wda_port)
        self.wda_bundle_id = wda_bundle_id
        self.wda_testrunner_bundle_id = wda_testrunner_bundle_id or wda_bundle_id
        self.wda_xctestconfig = wda_xctestconfig
        self.tunnel_userspace = bool(tunnel_userspace)
        self.wda_ipa_path = Path(wda_ipa_path) if wda_ipa_path else default_wda_ipa_path()
        self.log = log or _default_log
        self._tunnel_proc: subprocess.Popen[str] | None = None
        self._wda_proc: subprocess.Popen[str] | None = None
        self._forward_proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self.discovered_wda_url: str = ""
        self.last_error: str = ""

    @property
    def wda_url(self) -> str:
        if self.discovered_wda_url:
            return self.discovered_wda_url.rstrip("/")
        return f"http://127.0.0.1:{self.wda_port}"

    @staticmethod
    def _resolve_binary(configured: str) -> str:
        candidates: list[str] = []
        if configured:
            candidates.append(configured)
        env = os.environ.get("GO_IOS_PATH", "").strip()
        if env:
            candidates.append(env)
        bundled = bundled_go_ios_path()
        if bundled.exists():
            candidates.append(str(bundled))
        which = shutil.which("ios") or shutil.which("ios.exe")
        if which:
            candidates.append(which)
        for path in candidates:
            if path and Path(path).exists():
                return str(Path(path).resolve())
        return str(bundled)

    def _base_cmd(self, *args: str, udid: str | None = None) -> list[str]:
        cmd = [self.binary, *args]
        target = (udid if udid is not None else self.udid).strip()
        if target:
            cmd.extend(["--udid", target])
        return cmd

    def run(
        self,
        *args: str,
        udid: str | None = None,
        timeout: float | None = 60,
        check: bool = True,
        quiet: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        cmd = self._base_cmd(*args, udid=udid)
        if not quiet:
            self.log(f"[go-ios] {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GoIosError(
                f"go-ios not found at {self.binary}. Run: python scripts/fetch_go_ios.py"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise GoIosError(f"go-ios timed out: {' '.join(cmd)}") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise GoIosError(f"go-ios failed ({result.returncode}): {detail or ' '.join(cmd)}")
        return result

    def list_devices(self, *, enrich: bool = False) -> list[DeviceInfo]:
        result = self.run("list", "--details", udid="", timeout=30, check=False, quiet=True)
        if result.returncode != 0 or not (result.stdout or "").strip():
            result = self.run("list", udid="", timeout=30, check=False, quiet=True)
        text = (result.stdout or "").strip()
        devices: list[DeviceInfo] = []
        if not text:
            return devices
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            for line in text.splitlines():
                token = line.strip().split()[0] if line.strip() else ""
                if len(token) >= 25:
                    devices.append(DeviceInfo(udid=token))
            return devices

        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get("deviceList") or payload.get("devices") or payload.get("list") or []
            if not rows and (payload.get("udid") or payload.get("Udid") or payload.get("UDID")):
                rows = [payload]
        else:
            rows = []

        for row in rows:
            if isinstance(row, str):
                devices.append(DeviceInfo(udid=row))
                continue
            if not isinstance(row, dict):
                continue
            udid = str(
                row.get("udid")
                or row.get("Udid")
                or row.get("UDID")
                or row.get("UniqueDeviceID")
                or ""
            ).strip()
            if not udid:
                continue
            devices.append(
                DeviceInfo(
                    udid=udid,
                    name=str(row.get("DeviceName") or row.get("name") or ""),
                    version=str(
                        row.get("ProductVersion")
                        or row.get("HumanReadableProductVersionString")
                        or row.get("version")
                        or ""
                    ),
                    product_type=str(row.get("ProductType") or row.get("productType") or ""),
                    raw=row,
                )
            )

        if enrich:
            for device in devices:
                try:
                    info = self.device_info(udid=device.udid)
                except Exception:  # noqa: BLE001
                    continue
                device.name = device.name or str(info.get("DeviceName") or "")
                device.version = device.version or str(
                    info.get("ProductVersion") or info.get("HumanReadableProductVersionString") or ""
                )
                device.product_type = device.product_type or str(info.get("ProductType") or "")
                device.raw = {**device.raw, **info}
        return devices

    def device_info(self, udid: str | None = None) -> dict[str, Any]:
        target = (udid or self.udid or "").strip()
        result = self.run("info", udid=target or None, timeout=45, check=False, quiet=True)
        text = (result.stdout or "").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}
        return payload if isinstance(payload, dict) else {"raw": payload}

    def product_model_label(self, product_type: str) -> str:
        mapping = {
            "iPhone12,1": "iPhone 11",
            "iPhone12,3": "iPhone 11 Pro",
            "iPhone12,5": "iPhone 11 Pro Max",
            "iPhone13,2": "iPhone 12",
            "iPhone13,3": "iPhone 12 Pro",
            "iPhone13,4": "iPhone 12 Pro Max",
            "iPhone14,5": "iPhone 13",
            "iPhone14,2": "iPhone 13 Pro",
            "iPhone14,3": "iPhone 13 Pro Max",
            "iPhone14,7": "iPhone 14",
            "iPhone15,2": "iPhone 14 Pro",
            "iPhone15,3": "iPhone 14 Pro Max",
            "iPhone15,4": "iPhone 15",
            "iPhone16,1": "iPhone 15 Pro",
            "iPhone16,2": "iPhone 15 Pro Max",
            "iPhone17,3": "iPhone 16",
            "iPhone17,1": "iPhone 16 Pro",
            "iPhone17,2": "iPhone 16 Pro Max",
        }
        return mapping.get(product_type, product_type or "iPhone")

    def ensure_udid(self) -> str:
        if self.udid:
            return self.udid
        devices = self.list_devices()
        if not devices:
            raise GoIosError("No iPhone found over USB. Plug in, unlock, and Trust this computer.")
        self.udid = devices[0].udid
        self.log(f"[device] using first USB device {self.udid}")
        return self.udid

    def list_apps(self) -> list[dict[str, Any]]:
        self.ensure_udid()
        result = self.run("apps", "--all", timeout=90, check=False)
        text = (result.stdout or "").strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            apps = []
            for line in text.splitlines():
                parts = line.split()
                if parts:
                    apps.append({"bundleId": parts[0], "raw": line})
            return apps
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            rows = payload.get("apps") or payload.get("list") or []
            return [row for row in rows if isinstance(row, dict)]
        return []

    def has_wda_installed(self) -> bool:
        needle = (self.wda_bundle_id or "").lower()
        if not needle:
            return False
        for app in self.list_apps():
            bid = str(
                app.get("bundleId")
                or app.get("BundleIdentifier")
                or app.get("CFBundleIdentifier")
                or app.get("identifier")
                or ""
            ).lower()
            if bid == needle or needle in bid:
                return True
        return False

    def install_wda_ipa(self, ipa_path: Path | None = None) -> dict[str, Any]:
        self.ensure_udid()
        path = Path(ipa_path) if ipa_path else self.wda_ipa_path
        if not path.exists():
            raise GoIosError(
                f"WDA IPA not found: {path}. Place a signed WebDriverAgentRunner.ipa in resources/ipa/"
            )
        self.log(f"[device] installing WDA IPA {path}")
        self.run("install", f"--path={path}", timeout=180)
        return {"ok": True, "ipa": str(path), "udid": self.udid, "bundle_id": self.wda_bundle_id}

    def launch_app(self, bundle_id: str) -> None:
        self.ensure_udid()
        self.run("launch", bundle_id, timeout=45)

    def kill_app(self, bundle_id: str) -> None:
        self.ensure_udid()
        self.run("kill", bundle_id, timeout=30, check=False)

    def _spawn(self, *args: str, udid: str | None = None) -> subprocess.Popen[str]:
        cmd = self._base_cmd(*args, udid=udid)
        self.log(f"[go-ios:spawn] {' '.join(cmd)}")
        try:
            return subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise GoIosError(
                f"go-ios not found at {self.binary}. Run: python scripts/fetch_go_ios.py"
            ) from exc

    def _pipe_logs(self, proc: subprocess.Popen[str], prefix: str) -> None:
        def _reader() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                text = line.rstrip()
                if text:
                    self.log(f"[{prefix}] {text}")
                    lower = text.lower()
                    if "not trusted" in lower or "0xe8008011" in lower or "expired" in lower:
                        self.last_error = text

        threading.Thread(target=_reader, daemon=True).start()

    def start_tunnel(self) -> None:
        with self._lock:
            if self._tunnel_proc and self._tunnel_proc.poll() is None:
                return
            args = ["tunnel", "start"]
            if self.tunnel_userspace:
                args.append("--userspace")
                self.log("[device] starting userspace tunnel (no sudo)")
            else:
                self.log("[device] starting privileged tunnel (needs sudo/admin)")
            self._tunnel_proc = self._spawn(*args, udid="")
            self._pipe_logs(self._tunnel_proc, "tunnel")

        deadline = time.time() + 5.0
        while time.time() < deadline:
            if self._tunnel_proc.poll() is not None:
                hint = (
                    "Tunnel exited. Keep device.tunnel_userspace=true, or run in another terminal:\n"
                    "  sudo ./resources/bin/darwin/ios tunnel start\n"
                    "then set auto_start_tunnel=false."
                )
                self.last_error = hint
                raise GoIosError(hint)
            time.sleep(0.3)
        self.log("[device] tunnel process is up")

    def start_wda(self) -> None:
        self.ensure_udid()
        if not self.wda_bundle_id:
            raise GoIosError("wda_bundle_id is required")
        with self._lock:
            if self._wda_proc and self._wda_proc.poll() is None:
                return
            self._wda_proc = self._spawn(
                "runwda",
                f"--bundleid={self.wda_bundle_id}",
                f"--testrunnerbundleid={self.wda_testrunner_bundle_id}",
                f"--xctestconfig={self.wda_xctestconfig}",
            )
            self._pipe_logs(self._wda_proc, "runwda")
        time.sleep(1.2)
        if self._wda_proc and self._wda_proc.poll() is not None:
            detail = self.last_error or "runwda exited immediately"
            raise GoIosError(
                f"{detail}. "
                "Checklist: Trust developer on iPhone, Developer Mode ON, WDA IPA installed, tunnel running."
            )

    def start_forward(self, device_port: int = 8100) -> None:
        self.ensure_udid()
        with self._lock:
            if self._forward_proc and self._forward_proc.poll() is None:
                return
            self._forward_proc = self._spawn("forward", str(self.wda_port), str(device_port))
            self._pipe_logs(self._forward_proc, "forward")
            time.sleep(0.7)

    def wait_wda_http(self, url: str | None = None, timeout_seconds: float = 60.0) -> str:
        target = (url or self.wda_url).rstrip("/")
        deadline = time.time() + timeout_seconds
        last_error = ""
        while time.time() < deadline:
            if self._wda_proc and self._wda_proc.poll() is not None:
                raise GoIosError(
                    self.last_error
                    or "runwda died while waiting for /status. Trust developer certificate on iPhone."
                )
            try:
                response = httpx.get(f"{target}/status", timeout=1.5)
                if response.status_code < 500:
                    self.log(f"[device] WDA healthy at {target}")
                    self.discovered_wda_url = target
                    return target
                last_error = f"HTTP {response.status_code}"
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
            time.sleep(0.5)
        raise GoIosError(f"WDA not healthy at {target}: {last_error or self.last_error}")

    def stop_all(self) -> None:
        with self._lock:
            for name, proc in (
                ("forward", self._forward_proc),
                ("runwda", self._wda_proc),
                ("tunnel", self._tunnel_proc),
            ):
                if proc and proc.poll() is None:
                    self.log(f"[device] stopping {name}")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            self._forward_proc = None
            self._wda_proc = None
            self._tunnel_proc = None
            self.discovered_wda_url = ""

    def bootstrap(
        self,
        *,
        start_tunnel: bool = True,
        start_wda: bool = True,
        start_forward: bool = True,
        install_ipa_if_missing: bool = True,
    ) -> dict[str, Any]:
        udid = self.ensure_udid()
        self.last_error = ""
        self.log("[device] bootstrap via go-ios only")

        if not Path(self.binary).exists():
            raise GoIosError(
                f"go-ios binary missing: {self.binary}. Run: python scripts/fetch_go_ios.py"
            )

        if install_ipa_if_missing:
            try:
                installed = self.has_wda_installed()
            except Exception as exc:  # noqa: BLE001
                self.log(f"[device] apps check skipped: {exc}")
                installed = False
            if not installed:
                self.log("[device] WDA not installed — installing IPA")
                self.install_wda_ipa()

        if start_tunnel:
            self.start_tunnel()
        if start_wda:
            self.start_wda()
        if start_forward:
            self.start_forward(device_port=8100)

        healthy_url = self.wait_wda_http(f"http://127.0.0.1:{self.wda_port}", timeout_seconds=75)
        return {
            "udid": udid,
            "launcher": "go-ios",
            "wda_url": healthy_url,
            "binary": self.binary,
            "ipa": str(self.wda_ipa_path),
            "tunnel_userspace": self.tunnel_userspace,
            "tunnel_running": bool(self._tunnel_proc and self._tunnel_proc.poll() is None),
            "wda_running": bool(self._wda_proc and self._wda_proc.poll() is None),
            "forward_running": bool(self._forward_proc and self._forward_proc.poll() is None),
        }

    def status(self) -> dict[str, Any]:
        return {
            "binary": self.binary,
            "binary_exists": Path(self.binary).exists(),
            "udid": self.udid,
            "wda_port": self.wda_port,
            "wda_url": self.wda_url,
            "launcher": "go-ios",
            "ipa": str(self.wda_ipa_path),
            "ipa_exists": self.wda_ipa_path.exists(),
            "tunnel_userspace": self.tunnel_userspace,
            "tunnel_running": bool(self._tunnel_proc and self._tunnel_proc.poll() is None),
            "wda_running": bool(self._wda_proc and self._wda_proc.poll() is None),
            "forward_running": bool(self._forward_proc and self._forward_proc.poll() is None),
            "last_error": self.last_error,
        }
