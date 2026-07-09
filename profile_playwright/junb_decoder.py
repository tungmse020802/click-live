"""Decode junb.io.vn / thanhtai.io shortlinks to TikTok live deeplink."""

import re
from urllib.parse import urlparse

DEEPLINK_PREFIX = "snssdk1180://live?room_id="
BASE62_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE62_OFFSET = 0xE6875


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


def decode_live_url(url: str) -> str:
    """Decode junb.io.vn or thanhtai.io shortlink to TikTok live deeplink."""
    param = extract_encoded_param(url)
    return decode_param(param)


def decode_junb_url(url: str) -> str:
    """Backward-compatible alias."""
    return decode_live_url(url)
