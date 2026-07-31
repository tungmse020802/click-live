"""Immediate phone opens via queue poll (works abroad — no VPS→phone HTTP)."""

from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from phone_registry import device_click_point, list_devices, sync_lead_seconds

_lock = threading.Lock()
_pending_by_device: Dict[str, Deque[Dict[str, Any]]] = {}
_broadcast_seq = itertools.count(1)
_TTL_SECONDS = 120.0


def _device_queue(device_id: str) -> Deque[Dict[str, Any]]:
    key = str(device_id or "").strip() or "_anonymous"
    if key not in _pending_by_device:
        _pending_by_device[key] = deque(maxlen=64)
    return _pending_by_device[key]


def _job_dict(item: Dict[str, Any], device_id: str) -> Dict[str, Any]:
    x, y = device_click_point(
        device_id,
        int(item.get("click_x") or 0),
        int(item.get("click_y") or 0),
    )
    open_at = float(item.get("open_at") or 0)
    now = time.time()
    wait_ms = max(0, int((open_at - now) * 1000)) if open_at > 0 else 0
    click_after_ms = max(0, int(item.get("click_after_ms") or 0))
    return {
        "id": int(item["id"]),
        "url": item["url"],
        "time": item.get("time") or "",
        "click_after_ms": click_after_ms + wait_ms,
        "open_at": open_at,
        "click_x": x,
        "click_y": y,
        "device_id": device_id,
        "message": "",
        "payload": dict(item.get("payload") or {}),
        "sync_broadcast": True,
    }


def push_phone_open(
    *,
    url: str,
    queue_id: Optional[int] = None,
    time_label: str = "",
    click_after_ms: int = 0,
    click_x: int = 0,
    click_y: int = 0,
    device_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    text = str(url or "").strip()
    if not text:
        return {"ok": False, "error": "empty url"}

    open_at = time.time() + sync_lead_seconds()
    push_id = -(int(time.time() * 1000) + next(_broadcast_seq))
    base = {
        "id": push_id,
        "url": text,
        "time": str(time_label or ""),
        "click_after_ms": max(0, int(click_after_ms or 0)),
        "click_x": max(0, int(click_x or 0)),
        "click_y": max(0, int(click_y or 0)),
        "queue_id": int(queue_id) if queue_id is not None else 0,
        "open_at": open_at,
        "created_at": time.time(),
        "payload": {"source": "open_link_push", "queue_id": int(queue_id or 0)},
    }

    targets = [str(d).strip() for d in (device_ids or []) if str(d).strip()]
    if not targets:
        targets = [str(d.get("device_id") or "") for d in list_devices()]
        targets = [d for d in targets if d]

    delivered: List[str] = []
    with _lock:
        if targets:
            for device_id in targets:
                q = _device_queue(device_id)
                copy = dict(base)
                copy["payload"] = dict(base.get("payload") or {})
                q.append(copy)
                delivered.append(device_id)
        else:
            q = _device_queue("_anonymous")
            q.append(dict(base))
            delivered.append("_anonymous")

    return {
        "ok": True,
        "push_id": push_id,
        "url": text,
        "open_at": open_at,
        "devices": delivered,
        "broadcast": len(delivered) > 1 or (len(delivered) == 1 and delivered[0] != "_anonymous"),
    }


def pop_phone_open(device_id: str = "") -> Optional[Dict[str, Any]]:
    key = str(device_id or "").strip() or "_anonymous"
    with _lock:
        for queue_key in (key, "_anonymous"):
            q = _pending_by_device.get(queue_key)
            if not q:
                continue
            while q:
                item = q.popleft()
                if (time.time() - float(item.get("created_at") or 0)) > _TTL_SECONDS:
                    continue
                return _job_dict(item, key if queue_key != "_anonymous" else key)
    return None


def wait_phone_open(device_id: str, wait_seconds: float) -> Optional[Dict[str, Any]]:
    deadline = time.time() + max(0.0, float(wait_seconds))
    while time.time() < deadline:
        job = pop_phone_open(device_id)
        if job:
            return job
        time.sleep(0.25)
    return pop_phone_open(device_id)
