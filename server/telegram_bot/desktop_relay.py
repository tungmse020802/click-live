"""Relay mở countdown: queue UI (mọi thiết bị) → desktop-tool (một máy). Dedup theo URL."""

from __future__ import annotations

import html as html_module
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

_lock = threading.Lock()
_pending: List[Dict[str, Any]] = []
_opened_urls: Dict[str, float] = {}
_last_desktop_ping: float = 0.0

PENDING_MAX = 32
DEFAULT_DEDUP_SECONDS = 90
DEFAULT_ONLINE_SECONDS = 20


def normalize_open_url(url: str) -> str:
    text = html_module.unescape(str(url or "").strip())
    if not text:
        return ""
    try:
        parsed = urlparse(text)
        query = parse_qs(parsed.query)
        if "r" in query and query["r"]:
            r = query["r"][0]
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?r={r}"
        if "data" in query and query["data"]:
            data = query["data"][0]
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?data={data}"
        if "room_id" in query and query["room_id"]:
            room_id = query["room_id"][0]
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?room_id={room_id}"
    except Exception:
        pass
    return text


def _purge_old(now: float, dedup_seconds: int) -> None:
    cutoff = now - dedup_seconds
    stale = [key for key, opened_at in _opened_urls.items() if opened_at < cutoff]
    for key in stale:
        _opened_urls.pop(key, None)
    while len(_pending) > PENDING_MAX:
        _pending.pop(0)


def enqueue_open(
    url: str,
    *,
    job_id: Optional[int] = None,
    ttl_seconds: int = 30,
    dedup_seconds: int = DEFAULT_DEDUP_SECONDS,
    click_after_ms: int = 0,
    time_label: str = "",
) -> Dict[str, Any]:
    target = html_module.unescape(str(url or "").strip())
    if not target.startswith("http://") and not target.startswith("https://"):
        return {"ok": False, "error": "Invalid url"}

    key = normalize_open_url(target)
    now = time.time()
    with _lock:
        _purge_old(now, dedup_seconds)
        if key in _opened_urls:
            return {
                "ok": True,
                "deduplicated": True,
                "reason": "already_opened",
                "url": target,
            }
        for item in _pending:
            if item["url_key"] == key:
                return {
                    "ok": True,
                    "deduplicated": True,
                    "reason": "already_pending",
                    "url": target,
                }
        _pending.append(
            {
                "url": target,
                "url_key": key,
                "job_id": job_id,
                "ttl_seconds": ttl_seconds,
                "click_after_ms": max(0, int(click_after_ms or 0)),
                "time_label": str(time_label or "").strip(),
                "created_at": now,
            }
        )
        return {"ok": True, "deduplicated": False, "queued": True, "url": target}


def pull_pending(token: str, expected_token: str) -> Dict[str, Any]:
    if not expected_token or token != expected_token:
        return {"ok": False, "error": "Unauthorized"}

    now = time.time()
    with _lock:
        global _last_desktop_ping
        _last_desktop_ping = now
        if not _pending:
            return {"ok": True, "opens": []}
        item = _pending.pop(0)
        _opened_urls[item["url_key"]] = now
        return {
            "ok": True,
            "opens": [
                {
                    "url": item["url"],
                    "job_id": item.get("job_id"),
                    "ttl_seconds": item.get("ttl_seconds") or 30,
                    "click_after_ms": item.get("click_after_ms") or 0,
                    "time_label": item.get("time_label") or "",
                }
            ],
        }


def desktop_status(*, online_within_seconds: float = DEFAULT_ONLINE_SECONDS) -> Dict[str, Any]:
    now = time.time()
    with _lock:
        if _last_desktop_ping <= 0:
            return {"ok": True, "desktop_online": False, "last_seen_seconds_ago": None}
        age = now - _last_desktop_ping
        return {
            "ok": True,
            "desktop_online": age <= online_within_seconds,
            "last_seen_seconds_ago": round(age, 1),
        }
