"""Parse TIME lines from Telegram box messages."""

from __future__ import annotations

import re
from typing import Any, Dict


def normalize_time_label(raw: str) -> str:
    """Keep only countdown + HH:MM:SS; drop trailing BOX/emoji junk on same line."""
    text = str(raw or "").strip()
    if not text:
        return ""

    compact = re.search(
        r"(\d{1,2}:\d{2}\s*s?\s*-\s*\d{1,2}:\d{2}:\d{2})",
        text,
        re.I,
    )
    if compact:
        return re.sub(r"\s+", " ", compact.group(1).strip())

    only_delay = re.search(r"^(\d{1,2}:\d{2}\s*s?)", text, re.I)
    if only_delay:
        return only_delay.group(1).strip()

    cut = re.split(r"\s+(?:🎁|BOX|📈|Rate)", text, maxsplit=1, flags=re.I)
    return cut[0].strip()


def parse_time_delay_ms(value: Any) -> int:
    text = str(value or "").strip()
    match = re.search(r"(\d{1,2}):(\d{2})\s*s?", text, re.I)
    if match:
        return (int(match.group(1)) * 60 + int(match.group(2))) * 1000
    match = re.search(r"(\d+(?:\.\d+)?)\s*s", text, re.I)
    if match:
        return int(float(match.group(1)) * 1000)
    return 0


def extract_time_from_text(text: str) -> Dict[str, object]:
    raw = str(text or "")
    match = (
        re.search(r"TIME\s*[:：]\s*([^\n\r]+)", raw, re.I)
        or re.search(r"(\d{1,2}:\d{2}\s*s?\s*-\s*\d{1,2}:\d{2}:\d{2})", raw, re.I)
        or re.search(r"(\d{1,2}:\d{2}\s*s?)", raw, re.I)
    )
    if not match:
        return {"label": "", "click_after_ms": 0, "target_time_hhmmss": ""}

    label = normalize_time_label(match.group(1))
    target_match = re.search(r"-\s*(\d{1,2}:\d{2}:\d{2})", label)
    return {
        "label": label,
        "click_after_ms": parse_time_delay_ms(label),
        "target_time_hhmmss": target_match.group(1).strip() if target_match else "",
    }


def extract_time_from_item(item: Dict[str, Any]) -> Dict[str, object]:
    payload = item.get("payload") or {}
    message = item.get("message") or {}
    candidates = [
        payload.get("TIME"),
        payload.get("time"),
        payload.get("Time"),
        payload.get("click_time"),
        payload.get("open_time"),
        message.get("text"),
    ]
    for value in candidates:
        parsed = extract_time_from_text(str(value or ""))
        if parsed.get("label"):
            return parsed
    return {"label": "", "click_after_ms": 0, "target_time_hhmmss": ""}
