from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from host.config import DEFAULT_CONFIG_PATH, EXAMPLE_CONFIG_PATH, ROOT, load_config
from host.service import AutomationService


class CreateJobBody(BaseModel):
    kind: str = Field(default="full", description="full|expressvpn|tiktok_signup")
    account_index: int = 0


class OtpBody(BaseModel):
    code: str


class OpenUrlBody(BaseModel):
    url: str
    bundle_id: str | None = None


class SelectDeviceBody(BaseModel):
    udid: str
    persist: bool = True


def create_app(config_path: Path | None = None) -> FastAPI:
    service = AutomationService(config_path=config_path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        service.log("[server] starting")
        service.ensure_worker()
        if service.config.device.auto_start_wda or service.config.device.auto_start_tunnel:
            try:
                service.bootstrap_device()
            except Exception as exc:  # noqa: BLE001
                service.log(f"[server] bootstrap deferred: {exc}")
        yield
        service.shutdown()

    app = FastAPI(title="App Automation Panel", version="0.1.0", lifespan=lifespan)
    app.state.service = service

    panel_dir = ROOT / "panel"
    captures_dir = ROOT / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(panel_dir / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return service.health()

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        cfg = service.config
        return {
            "server": cfg.server.model_dump(),
            "device": cfg.device.model_dump(),
            "apps": cfg.apps.model_dump(),
            "expressvpn": cfg.expressvpn.model_dump(),
            "tiktok_signup": {
                **cfg.tiktok_signup.model_dump(),
                "accounts": [
                    {
                        "email": account.email,
                        "phone": account.phone,
                        "username": account.username,
                        "password_set": bool(account.password),
                    }
                    for account in cfg.tiktok_signup.accounts
                ],
            },
            "automation": cfg.automation.model_dump(),
            "config_path": str(config_path or DEFAULT_CONFIG_PATH),
        }

    @app.post("/api/config/reload")
    def reload_config() -> dict[str, Any]:
        service.reload_config()
        return {"ok": True, "config": get_config()}

    @app.get("/api/logs")
    def logs(limit: int = 200) -> dict[str, Any]:
        limit = max(1, min(limit, 1000))
        return {"logs": service.logs[-limit:]}

    @app.get("/api/devices")
    def devices(enrich: bool = True) -> dict[str, Any]:
        try:
            phones = service.list_connected_phones(enrich=enrich)
            status = service.device.status()
            return {
                "ok": True,
                "count": len(phones),
                "selected_udid": status.get("udid") or service.config.device.udid,
                "wda_url": service.device.wda_url,
                "device_status": status,
                "phones": phones,
            }
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/devices/select")
    def select_device(body: SelectDeviceBody) -> dict[str, Any]:
        try:
            return service.select_device(body.udid, persist=body.persist)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/devices/{udid}/bootstrap")
    def bootstrap_device(udid: str) -> dict[str, Any]:
        try:
            service.select_device(udid, persist=True)
            return {"ok": True, **service.bootstrap_device()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/devices/{udid}/info")
    def device_info(udid: str) -> dict[str, Any]:
        try:
            info = service.device.device_info(udid=udid)
            return {"ok": True, "udid": udid, "info": info}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/apps")
    def apps() -> dict[str, Any]:
        try:
            return {"ok": True, "apps": service.device.list_apps()}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/device/bootstrap")
    def bootstrap() -> dict[str, Any]:
        try:
            return {"ok": True, **service.bootstrap_device()}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/device/install-wda")
    def install_wda() -> dict[str, Any]:
        try:
            return service.device.install_wda_ipa()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/device/stop")
    def stop_device() -> dict[str, Any]:
        service.device.stop_all()
        if service.wda is not None:
            service.wda.close()
            service.wda = None
        return {"ok": True}

    @app.post("/api/device/screenshot")
    def screenshot() -> dict[str, Any]:
        try:
            wda = service.ensure_wda_session()
            path = service.config.screenshot_path / "manual_latest.png"
            wda.save_screenshot(path)
            return {"ok": True, "path": str(path), "url": "/captures/manual_latest.png"}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/device/home")
    def home() -> dict[str, Any]:
        try:
            wda = service.ensure_wda_session()
            wda.home()
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/device/open-url")
    def open_url(body: OpenUrlBody) -> dict[str, Any]:
        try:
            wda = service.ensure_wda_session()
            wda.open_url(body.url, bundle_id=body.bundle_id)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": service.list_jobs()}

    @app.post("/api/jobs")
    def create_job(body: CreateJobBody) -> dict[str, Any]:
        try:
            job = service.create_job(kind=body.kind, account_index=body.account_index)
            return {"ok": True, "job": job.to_dict()}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = service.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return {"job": job.to_dict()}

    @app.post("/api/jobs/{job_id}/otp")
    def job_otp(job_id: str, body: OtpBody) -> dict[str, Any]:
        try:
            job = service.submit_job_otp(job_id, body.code)
            return {"ok": True, "job": job.to_dict()}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/cancel")
    def job_cancel(job_id: str) -> dict[str, Any]:
        try:
            job = service.cancel_job(job_id)
            return {"ok": True, "job": job.to_dict()}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc

    if panel_dir.exists():
        app.mount("/static", StaticFiles(directory=panel_dir), name="static")
    app.mount("/captures", StaticFiles(directory=captures_dir), name="captures")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="App Automation management server")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH),
        help="Path to config.yaml",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    cfg = load_config(config_path)
    host = args.host or cfg.server.host
    port = args.port or cfg.server.port

    app = create_app(config_path=config_path)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
