"""Build phone poll jobs from queue items (shared by queue_ui + phone_registry)."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from db import QueueJob
from deeplink_resolve import (
    DEEPLINK_PREFIX,
    find_first_convertible_url,
    item_context_from_parts,
    resolve_deeplink_for_broadcast,
    resolve_link_for_open,
    resolve_live_url,
)


def phone_config() -> Dict[str, object]:
    return {
        "poll_seconds": 0,
        "long_poll_seconds": 25,
        "click_x": 540,
        "click_y": 1800,
        "auto_open": True,
        "auto_tap_requires_accessibility": True,
    }


def extract_link_from_item(item: Dict[str, Any]) -> str:
    payload = item.get("payload") or {}
    message = item.get("message") or {}
    message_text = str(message.get("text") or "")

    deeplink = resolve_deeplink_for_broadcast(message_text, payload)
    if deeplink and deeplink.startswith(DEEPLINK_PREFIX):
        return deeplink

    deeplink = str(payload.get("deeplink") or payload.get("deep_link") or "").strip()
    if deeplink.startswith(DEEPLINK_PREFIX):
        return deeplink

    context = item_context_from_parts(message_text, payload)
    source_url = (
        find_first_convertible_url(context)
        or str(payload.get("source_url") or "").strip()
    )
    if source_url:
        resolved = resolve_link_for_open(source_url, context)
        if resolved.get("ok"):
            resolved_deeplink = str(resolved.get("deeplink") or "").strip()
            if resolved_deeplink.startswith(DEEPLINK_PREFIX):
                return resolved_deeplink

    candidates = [
        payload.get("url"),
        payload.get("link"),
        payload.get("live_url"),
        payload.get("room_url"),
        message_text,
    ]
    for value in candidates:
        match = re.search(
            r"(?:https?://|tiktok://|snssdk1180://)[^\s<>'\"]+",
            str(value or ""),
            re.I,
        )
        if match:
            candidate = resolve_live_url(match.group(0), context)
            if candidate.startswith(DEEPLINK_PREFIX):
                return candidate
    return ""


from time_parse import extract_time_from_item
    url = extract_link_from_item(item)
    if not url:
        return None
    time_meta = extract_time_from_item(item)
    config = phone_config()
    return {
        "id": item.get("id"),
        "url": url,
        "time": time_meta["label"],
        "click_after_ms": time_meta["click_after_ms"],
        "target_time_hhmmss": time_meta.get("target_time_hhmmss", ""),
        "click_x": config["click_x"],
        "click_y": config["click_y"],
        "message": (item.get("message") or {}).get("text", ""),
        "payload": item.get("payload") or {},
    }


def phone_job_from_claimed_job(claimed: QueueJob) -> Optional[Dict[str, object]]:
    item = {
        "id": claimed.id,
        "payload": claimed.payload,
        "message": {"text": claimed.message_text},
        "room": {"chat_id": claimed.room_chat_id},
    }
    return phone_job_from_queue_item(item)
