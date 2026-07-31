"""Decode junb.io.vn / thanhtai.io shortlinks to TikTok live deeplink."""

from __future__ import annotations

import base64
import re
from urllib.parse import urlparse

DEEPLINK_PREFIX = "snssdk1180://live?room_id="
BASE62_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE62_OFFSET = 0xE6875
COUNTDOWN_PATTERN = re.compile(r"thanhtai\.io/countdow\?data=([A-Za-z0-9+/=]+)", re.IGNORECASE)


def extract_thanhtai_countdown_room_id(text: str) -> str | None:
    match = COUNTDOWN_PATTERN.search(text or "")
    if not match:
        return None
    data = match.group(1)
    try:
        padding = "=" * ((4 - len(data) % 4) % 4)
        decoded = base64.b64decode(data + padding).decode("ascii").strip()
    except (ValueError, UnicodeDecodeError):
        return None
    if decoded.isdigit() and len(decoded) >= 10:
        return decoded
    return None


def is_thanhtai_hex_code(code: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]+", (code or "").strip()))


def is_offline_decodable_param(code: str) -> bool:
    param = (code or "").strip()
    if len(param) < 10:
        return False
    if is_thanhtai_hex_code(param):
        return False
    if not re.search(r"[A-Z]", param):
        return False
    return all(ch in BASE62_CHARS or ch in "_-" for ch in param)


def extract_encoded_param(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()

    if "junb.io.vn" in host:
        match = re.search(r"[?&]([A-Za-z0-9_-]+)(?:$|&)", url)
        if match:
            return match.group(1)

    if "thanhtai.io" in host:
        path_match = re.search(r"/r/([A-Za-z0-9_-]+)", parsed.path or "")
        if path_match:
            return path_match.group(1)
        query_match = re.search(r"[?&]([A-Za-z0-9_-]+)(?:$|&)", url)
        if query_match:
            return query_match.group(1)

    raise ValueError("Unsupported URL. Use junb.io.vn/i/?CODE or thanhtai.io/r/CODE")


def decode_param(param: str) -> str:
    if not is_offline_decodable_param(param):
        raise ValueError(f"Not an offline-decodable live code: {param!r}")

    w = param[:-1] if param.endswith("=") else param
    w = w[::-1]

    y = 0
    for ch in w:
        try:
            idx = BASE62_CHARS.index(ch)
        except ValueError as exc:
            raise ValueError(f"Invalid character in shortlink code: {ch!r}") from exc
        y = y * 62 + idx
    y -= BASE62_OFFSET

    decoded = str(y)[1:][::-1]
    if not decoded:
        raise ValueError("Decoded payload is empty")

    t = decoded[0]
    rest = decoded[1:]
    trim = int(t) if t.isdigit() else 0
    room_id = rest[: max(0, len(rest) - trim)]
    if not room_id.isdigit():
        raise ValueError(f"Invalid room_id: {room_id!r}")

    return f"{DEEPLINK_PREFIX}{room_id}"


def decode_live_url(url: str, context: str = "") -> str:
    """Decode junb/thanhtai shortlink to TikTok live deeplink."""
    room_id = extract_thanhtai_countdown_room_id(url)
    if room_id:
        return f"{DEEPLINK_PREFIX}{room_id}"

    if "thanhtai.io" in (urlparse(url).netloc or "").lower() and "/r/" in url:
        code_match = re.search(r"/r/([A-Za-z0-9_-]+)", url)
        if code_match and is_thanhtai_hex_code(code_match.group(1)):
            from thanhtai_http import resolve_thanhtai_via_http

            deeplink = resolve_thanhtai_via_http(url)
            if deeplink:
                return deeplink
            room_id = extract_thanhtai_countdown_room_id(context)
            if room_id:
                return f"{DEEPLINK_PREFIX}{room_id}"
            from thanhtai_playwright import resolve_thanhtai_via_playwright

            return resolve_thanhtai_via_playwright(url)

    param = extract_encoded_param(url)
    return decode_param(param)


def decode_junb_url(url: str) -> str:
    return decode_live_url(url)
