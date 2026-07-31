"""Open countdown on desktop + deeplink on phone (resolve via profile_playwright API)."""

from __future__ import annotations

import html as html_module
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from deeplink_resolve import (
    DEEPLINK_PREFIX,
    deeplink_open_href,
    extract_room_id,
    item_context_from_parts,
    resolve_deeplink_for_broadcast,
    resolve_link_for_open,
)
from desktop_relay import enqueue_open
from phone_push import push_phone_open

logger = logging.getLogger(__name__)


def phone_open_url(deeplink: str) -> str:
    """Same URL as broadcast link — HTTP /open/live (redirects to TikTok app)."""
    text = str(deeplink or "").strip()
    if not text:
        return ""
    href = deeplink_open_href(text)
    if href.startswith("http://") or href.startswith("https://") or href.startswith("snssdk"):
        return href
    room_id = extract_room_id(text)
    if room_id:
        return f"{DEEPLINK_PREFIX}{room_id}"
    return text


def _relay_phone_monitor(
    base_url: str,
    *,
    url: str,
    queue_id: Optional[int] = None,
    time_label: str = "",
    click_after_ms: int = 0,
    click_x: int = 0,
    click_y: int = 0,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    endpoint = f"{base_url.rstrip('/')}/actions/deeplink"
    body = urllib.parse.urlencode(
        {
            "url": url,
            "source": "queue",
            "queue_id": str(queue_id or ""),
            "time": time_label,
            "click_after_ms": str(max(0, int(click_after_ms or 0))),
            "click_x": str(max(0, int(click_x or 0))),
            "click_y": str(max(0, int(click_y or 0))),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return {"ok": True, "method": "phone_monitor", "endpoint": endpoint, "response": raw[:500]}


def _try_open_phone(
    url: str,
    *,
    queue_id: Optional[int] = None,
    time_label: str = "",
    click_after_ms: int = 0,
    click_x: int = 0,
    click_y: int = 0,
    device_id: Optional[str] = None,
) -> Dict[str, Any]:
    if not url:
        return {"ok": False, "skipped": True, "reason": "no_phone_url"}

    monitor_base = os.environ.get("PHONE_MONITOR_BASE_URL", "").strip()
    if monitor_base:
        try:
            return _relay_phone_monitor(
                monitor_base,
                url=url,
                queue_id=queue_id,
                time_label=time_label,
                click_after_ms=click_after_ms,
                click_x=click_x,
                click_y=click_y,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("Phone monitor relay failed: %s", exc)

    if os.environ.get("PHONE_OPEN_VIA_ADB", "true").strip().lower() in ("1", "true", "yes"):
        try:
            import importlib

            queue_ui = importlib.import_module("queue_ui")
            adb_device = device_id or os.environ.get("PHONE_OPEN_DEVICE_ID", "").strip() or None
            return {
                **queue_ui._adb_open_link(
                    url,
                    device_id=adb_device,
                    click_after_ms=click_after_ms,
                    click_x=click_x,
                    click_y=click_y,
                ),
                "method": "adb",
            }
        except Exception as exc:
            logger.warning("ADB phone open failed: %s", exc)
            return {"ok": False, "error": str(exc), "method": "adb"}

    return {
        "ok": False,
        "skipped": True,
        "reason": "PHONE_MONITOR_BASE_URL unset and ADB unavailable",
        "phone_open_url": url,
    }


def open_link_for_queue(
    url: str,
    *,
    context: str = "",
    message_text: str = "",
    queue_payload: Optional[Dict[str, Any]] = None,
    job_id: Optional[int] = None,
    ttl_seconds: int = 30,
    dedup_seconds: int = 90,
    click_after_ms: int = 0,
    time_label: str = "",
    click_x: int = 0,
    click_y: int = 0,
    device_id: Optional[str] = None,
    open_phone: bool = True,
    open_desktop: bool = True,
) -> Dict[str, Any]:
    source_url = html_module.unescape(str(url or "").strip())
    queue_payload = dict(queue_payload or {})
    message_text = str(message_text or "").strip()
    if not context:
        context = item_context_from_parts(message_text, queue_payload)
    if not source_url:
        return {"ok": False, "error": "Missing url"}

    broadcast_deeplink = resolve_deeplink_for_broadcast(message_text, queue_payload) or ""

    resolved = resolve_link_for_open(source_url, context)
    if not resolved.get("ok") and not broadcast_deeplink:
        return resolved

    countdown_url = ""
    if resolved.get("ok"):
        countdown_url = html_module.unescape(str(resolved.get("countdown_url") or "").strip())

    deeplink = broadcast_deeplink or str(resolved.get("deeplink") or "").strip()
    if not deeplink:
        return {
            "ok": False,
            "error": "Không giải mã được deeplink TikTok (logic broadcast)",
            "source_url": source_url,
            "deeplink": "",
            "room_id": "",
            "countdown_url": countdown_url,
            "phone_open_url": "",
        }

    phone_url = phone_open_url(deeplink)
    room_id = extract_room_id(deeplink) or str(resolved.get("room_id") or "")

    if countdown_url.startswith("snssdk") or "/open/live" in countdown_url:
        countdown_url = ""

    desktop: Dict[str, Any] = {"ok": False, "skipped": True}
    if open_desktop and countdown_url.startswith(("http://", "https://")):
        desktop = enqueue_open(
            countdown_url,
            job_id=job_id,
            ttl_seconds=ttl_seconds,
            dedup_seconds=dedup_seconds,
            click_after_ms=click_after_ms,
            time_label=time_label,
        )

    phone: Dict[str, Any] = {"ok": False, "skipped": True}
    if open_phone and phone_url:
        phone = _try_open_phone(
            phone_url,
            queue_id=job_id,
            time_label=time_label,
            click_after_ms=click_after_ms,
            click_x=click_x,
            click_y=click_y,
            device_id=device_id,
        )
        push_result = push_phone_open(
            url=phone_url,
            queue_id=job_id,
            time_label=time_label,
            click_after_ms=click_after_ms,
            click_x=click_x,
            click_y=click_y,
        )
        if push_result.get("ok"):
            phone = {
                **phone,
                "ok": True,
                "method": phone.get("method") if phone.get("ok") else "phone_poll",
                "push": push_result,
            }

    return {
        "ok": True,
        "source_url": (resolved.get("source_url") if resolved.get("ok") else None) or source_url,
        "deeplink": deeplink,
        "room_id": room_id,
        "countdown_url": countdown_url,
        "phone_open_url": phone_url,
        "desktop": desktop,
        "phone": phone,
    }
