"""Resolve countdown end_time from open URL (junb ?r= payload)."""

from __future__ import annotations

import base64
import html as html_module
import json
from typing import Optional
from urllib.parse import parse_qs, urlparse


def normalize_end_time_ms(raw: object) -> Optional[int]:
    try:
        end = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if end <= 0:
        return None
    if end < 1_000_000_000_000:
        return end * 1000
    return end


def parse_junb_end_time_ms(url: str) -> Optional[int]:
    text = html_module.unescape(str(url or "").strip())
    if not text:
        return None
    try:
        parsed = urlparse(text)
        raw = (parse_qs(parsed.query).get("r") or [None])[0]
        if not raw:
            return None
        padded = raw + "=" * ((4 - len(raw) % 4) % 4)
        payload = json.loads(base64.b64decode(padded).decode("utf-8"))
        if not isinstance(payload, dict):
            return None
        return normalize_end_time_ms(payload.get("end_time"))
    except Exception:
        return None


def resolve_countdown_end_time_ms(url: str) -> Optional[int]:
    return parse_junb_end_time_ms(url)
