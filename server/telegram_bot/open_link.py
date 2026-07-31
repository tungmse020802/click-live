"""Open countdown on desktop + deeplink on phone (resolve via profile_playwright API)."""

from __future__ import annotations

import html as html_module
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from deeplink_resolve import deeplink_open_href, resolve_link_for_open
from desktop_relay import enqueue_open

logger = logging.getLogger(__name__)


def phone_open_url(deeplink: str) -> str:
    text = str(deeplink or "").strip()
    if not text:
        return ""
    href = deeplink_open_href(text)
    if href.startswith("http://") or href.startswith("https://") or href.startswith("snssdk"):
        return href
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
    if not source_url:
        return {"ok": False, "error": "Missing url"}

    resolved = resolve_link_for_open(source_url, context)
    if not resolved.get("ok"):
        return resolved

    countdown_url = html_module.unescape(str(resolved.get("countdown_url") or "").strip())
    deeplink = str(resolved.get("deeplink") or "").strip()
    phone_url = phone_open_url(deeplink)

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

    return {
        "ok": True,
        "source_url": resolved.get("source_url") or source_url,
        "deeplink": deeplink,
        "room_id": resolved.get("room_id") or "",
        "countdown_url": countdown_url,
        "phone_open_url": phone_url,
        "desktop": desktop,
        "phone": phone,
    }
