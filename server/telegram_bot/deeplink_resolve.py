"""Resolve junb.io.vn / thanhtai.io shortlinks to TikTok live deeplink."""

from __future__ import annotations

import os
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

DEEPLINK_PREFIX = "snssdk1180://live?room_id="
BASE62_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE62_OFFSET = 0xE6875
ROOM_ID_PATTERN = re.compile(r"room_id=(\d+)")

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
ANCHOR_PATTERN = re.compile(r'<a href="(https?://[^"]+)">(.*?)</a>', re.IGNORECASE | re.DOTALL)
TAG_PATTERN = re.compile(r"<[^>]+>")


def deeplink_open_base_url() -> str:
    return os.environ.get("DEEPLINK_OPEN_BASE_URL", "http://103.38.237.7:8792").rstrip("/")


def extract_room_id(deeplink: str) -> Optional[str]:
    match = ROOM_ID_PATTERN.search(deeplink or "")
    return match.group(1) if match else None


def deeplink_open_href(deeplink: str) -> str:
    room_id = extract_room_id(deeplink)
    if not room_id:
        return (deeplink or "").strip()
    return f"{deeplink_open_base_url()}/open/live?room_id={room_id}"


def deeplink_hyperlink(deeplink: str, source_url: str = "") -> str:
    """Telegram needs https href; /open/live redirects to snssdk1180 on phone."""
    label = (deeplink or "").strip()
    href = deeplink_open_href(label)
    if not href.startswith("http"):
        href = (source_url or "").strip()
    href = href.replace("&", "&amp;")
    return f'<a href="{href}">{label}</a>'


def _host(url: str) -> str:
    return (urlparse(url.strip()).netloc or "").lower()


def is_live_shortlink_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    if "junb.io.vn" in host:
        if "bot-config" in path:
            return False
        return "/i/" in path or bool(re.search(r"[?&][A-Za-z0-9_-]+", url))

    if "thanhtai.io" in host:
        return bool(re.search(r"/r/[A-Za-z0-9_-]+", path))

    return False


def is_convertible_url(url: str) -> bool:
    return is_live_shortlink_url(url)


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
    param = extract_encoded_param(url)
    return decode_param(param)


def resolve_live_url(url: str) -> str:
    clean = (url or "").strip()
    if not clean or not is_live_shortlink_url(clean):
        return clean
    try:
        return decode_live_url(clean)
    except ValueError:
        return clean


def _is_inside_href(html_text: str, start: int) -> bool:
    href_pos = html_text.rfind('href="', 0, start)
    if href_pos < 0:
        return False
    return html_text.find('"', href_pos + 6, start) < 0


def _inner_looks_like_url(inner_html: str, source_url: str) -> bool:
    plain = TAG_PATTERN.sub("", inner_html or "").strip()
    if not plain:
        return True
    if plain == source_url.strip():
        return True
    if plain.startswith("http://") or plain.startswith("https://"):
        return True
    return "junb.io.vn" in plain or "thanhtai.io" in plain


def find_first_convertible_url(text: str) -> Optional[str]:
    for match in URL_PATTERN.finditer(text or ""):
        url = match.group(0)
        if is_live_shortlink_url(url):
            return url
    return None


def replace_urls_in_text(text: str) -> Tuple[str, int]:
    if not text:
        return text, 0

    replaced = 0

    def _sub(match: re.Match[str]) -> str:
        nonlocal replaced
        original = match.group(0)
        resolved = resolve_live_url(original)
        if resolved != original:
            replaced += 1
        return resolved

    return URL_PATTERN.sub(_sub, text), replaced


def replace_urls_as_deeplink_hyperlinks(text: str) -> Tuple[str, int]:
    if not text:
        return text, 0

    replaced = 0

    def _sub(match: re.Match[str]) -> str:
        nonlocal replaced
        original = match.group(0)
        resolved = resolve_live_url(original)
        if resolved == original:
            return original
        replaced += 1
        return deeplink_hyperlink(resolved, original)

    return URL_PATTERN.sub(_sub, text), replaced


def replace_urls_in_html(html_text: str) -> Tuple[str, int]:
    if not html_text:
        return html_text, 0

    replaced = 0

    def _anchor_sub(match: re.Match[str]) -> str:
        nonlocal replaced
        url, inner = match.group(1), match.group(2)
        if not is_live_shortlink_url(url):
            return match.group(0)
        deeplink = resolve_live_url(url)
        if deeplink == url:
            return match.group(0)
        replaced += 1
        if _inner_looks_like_url(inner, url):
            return deeplink_hyperlink(deeplink, url)
        open_href = deeplink_open_href(deeplink).replace("&", "&amp;")
        return f'<a href="{open_href}">{inner}</a>'

    updated = ANCHOR_PATTERN.sub(_anchor_sub, html_text)

    def _plain_sub(match: re.Match[str]) -> str:
        nonlocal replaced
        original = match.group(0)
        if _is_inside_href(updated, match.start()):
            return original
        if not is_live_shortlink_url(original):
            return original
        deeplink = resolve_live_url(original)
        if deeplink == original:
            return original
        replaced += 1
        return deeplink_hyperlink(deeplink, original)

    updated = URL_PATTERN.sub(_plain_sub, updated)
    return updated, replaced


def enrich_payload_with_deeplink(message_text: str, payload: dict) -> dict:
    enriched = dict(payload or {})
    if enriched.get("deeplink"):
        return enriched

    source_url = (
        str(enriched.get("url") or enriched.get("link") or "").strip()
        or find_first_convertible_url(message_text)
    )
    if not source_url:
        return enriched

    deeplink = resolve_live_url(source_url)
    if deeplink != source_url:
        enriched["deeplink"] = deeplink
        enriched.setdefault("source_url", source_url)
    return enriched
