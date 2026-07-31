"""Immediate phone opens via queue poll (works abroad — no VPS→phone HTTP)."""

from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Optional

_lock = threading.Lock()
_pending: Deque[Dict[str, Any]] = deque(maxlen=256)
_seq = itertools.count(1)
_TTL_SECONDS = 120.0


def push_phone_open(
    *,
    url: str,
    queue_id: Optional[int] = None,
    time_label: str = "",
    click_after_ms: int = 0,
    click_x: int = 0,
    click_y: int = 0,
) -> Dict[str, Any]:
    text = str(url or "").strip()
    if not text:
        return {"ok": False, "error": "empty url"}

    push_id = -(int(time.time() * 1000) + next(_seq))
    item = {
        "id": push_id,
        "url": text,
        "time": str(time_label or ""),
        "click_after_ms": max(0, int(click_after_ms or 0)),
        "click_x": max(0, int(click_x or 0)),
        "click_y": max(0, int(click_y or 0)),
        "queue_id": int(queue_id) if queue_id is not None else 0,
        "created_at": time.time(),
    }
    with _lock:
        _pending.append(item)
    return {"ok": True, "push_id": push_id, "url": text}


def _expired(created_at: float) -> bool:
    return (time.time() - float(created_at)) > _TTL_SECONDS


def pop_phone_open(device_id: str = "") -> Optional[Dict[str, Any]]:
    del device_id  # broadcast — any polling phone may claim
    with _lock:
        while _pending:
            item = _pending.popleft()
            if _expired(item.get("created_at", 0)):
                continue
            return {
                "id": item["id"],
                "url": item["url"],
                "time": item.get("time") or "",
                "click_after_ms": item.get("click_after_ms") or 0,
                "click_x": item.get("click_x") or 0,
                "click_y": item.get("click_y") or 0,
                "message": "",
                "payload": {"source": "open_link_push", "queue_id": item.get("queue_id") or 0},
            }
    return None


def wait_phone_open(device_id: str, wait_seconds: float) -> Optional[Dict[str, Any]]:
    deadline = time.time() + max(0.0, float(wait_seconds))
    while time.time() < deadline:
        job = pop_phone_open(device_id)
        if job:
            return job
        time.sleep(0.25)
    return pop_phone_open(device_id)
