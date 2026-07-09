import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from db import ChatDatabase


def mask_bot_token(token: str) -> str:
    token = token.strip()
    if ":" not in token:
        return "***"
    bot_id, secret = token.split(":", 1)
    if len(secret) <= 8:
        return f"{bot_id}:****"
    return f"{bot_id}:{secret[:4]}...{secret[-4:]}"


def fetch_bot_info(bot_token: str) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    with urllib.request.urlopen(url, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not payload.get("ok"):
        raise RuntimeError(payload.get("description") or "getMe failed")

    result = payload.get("result") or {}
    username = str(result.get("username") or "").strip()
    first_name = str(result.get("first_name") or "").strip()
    return {
        "id": result.get("id"),
        "username": username,
        "first_name": first_name,
        "display_name": first_name or (f"@{username}" if username else "Bot"),
        "mention": f"@{username}" if username else "",
        "can_join_groups": bool(result.get("can_join_groups")),
        "can_read_all_group_messages": bool(result.get("can_read_all_group_messages")),
    }


def list_configured_bots(bot_tokens: List[str]) -> List[Dict[str, Any]]:
    bots: List[Dict[str, Any]] = []
    for index, token in enumerate(bot_tokens, start=1):
        info: Dict[str, Any] = {
            "index": index,
            "token_hint": mask_bot_token(token),
            "ok": False,
        }
        try:
            me = fetch_bot_info(token)
            info.update(me)
            info["ok"] = True
        except (urllib.error.URLError, RuntimeError, json.JSONDecodeError) as exc:
            info["error"] = str(exc)
        bots.append(info)
    return bots


def discover_bot_groups(bot_token: str, offset: Optional[int] = None) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    if offset is not None:
        url += f"?offset={offset}&timeout=0"
    else:
        url += "?timeout=0"

    with urllib.request.urlopen(url, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not payload.get("ok"):
        raise RuntimeError(payload.get("description") or "getUpdates failed")

    discovered: Dict[str, Dict[str, Any]] = {}
    next_offset = offset or 0

    for update in payload.get("result", []):
        update_id = int(update.get("update_id", 0))
        next_offset = max(next_offset, update_id + 1)

        for key in ("my_chat_member", "chat_member", "message"):
            event = update.get(key)
            if not isinstance(event, dict):
                continue
            chat = event.get("chat") or {}
            chat_type = str(chat.get("type") or "")
            if chat_type not in {"group", "supergroup", "channel"}:
                continue
            chat_id = chat.get("id")
            if chat_id is None:
                continue
            chat_id_text = str(chat_id)
            title = str(chat.get("title") or chat.get("username") or chat_id_text)
            discovered[chat_id_text] = {
                "chat_id": chat_id_text,
                "name": title,
                "chat_type": chat_type,
            }

    return {
        "next_offset": next_offset if next_offset else None,
        "discovered": list(discovered.values()),
    }


def discover_all_bot_groups(bot_tokens: List[str]) -> Dict[str, Any]:
    merged: Dict[str, Dict[str, Any]] = {}
    scans: List[Dict[str, Any]] = []

    for index, token in enumerate(bot_tokens, start=1):
        try:
            result = discover_bot_groups(token)
            scans.append({"index": index, "count": len(result["discovered"]), "ok": True})
            for group in result["discovered"]:
                merged[str(group["chat_id"])] = group
        except (urllib.error.URLError, RuntimeError, json.JSONDecodeError) as exc:
            scans.append({"index": index, "count": 0, "ok": False, "error": str(exc)})

    return {
        "discovered": list(merged.values()),
        "scans": scans,
    }


def register_discovered_groups(
    db: ChatDatabase,
    discovered_groups: List[Dict[str, Any]],
) -> Dict[str, Any]:
    db.init_schema()
    added = 0
    updated = 0
    for group in discovered_groups:
        created = db.upsert_pending_broadcast_group(
            chat_id=str(group["chat_id"]),
            name=str(group.get("name") or group["chat_id"]),
        )
        if created:
            added += 1
        else:
            updated += 1
    return {
        "added": added,
        "updated": updated,
        "pending": db.list_pending_broadcast_groups(),
        "approved": db.list_approved_broadcast_groups(),
    }
