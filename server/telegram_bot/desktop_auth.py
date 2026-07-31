"""Desktop pull tokens & queue UI users — mỗi user chỉ mở tab trên desktop đã login cùng user."""

from __future__ import annotations

import hashlib
import hmac
from typing import Dict, Mapping, Optional


DEFAULT_QUEUE_PASSWORD = "Admin123@"


def seed_queue_users(
    count: int = 10,
    *,
    prefix: str = "admin",
    password: str = DEFAULT_QUEUE_PASSWORD,
) -> Dict[str, str]:
    total = max(0, int(count))
    base = str(prefix or "admin").strip() or "admin"
    secret = str(password or DEFAULT_QUEUE_PASSWORD)
    return {f"{base}{index}": secret for index in range(1, total + 1)}


def format_queue_users(users: Mapping[str, str]) -> str:
    return ",".join(f"{username}:{password}" for username, password in users.items())


def parse_queue_users(
    raw: str,
    *,
    fallback_username: str = "",
    fallback_password: str = "",
) -> Dict[str, str]:
    users: Dict[str, str] = {}
    for chunk in str(raw or "").split(","):
        part = chunk.strip()
        if not part or ":" not in part:
            continue
        username, password = part.split(":", 1)
        username = username.strip()
        password = password.strip()
        if username and password:
            users[username] = password
    if not users and fallback_username and fallback_password:
        users[fallback_username] = fallback_password
    return users


def verify_queue_user(username: str, password: str, users: Mapping[str, str]) -> bool:
    if not users:
        return True
    expected = users.get(str(username or "").strip())
    if expected is None:
        return False
    return hmac.compare_digest(str(password or ""), expected)


def desktop_pull_token_for_user(username: str, secret: str) -> str:
    name = str(username or "").strip()
    if not secret or not name:
        return ""
    digest = hmac.new(
        secret.encode("utf-8"),
        f"desktop-pull:{name}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:40]


def list_queue_usernames(users: Mapping[str, str]) -> list[str]:
    return sorted(str(name).strip() for name in users if str(name).strip())


def resolve_username_from_desktop_token(
    token: str,
    *,
    users: Mapping[str, str],
    secret: str,
) -> Optional[str]:
    text = str(token or "").strip()
    if not text:
        return None
    for username in users:
        if hmac.compare_digest(text, desktop_pull_token_for_user(username, secret)):
            return username
    return None
