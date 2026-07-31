import json
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from db import ChatDatabase

_ALLOWED_UPDATES = [
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "my_chat_member",
    "chat_member",
]
_ACTIVE_MEMBER_STATUSES = {"member", "administrator", "creator", "restricted"}


def mask_bot_token(token: str) -> str:
    token = token.strip()
    if ":" not in token:
        return "***"
    bot_id, secret = token.split(":", 1)
    if len(secret) <= 8:
        return f"{bot_id}:****"
    return f"{bot_id}:{secret[:4]}...{secret[-4:]}"


def fetch_bot_info(bot_token: str, *, timeout: float = 5) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    with urllib.request.urlopen(url, timeout=timeout) as response:
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


def _telegram_api(
    bot_token: str,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    timeout: float = 15,
) -> Dict[str, Any]:
    query = ""
    if params:
        encoded: Dict[str, str] = {}
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                encoded[key] = json.dumps(value, ensure_ascii=False)
            else:
                encoded[key] = str(value)
        query = "?" + urllib.parse.urlencode(encoded)
    url = f"https://api.telegram.org/bot{bot_token}/{method}{query}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description") or f"{method} failed")
    return payload


def _extract_group_from_event(event: Dict[str, Any], *, require_active_member: bool) -> Optional[Dict[str, Any]]:
    if not isinstance(event, dict):
        return None

    if require_active_member:
        new_member = event.get("new_chat_member") or {}
        status = str(new_member.get("status") or "").strip().lower()
        if status and status not in _ACTIVE_MEMBER_STATUSES:
            return None

    chat = event.get("chat") or {}
    chat_type = str(chat.get("type") or "")
    if chat_type not in {"group", "supergroup", "channel"}:
        return None
    chat_id = chat.get("id")
    if chat_id is None:
        return None
    chat_id_text = str(chat_id)
    title = str(chat.get("title") or chat.get("username") or chat_id_text)
    return {
        "chat_id": chat_id_text,
        "name": title,
        "chat_type": chat_type,
    }


def discover_bot_groups(bot_token: str, offset: Optional[int] = None) -> Dict[str, Any]:
    """Scan getUpdates for groups/channels this bot can access.

    Telegram Bot API cannot list all chats. Discovery only works from recent
    updates (bot added, message, channel post). We page through pending updates
    and confirm them after processing so the queue does not stall forever.
    """
    try:
        _telegram_api(bot_token, "deleteWebhook", {"drop_pending_updates": False}, timeout=8)
    except Exception:
        pass

    discovered: Dict[str, Dict[str, Any]] = {}
    next_offset = offset
    pages = 0
    update_count = 0

    while pages < 20:
        params: Dict[str, Any] = {
            "timeout": 0,
            "limit": 100,
            "allowed_updates": _ALLOWED_UPDATES,
        }
        if next_offset is not None:
            params["offset"] = next_offset

        payload = _telegram_api(bot_token, "getUpdates", params, timeout=20)
        updates = payload.get("result") or []
        pages += 1
        if not updates:
            break

        update_count += len(updates)
        max_update_id = 0
        for update in updates:
            update_id = int(update.get("update_id", 0) or 0)
            max_update_id = max(max_update_id, update_id)

            for key in ("my_chat_member", "chat_member"):
                group = _extract_group_from_event(
                    update.get(key) or {},
                    require_active_member=True,
                )
                if group:
                    discovered[group["chat_id"]] = group

            for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
                group = _extract_group_from_event(
                    update.get(key) or {},
                    require_active_member=False,
                )
                if group:
                    discovered[group["chat_id"]] = group

        # Confirm processed updates so later scans see only new events.
        next_offset = max_update_id + 1
        if len(updates) < 100:
            break

    if next_offset is not None:
        try:
            _telegram_api(
                bot_token,
                "getUpdates",
                {
                    "offset": next_offset,
                    "timeout": 0,
                    "limit": 1,
                    "allowed_updates": _ALLOWED_UPDATES,
                },
                timeout=12,
            )
        except Exception:
            pass

    return {
        "next_offset": next_offset,
        "update_count": update_count,
        "pages": pages,
        "discovered": list(discovered.values()),
    }


def discover_all_bot_groups(bot_tokens: List[str]) -> Dict[str, Any]:
    merged: Dict[str, Dict[str, Any]] = {}
    scans: List[Dict[str, Any]] = []
    normalized = [token.strip() for token in bot_tokens if token and token.strip()]

    def _scan(index: int, token: str) -> Dict[str, Any]:
        bot_id = token.split(":", 1)[0]
        try:
            result = discover_bot_groups(token)
            return {
                "index": index,
                "bot_id": bot_id,
                "count": len(result["discovered"]),
                "update_count": result.get("update_count", 0),
                "ok": True,
                "discovered": result["discovered"],
            }
        except (urllib.error.URLError, RuntimeError, json.JSONDecodeError, TimeoutError) as exc:
            return {
                "index": index,
                "bot_id": bot_id,
                "count": 0,
                "update_count": 0,
                "ok": False,
                "error": str(exc),
                "discovered": [],
            }

    if not normalized:
        return {"discovered": [], "scans": []}

    workers = min(12, len(normalized))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_scan, index, token): index
            for index, token in enumerate(normalized, start=1)
        }
        for future in as_completed(futures):
            scan = future.result()
            scans.append(
                {
                    "index": scan["index"],
                    "bot_id": scan.get("bot_id"),
                    "count": scan.get("count", 0),
                    "update_count": scan.get("update_count", 0),
                    "ok": scan.get("ok", False),
                    **({"error": scan["error"]} if scan.get("error") else {}),
                }
            )
            for group in scan.get("discovered") or []:
                merged[str(group["chat_id"])] = group

    scans.sort(key=lambda item: int(item.get("index") or 0))
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
    already_approved = 0
    new_pending: List[Dict[str, Any]] = []

    approved_ids = {
        str(group.get("chat_id"))
        for group in db.list_approved_broadcast_groups()
    }

    for group in discovered_groups:
        chat_id = str(group["chat_id"])
        created = db.upsert_pending_broadcast_group(
            chat_id=chat_id,
            name=str(group.get("name") or chat_id),
        )
        if chat_id in approved_ids:
            already_approved += 1
            updated += 1
            continue
        if created:
            added += 1
            new_pending.append(
                {
                    "chat_id": chat_id,
                    "name": str(group.get("name") or chat_id),
                }
            )
        else:
            updated += 1

    return {
        "added": added,
        "updated": updated,
        "already_approved": already_approved,
        "new_pending": new_pending,
        "pending": db.list_pending_broadcast_groups(),
        "approved": db.list_approved_broadcast_groups(),
    }
