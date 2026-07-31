from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from host.config import AppConfig, TikTokAccount, load_config
from host.device import DeviceManager
from host.flows.expressvpn import run_expressvpn_connect
from host.flows.tiktok_signup import run_tiktok_signup, submit_otp
from host.wda_client import WdaClient, WdaError


LogFn = Callable[[str], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued|running|waiting_otp|succeeded|failed|cancelled
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    account_index: int = 0
    otp_code: str = ""
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AutomationService:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path
        self.config: AppConfig = load_config(config_path)
        self.logs: list[str] = []
        self._log_lock = threading.Lock()
        self.device = DeviceManager(
            go_ios_path=self.config.device.go_ios_path,
            udid=self.config.device.udid,
            wda_port=self.config.device.wda_port,
            wda_bundle_id=self.config.device.wda_bundle_id,
            wda_testrunner_bundle_id=self.config.device.wda_testrunner_bundle_id,
            wda_xctestconfig=self.config.device.wda_xctestconfig,
            tunnel_userspace=self.config.device.tunnel_userspace,
            wda_ipa_path=self.config.device.wda_ipa_path,
            log=self.log,
        )
        self.wda: WdaClient | None = None
        self.jobs: dict[str, Job] = {}
        self._jobs_lock = threading.Lock()
        self._worker_thread: threading.Thread | None = None
        self._stop_worker = threading.Event()
        self._otp_events: dict[str, threading.Event] = {}
        self._data_dir = Path(__file__).resolve().parent.parent / "data"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._jobs_file = self._data_dir / "jobs.json"
        self._load_jobs()

    def log(self, message: str) -> None:
        line = f"{datetime.now().strftime('%H:%M:%S')} {message}"
        with self._log_lock:
            self.logs.append(line)
            if len(self.logs) > 2000:
                self.logs = self.logs[-1500:]
        print(line, flush=True)

    def reload_config(self) -> AppConfig:
        self.config = load_config(self.config_path)
        self.device.udid = self.config.device.udid
        self.device.wda_port = self.config.device.wda_port
        self.device.wda_bundle_id = self.config.device.wda_bundle_id
        self.device.wda_testrunner_bundle_id = self.config.device.wda_testrunner_bundle_id
        self.device.wda_xctestconfig = self.config.device.wda_xctestconfig
        self.device.tunnel_userspace = self.config.device.tunnel_userspace
        if self.config.device.wda_ipa_path:
            self.device.wda_ipa_path = Path(self.config.device.wda_ipa_path)
        if self.config.device.go_ios_path:
            self.device.binary = self.device._resolve_binary(self.config.device.go_ios_path)
        return self.config

    def _load_jobs(self) -> None:
        if not self._jobs_file.exists():
            return
        try:
            rows = json.loads(self._jobs_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            job = Job(
                id=str(row["id"]),
                kind=str(row.get("kind") or "full"),
                status=str(row.get("status") or "queued"),
                created_at=str(row.get("created_at") or _utc_now()),
                updated_at=str(row.get("updated_at") or _utc_now()),
                account_index=int(row.get("account_index") or 0),
                otp_code=str(row.get("otp_code") or ""),
                error=str(row.get("error") or ""),
                result=row.get("result") if isinstance(row.get("result"), dict) else {},
                logs=list(row.get("logs") or []),
            )
            # Don't auto-resume running jobs after restart.
            if job.status in {"running", "waiting_otp"}:
                job.status = "failed"
                job.error = "interrupted by host restart"
            self.jobs[job.id] = job

    def _save_jobs(self) -> None:
        rows = [job.to_dict() for job in self.jobs.values()]
        rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
        self._jobs_file.write_text(json.dumps(rows[:200], indent=2), encoding="utf-8")

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._jobs_lock:
            rows = [job.to_dict() for job in self.jobs.values()]
        rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
        return rows

    def get_job(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def create_job(self, kind: str = "full", account_index: int = 0) -> Job:
        kind = (kind or "full").strip().lower()
        if kind not in {"full", "expressvpn", "tiktok_signup"}:
            raise ValueError("kind must be full|expressvpn|tiktok_signup")
        job = Job(id=str(uuid.uuid4())[:8], kind=kind, account_index=account_index)
        with self._jobs_lock:
            self.jobs[job.id] = job
            self._save_jobs()
        self._otp_events[job.id] = threading.Event()
        self.log(f"[job:{job.id}] queued kind={kind} account_index={account_index}")
        self.ensure_worker()
        return job

    def cancel_job(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job.status in {"queued", "waiting_otp", "running"}:
            job.status = "cancelled"
            job.updated_at = _utc_now()
            job.error = "cancelled by operator"
            event = self._otp_events.get(job_id)
            if event:
                event.set()
            with self._jobs_lock:
                self._save_jobs()
        return job

    def submit_job_otp(self, job_id: str, code: str) -> Job:
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        code = (code or "").strip()
        if not code:
            raise ValueError("otp code is empty")
        job.otp_code = code
        job.updated_at = _utc_now()
        job.logs.append(f"OTP received ({len(code)} chars)")
        event = self._otp_events.get(job_id)
        if event:
            event.set()
        with self._jobs_lock:
            self._save_jobs()
        return job

    def ensure_worker(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_worker.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, name="job-worker", daemon=True)
        self._worker_thread.start()

    def stop_worker(self) -> None:
        self._stop_worker.set()

    def _worker_loop(self) -> None:
        self.log("[worker] started")
        while not self._stop_worker.is_set():
            job = self._next_queued_job()
            if not job:
                time.sleep(0.5)
                continue
            try:
                self._run_job(job)
            except Exception as exc:  # noqa: BLE001
                job.status = "failed"
                job.error = str(exc)
                job.updated_at = _utc_now()
                self.log(f"[job:{job.id}] failed: {exc}")
                with self._jobs_lock:
                    self._save_jobs()
        self.log("[worker] stopped")

    def _next_queued_job(self) -> Job | None:
        with self._jobs_lock:
            queued = [job for job in self.jobs.values() if job.status == "queued"]
        if not queued:
            return None
        queued.sort(key=lambda job: job.created_at)
        return queued[0]

    def _job_log(self, job: Job, message: str) -> None:
        line = message
        job.logs.append(line)
        if len(job.logs) > 400:
            job.logs = job.logs[-300:]
        self.log(f"[job:{job.id}] {line}")

    def bootstrap_device(self) -> dict[str, Any]:
        result = self.device.bootstrap(
            start_tunnel=True,
            start_wda=True,
            start_forward=True,
            install_ipa_if_missing=self.config.device.install_ipa_if_missing,
        )
        self.ensure_wda_session()
        return result

    def is_wda_healthy(self) -> bool:
        try:
            client = WdaClient(self.device.wda_url, timeout=1.5)
            client.status()
            client.close()
            return True
        except Exception:  # noqa: BLE001
            return False

    def ensure_wda_session(self, bundle_id: str | None = None) -> WdaClient:
        wda_url = self.device.wda_url
        if self.wda is None or self.wda.base_url != wda_url:
            if self.wda is not None:
                try:
                    self.wda.close()
                except Exception:  # noqa: BLE001
                    pass
            self.wda = WdaClient(wda_url, log=self.log)
        if not self.wda.session_id:
            self.log(f"[wda] creating session at {wda_url}")
            self.wda.create_session(bundle_id=bundle_id, ready_timeout_seconds=20)
        return self.wda

    def health(self) -> dict[str, Any]:
        wda_ok = False
        wda_error = ""
        try:
            client = WdaClient(self.device.wda_url, timeout=2.0)
            client.status()
            wda_ok = True
            client.close()
        except Exception as exc:  # noqa: BLE001
            wda_error = str(exc)
        return {
            "ok": wda_ok,
            "wda_ok": wda_ok,
            "wda_error": wda_error,
            "wda_url": self.device.wda_url,
            "device": self.device.status(),
            "device_error": "",
            "worker_alive": bool(self._worker_thread and self._worker_thread.is_alive()),
            "queued_jobs": sum(1 for job in self.jobs.values() if job.status == "queued"),
            "config": {
                "expressvpn_bundle_id": self.config.apps.expressvpn_bundle_id,
                "tiktok_bundle_id": self.config.apps.tiktok_bundle_id,
                "accounts": len(self.config.tiktok_signup.accounts),
                "signup_method": self.config.tiktok_signup.method,
                "launcher": "go-ios",
            },
        }

    def list_connected_phones(self, *, enrich: bool = True) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        selected = (self.device.udid or self.config.device.udid or "").strip()
        try:
            devices = self.device.list_devices(enrich=enrich)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(str(exc)) from exc

        if not selected and devices:
            selected = devices[0].udid

        for index, device in enumerate(devices, start=1):
            raw = device.raw or {}
            model = self.device.product_model_label(device.product_type)
            is_selected = bool(selected) and device.udid == selected
            rows.append(
                {
                    "slot": f"iphone-{index:02d}",
                    "udid": device.udid,
                    "name": device.name or str(raw.get("DeviceName") or "iPhone"),
                    "model": model,
                    "product_type": device.product_type,
                    "ios_version": device.version,
                    "phone_number": str(raw.get("PhoneNumber") or ""),
                    "serial": str(raw.get("SerialNumber") or ""),
                    "connected": True,
                    "selected": is_selected,
                    "wda_active": is_selected
                    and bool(self.device._wda_proc and self.device._wda_proc.poll() is None),
                    "password_protected": bool(raw.get("PasswordProtected")),
                }
            )
        return rows

    def select_device(self, udid: str, *, persist: bool = True) -> dict[str, Any]:
        udid = (udid or "").strip()
        if not udid:
            raise ValueError("udid is required")
        connected = {device.udid for device in self.device.list_devices(enrich=False)}
        if udid not in connected:
            raise ValueError(f"Device {udid} is not connected over USB")

        previous = self.device.udid
        if previous and previous != udid:
            self.log(f"[device] switching {previous} → {udid}; stopping previous WDA")
            self.device.stop_all()
            if self.wda is not None:
                try:
                    self.wda.close()
                except WdaError:
                    pass
                self.wda = None

        self.device.udid = udid
        self.config.device.udid = udid
        if persist:
            self._persist_udid(udid)
        self.log(f"[device] selected {udid}")
        return {
            "ok": True,
            "udid": udid,
            "persisted": persist,
            "phones": self.list_connected_phones(enrich=True),
        }

    def _persist_udid(self, udid: str) -> None:
        path = self.config_path
        if path is None:
            from host.config import DEFAULT_CONFIG_PATH, EXAMPLE_CONFIG_PATH

            path = DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH
        path = Path(path)
        if not path.exists():
            return
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                return
            device = data.get("device")
            if not isinstance(device, dict):
                device = {}
                data["device"] = device
            device["udid"] = udid
            path.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            self.log(f"[device] saved udid to {path}")
        except Exception as exc:  # noqa: BLE001
            self.log(f"[device] could not persist udid: {exc}")

    def _account_for_job(self, job: Job) -> TikTokAccount:
        accounts = self.config.tiktok_signup.accounts
        if not accounts:
            raise RuntimeError("No accounts configured in tiktok_signup.accounts")
        if job.account_index < 0 or job.account_index >= len(accounts):
            raise RuntimeError(f"account_index {job.account_index} out of range (0..{len(accounts)-1})")
        return accounts[job.account_index]

    def _run_job(self, job: Job) -> None:
        job.status = "running"
        job.updated_at = _utc_now()
        job.error = ""
        with self._jobs_lock:
            self._save_jobs()

        self._job_log(job, f"start kind={job.kind}")
        try:
            if not self.is_wda_healthy():
                self._job_log(job, "WDA offline — bootstrapping via go-ios (unlock iPhone)")
                self.device.bootstrap(
                    start_tunnel=True,
                    start_wda=True,
                    start_forward=True,
                    install_ipa_if_missing=self.config.device.install_ipa_if_missing,
                )
            else:
                self._job_log(job, f"WDA healthy at {self.device.wda_url}")

            wda = self.ensure_wda_session()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"WDA not ready: {exc}. "
                "Mở khóa iPhone → tab Quản lý điện thoại → Bootstrap, rồi chạy job lại."
            ) from exc

        shot_dir = self.config.screenshot_path / job.id
        shot_dir.mkdir(parents=True, exist_ok=True)
        result: dict[str, Any] = {}

        try:
            if job.kind in {"full", "expressvpn"}:
                vpn_result = run_expressvpn_connect(
                    wda,
                    self.config,
                    screenshot_dir=shot_dir,
                    log=lambda message: self._job_log(job, message),
                )
                result["expressvpn"] = vpn_result
                if not vpn_result.get("ok"):
                    raise RuntimeError(vpn_result.get("error") or "ExpressVPN flow failed")

            if job.kind in {"full", "tiktok_signup"}:
                account = self._account_for_job(job)
                # First pass without long OTP wait; if needs OTP, enter waiting state.
                signup_result = run_tiktok_signup(
                    wda,
                    self.config,
                    account,
                    otp_code=job.otp_code or None,
                    wait_for_otp=False,
                    screenshot_dir=shot_dir,
                    log=lambda message: self._job_log(job, message),
                )
                result["tiktok_signup"] = signup_result

                if signup_result.get("needs_otp") or (
                    signup_result.get("ok") is False and signup_result.get("step") == "otp"
                ):
                    # Move to waiting_otp and block until panel submits code or timeout.
                    job.status = "waiting_otp"
                    job.result = result
                    job.updated_at = _utc_now()
                    with self._jobs_lock:
                        self._save_jobs()
                    self._job_log(job, "waiting for OTP from panel")

                    event = self._otp_events.setdefault(job.id, threading.Event())
                    event.clear()
                    timed_out = not event.wait(timeout=self.config.tiktok_signup.otp_wait_seconds)
                    if job.status == "cancelled":
                        return
                    if timed_out and not job.otp_code:
                        raise RuntimeError("OTP wait timed out")
                    if not job.otp_code:
                        raise RuntimeError("OTP missing after wait")

                    otp_result = submit_otp(
                        wda,
                        job.otp_code,
                        self.config.tiktok_signup.continue_labels,
                    )
                    result["otp"] = otp_result
                    self._job_log(job, "OTP submitted")
                    # Continue username if needed by re-entering signup tail lightly.
                    if account.username:
                        time.sleep(1.0)
                        if wda.page_contains(["username", "tên người dùng", "Create username"]):
                            wda.fill_first_text_field(account.username)
                            wda.tap_labels(self.config.tiktok_signup.continue_labels, contains=True)
                    signup_result = {**signup_result, "ok": True, "otp_submitted": True, "needs_otp": False}
                    result["tiktok_signup"] = signup_result

                elif not signup_result.get("ok"):
                    raise RuntimeError(signup_result.get("error") or "TikTok signup flow failed")

            job.status = "succeeded"
            job.result = result
            job.updated_at = _utc_now()
            self._job_log(job, "succeeded")
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = str(exc)
            job.result = result
            job.updated_at = _utc_now()
            self._job_log(job, f"failed: {exc}")
        finally:
            with self._jobs_lock:
                self._save_jobs()

    def shutdown(self) -> None:
        self.stop_worker()
        if self.wda is not None:
            try:
                self.wda.close()
            except WdaError:
                pass
            self.wda = None
        self.device.stop_all()
