"""Relay mở countdown: queue UI (theo user) → desktop-tool (login cùng user)."""

from __future__ import annotations

import html as html_module
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from urllib.parse import parse_qs, urlparse

from config import QueueUiConfig, queue_users_map
from desktop_auth import resolve_username_from_desktop_token

_lock = threading.Lock()
_pending: List[Dict[str, Any]] = []
_opened_urls: Dict[Tuple[str, str], float] = {}
_last_desktop_ping: Dict[str, float] = {}

PENDING_MAX = 32
DEFAULT_DEDUP_SECONDS = 90
DEFAULT_ONLINE_SECONDS = 20
DEFAULT_QUEUE_USER = ""


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


def _normalize_queue_user(queue_user: Optional[str]) -> str:
    return str(queue_user or "").strip()


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
    queue_user: str = "",
) -> Dict[str, Any]:
    target = html_module.unescape(str(url or "").strip())
    if not target.startswith("http://") and not target.startswith("https://"):
        return {"ok": False, "error": "Invalid url"}

    user = _normalize_queue_user(queue_user)
    key = normalize_open_url(target)
    dedup_key = (user, key)
    now = time.time()
    with _lock:
        _purge_old(now, dedup_seconds)
        if dedup_key in _opened_urls:
            return {
                "ok": True,
                "deduplicated": True,
                "reason": "already_opened",
                "url": target,
                "queue_user": user,
            }
        for item in _pending:
            if item["url_key"] == key and item.get("queue_user", "") == user:
                return {
                    "ok": True,
                    "deduplicated": True,
                    "reason": "already_pending",
                    "url": target,
                    "queue_user": user,
                }
        _pending.append(
            {
                "url": target,
                "url_key": key,
                "job_id": job_id,
                "ttl_seconds": ttl_seconds,
                "click_after_ms": max(0, int(click_after_ms or 0)),
                "time_label": str(time_label or "").strip(),
                "queue_user": user,
                "created_at": now,
            }
        )
        return {
            "ok": True,
            "deduplicated": False,
            "queued": True,
            "url": target,
            "queue_user": user,
        }


def _pop_pending_for_user(queue_user: str) -> Optional[Dict[str, Any]]:
    user = _normalize_queue_user(queue_user)
    for index, item in enumerate(_pending):
        if item.get("queue_user", "") == user:
            return _pending.pop(index)
    return None


def pull_pending(token: str, config: QueueUiConfig) -> Dict[str, Any]:
    users = queue_users_map(config)
    queue_user = resolve_username_from_desktop_token(
        token,
        users=users,
        secret=config.auth_secret,
    )
    if not queue_user:
        return {"ok": False, "error": "Unauthorized"}

    now = time.time()
    with _lock:
        _last_desktop_ping[queue_user] = now
        item = _pop_pending_for_user(queue_user)
        if not item:
            return {"ok": True, "opens": [], "queue_user": queue_user}
        _opened_urls[(queue_user, item["url_key"])] = now
        return {
            "ok": True,
            "queue_user": queue_user,
            "opens": [
                {
                    "url": item["url"],
                    "job_id": item.get("job_id"),
                    "ttl_seconds": item.get("ttl_seconds") or 30,
                    "click_after_ms": item.get("click_after_ms") or 0,
                    "time_label": item.get("time_label") or "",
                    "queue_user": queue_user,
                }
            ],
        }


def desktop_status(
    *,
    queue_user: str = "",
    online_within_seconds: float = DEFAULT_ONLINE_SECONDS,
) -> Dict[str, Any]:
    user = _normalize_queue_user(queue_user)
    now = time.time()
    with _lock:
        if not user:
            any_online = any(now - ts <= online_within_seconds for ts in _last_desktop_ping.values())
            return {
                "ok": True,
                "desktop_online": any_online,
                "last_seen_seconds_ago": None,
                "queue_user": "",
            }
        last = _last_desktop_ping.get(user, 0.0)
        if last <= 0:
            return {
                "ok": True,
                "desktop_online": False,
                "last_seen_seconds_ago": None,
                "queue_user": user,
            }
        age = now - last
        return {
            "ok": True,
            "desktop_online": age <= online_within_seconds,
            "last_seen_seconds_ago": round(age, 1),
            "queue_user": user,
        }
