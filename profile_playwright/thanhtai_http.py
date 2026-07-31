"""Resolve thanhtai.io /r/hex links via HTTP + HTML script parse."""

from __future__ import annotations

import os
import re
import urllib.request

from config import DEVICE_ID

DEEPLINK_PATTERN = re.compile(r"snssdk1180://live\?room_id=\d+")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def thanhtai_device_id() -> str:
    return (os.environ.get("THANHTAI_DEVICE_ID") or DEVICE_ID or "").strip()


def extract_deeplink_from_html(html: str) -> str | None:
    match = DEEPLINK_PATTERN.search(html or "")
    return match.group(0) if match else None


def resolve_thanhtai_via_http(url: str, *, timeout: float = 15) -> str | None:
    """Fetch thanhtai page; room_id is in inline script location.href."""
    clean_url = (url or "").strip()
    if not clean_url:
        return None

    device_id = thanhtai_device_id()
    if not device_id:
        return None

    request = urllib.request.Request(
        clean_url,
        headers={
            "Cookie": f"device_id={device_id}",
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    return extract_deeplink_from_html(html)
