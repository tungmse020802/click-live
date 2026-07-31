"""Registered phones + per-device job delivery for multi-phone sync."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_lock = threading.Lock()
_DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "phone_devices.json"


def _registry_path() -> Path:
    raw = os.environ.get("PHONE_DEVICES_FILE", "").strip()
    return Path(raw) if raw else _DEFAULT_PATH


def _load() -> Dict[str, Any]:
    path = _registry_path()
    if not path.exists():
        return {"devices": {}, "delivered": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"devices": {}, "delivered": {}}
    if not isinstance(data, dict):
        return {"devices": {}, "delivered": {}}
    data.setdefault("devices", {})
    data.setdefault("delivered", {})
    return data


def _save(data: Dict[str, Any]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def sync_broadcast_enabled() -> bool:
    return os.environ.get("PHONE_SYNC_BROADCAST", "true").strip().lower() in ("1", "true", "yes")


def sync_lead_seconds() -> float:
    try:
        return max(0.5, float(os.environ.get("PHONE_SYNC_LEAD_SECONDS", "2.5")))
    except ValueError:
        return 2.5


def register_device(
    device_id: str,
    *,
    label: str = "",
    click_x: int = 0,
    click_y: int = 0,
    screen_w: int = 0,
    screen_h: int = 0,
) -> Dict[str, Any]:
    device_id = str(device_id or "").strip()
    if not device_id:
        return {"ok": False, "error": "missing device_id"}

    with _lock:
        data = _load()
        devices = data.setdefault("devices", {})
        prev = devices.get(device_id) if isinstance(devices.get(device_id), dict) else {}
        entry = {
            "device_id": device_id,
            "label": str(label or prev.get("label") or device_id).strip(),
            "click_x": max(0, int(click_x or prev.get("click_x") or 0)),
            "click_y": max(0, int(click_y or prev.get("click_y") or 0)),
            "screen_w": max(0, int(screen_w or prev.get("screen_w") or 0)),
            "screen_h": max(0, int(screen_h or prev.get("screen_h") or 0)),
            "last_seen": time.time(),
        }
        devices[device_id] = entry
        _save(data)
        return {"ok": True, "device": entry, "sync_broadcast": sync_broadcast_enabled()}


def list_devices(*, active_within_seconds: float = 3600) -> List[Dict[str, Any]]:
    cutoff = time.time() - max(60.0, float(active_within_seconds))
    with _lock:
        data = _load()
        devices = data.get("devices") or {}
        out: List[Dict[str, Any]] = []
        if not isinstance(devices, dict):
            return out
        for entry in devices.values():
            if not isinstance(entry, dict):
                continue
            if float(entry.get("last_seen") or 0) >= cutoff:
                out.append(dict(entry))
        out.sort(key=lambda row: str(row.get("label") or row.get("device_id") or ""))
        return out


def device_click_point(device_id: str, fallback_x: int = 0, fallback_y: int = 0) -> tuple[int, int]:
    with _lock:
        data = _load()
        devices = data.get("devices") or {}
        entry = devices.get(device_id) if isinstance(devices, dict) else None
        if isinstance(entry, dict):
            x = int(entry.get("click_x") or 0)
            y = int(entry.get("click_y") or 0)
            if x > 0 and y > 0:
                return x, y
    return max(0, fallback_x), max(0, fallback_y)


def mark_job_delivered(device_id: str, job_id: int) -> None:
    if not device_id or job_id <= 0:
        return
    with _lock:
        data = _load()
        delivered = data.setdefault("delivered", {})
        key = str(device_id)
        rows = delivered.get(key) if isinstance(delivered.get(key), list) else []
        if job_id not in rows:
            rows.append(job_id)
            rows = rows[-200:]
        delivered[key] = rows
        _save(data)


def device_has_job(device_id: str, job_id: int) -> bool:
    with _lock:
        data = _load()
        delivered = data.get("delivered") or {}
        rows = delivered.get(device_id) if isinstance(delivered.get(device_id), list) else []
        return job_id in rows


def next_pending_job_for_device(device_id: str, after_id: int, db) -> Optional[Dict[str, Any]]:
    """Broadcast queue mode: every registered phone gets the same pending jobs."""
    from phone_jobs import phone_job_from_queue_item

    limit = 80
    items = db.get_queue_items(limit=limit, statuses=["pending"])
    if not items:
        return None
    items.sort(key=lambda row: int(row.get("id") or 0))
    for item in items:
        job_id = int(item.get("id") or 0)
        if job_id <= after_id:
            continue
        if device_has_job(device_id, job_id):
            continue
        job = phone_job_from_queue_item(item)
        if not job:
            mark_job_delivered(device_id, job_id)
            continue
        mark_job_delivered(device_id, job_id)
        x, y = device_click_point(device_id, int(job.get("click_x") or 0), int(job.get("click_y") or 0))
        job["click_x"] = x
        job["click_y"] = y
        job["device_id"] = device_id
        job["sync_broadcast"] = True
        job["open_at"] = time.time() + sync_lead_seconds()
        return job
    return None
