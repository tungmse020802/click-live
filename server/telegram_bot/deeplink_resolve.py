"""Resolve junb.io.vn / thanhtai.io shortlinks to TikTok live deeplink."""

from __future__ import annotations

import base64
import html as html_module
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Optional, Tuple
from urllib.parse import parse_qs, urlparse

_cache_lock = threading.Lock()
_deeplink_api_cache: dict[str, tuple[float, str]] = {}

DEEPLINK_PREFIX = "snssdk1180://live?room_id="
BASE62_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE62_OFFSET = 0xE6875
ROOM_ID_PATTERN = re.compile(r"room_id=(\d+)")
COUNTDOWN_PATTERN = re.compile(r"thanhtai\.io/countdow\?data=([A-Za-z0-9+/=]+)", re.IGNORECASE)

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
ANCHOR_PATTERN = re.compile(r'<a href="(https?://[^"]+)">(.*?)</a>', re.IGNORECASE | re.DOTALL)
TAG_PATTERN = re.compile(r"<[^>]+>")
COIN_RATIO_PATTERN = re.compile(r"\d+\s*/\s*\d+")


def normalize_url_href(href: str) -> str:
    return html_module.unescape(str(href or "").strip())


def deeplink_api_base_url() -> str:
    return os.environ.get("DEEPLINK_API_BASE_URL", "http://127.0.0.1:8792").rstrip("/")


def deeplink_api_timeout() -> float:
    try:
        return max(3.0, float(os.environ.get("DEEPLINK_API_TIMEOUT_SECONDS", "20")))
    except ValueError:
        return 20.0


def deeplink_cache_ttl_seconds() -> float:
    try:
        return max(60.0, float(os.environ.get("DEEPLINK_CACHE_TTL_SECONDS", "600")))
    except ValueError:
        return 600.0


def resolve_via_deeplink_api(url: str, context: str = "") -> Optional[str]:
    key = (url or "").strip()
    if not key:
        return None

    now = time.time()
    with _cache_lock:
        cached = _deeplink_api_cache.get(key)
        if cached and now - cached[0] < deeplink_cache_ttl_seconds():
            return cached[1]

    params = urllib.parse.urlencode({"url": key, "context": context or key})
    endpoint = f"{deeplink_api_base_url()}/api/deeplink?{params}"
    try:
        with urllib.request.urlopen(endpoint, timeout=deeplink_api_timeout()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    if not payload.get("ok"):
        return None
    deeplink = str(payload.get("deeplink") or "").strip()
    if deeplink.startswith(DEEPLINK_PREFIX):
        with _cache_lock:
            _deeplink_api_cache[key] = (now, deeplink)
        return deeplink
    return None


def deeplink_open_base_url() -> str:
    explicit = os.environ.get("DEEPLINK_OPEN_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    api_base = deeplink_api_base_url()
    if "127.0.0.1" in api_base or "localhost" in api_base.lower():
        return ""
    return api_base


def extract_room_id(deeplink: str) -> Optional[str]:
    match = ROOM_ID_PATTERN.search(deeplink or "")
    return match.group(1) if match else None


def deeplink_open_href(deeplink: str) -> str:
    room_id = extract_room_id(deeplink)
    if not room_id:
        return (deeplink or "").strip()
    open_base = deeplink_open_base_url()
    if not open_base:
        return (deeplink or "").strip()
    return f"{open_base}/open/live?room_id={room_id}"


def deeplink_hyperlink(deeplink: str, source_url: str = "") -> str:
    label = (deeplink or "").strip()
    href = deeplink_open_href(label)
    if not href.startswith("http") and not href.startswith("snssdk"):
        href = (source_url or label).strip()
    href = href.replace("&", "&amp;")
    return f'<a href="{href}">{label}</a>'


def _host(url: str) -> str:
    return (urlparse(url.strip()).netloc or "").lower()


def extract_thanhtai_countdown_room_id(text: str) -> Optional[str]:
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


def is_thanhtai_countdown_url(url: str) -> bool:
    return "thanhtai.io" in _host(url) and "countdow" in (urlparse(url).path or "")


def is_junb_box_countdown_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    return "junb.io.vn" in host and "/box-countdown/" in path


def is_countdown_page_url(url: str) -> bool:
    return is_thanhtai_countdown_url(url) or is_junb_box_countdown_url(url)


def is_live_shortlink_url(url: str) -> bool:
    if is_countdown_page_url(url):
        return False
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    if is_thanhtai_countdown_url(url):
        return extract_thanhtai_countdown_room_id(url) is not None

    if "junb.io.vn" in host:
        if "bot-config" in path or "/box-countdown/" in path:
            return False
        return "/i/" in path or bool(re.search(r"[?&][A-Za-z0-9_-]+", url))

    if "thanhtai.io" in host:
        path_match = re.search(r"/r/([A-Za-z0-9_-]+)", path)
        if path_match:
            return is_offline_decodable_param(path_match.group(1))
        return False

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
    if not is_offline_decodable_param(param):
        raise ValueError(f"Not an offline-decodable live code: {param!r}")
    return decode_param(param)


def find_thanhtai_hex_url(text: str) -> Optional[str]:
    for match in URL_PATTERN.finditer(text or ""):
        url = match.group(0)
        if "thanhtai.io" not in _host(url) or "/r/" not in url:
            continue
        code_match = re.search(r"/r/([A-Za-z0-9_-]+)", url)
        if code_match and is_thanhtai_hex_code(code_match.group(1)):
            return url
    return None


def resolve_deeplink_from_text(text: str) -> Optional[str]:
    hex_url = find_thanhtai_hex_url(text)
    if hex_url:
        api_deeplink = resolve_via_deeplink_api(hex_url, hex_url)
        if api_deeplink:
            return api_deeplink

    room_id = extract_thanhtai_countdown_room_id(text)
    if room_id:
        return f"{DEEPLINK_PREFIX}{room_id}"

    for match in URL_PATTERN.finditer(text or ""):
        url = match.group(0)
        if "junb.io.vn" in url and "/i/" in url and is_live_shortlink_url(url):
            deeplink = resolve_live_url(url, text)
            if deeplink.startswith(DEEPLINK_PREFIX):
                return deeplink

    for match in URL_PATTERN.finditer(text or ""):
        url = match.group(0)
        if is_live_shortlink_url(url):
            deeplink = resolve_live_url(url, text)
            if deeplink.startswith(DEEPLINK_PREFIX):
                return deeplink

    return None


def resolve_live_url(url: str, context: str = "") -> str:
    clean = (url or "").strip()
    if not clean:
        return clean

    if is_thanhtai_countdown_url(clean):
        hex_url = find_thanhtai_hex_url(context or clean)
        if hex_url:
            api_deeplink = resolve_via_deeplink_api(hex_url, hex_url)
            if api_deeplink:
                return api_deeplink

    room_id = extract_thanhtai_countdown_room_id(clean)
    if room_id:
        return f"{DEEPLINK_PREFIX}{room_id}"

    if "thanhtai.io" in _host(clean) and "/r/" in clean:
        code_match = re.search(r"/r/([A-Za-z0-9_-]+)", clean)
        if code_match and is_thanhtai_hex_code(code_match.group(1)):
            api_deeplink = resolve_via_deeplink_api(clean, clean)
            if api_deeplink:
                return api_deeplink
            room_id = extract_thanhtai_countdown_room_id(context)
            if room_id:
                return f"{DEEPLINK_PREFIX}{room_id}"
            return clean

    if not is_live_shortlink_url(clean):
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
    if plain.startswith("snssdk1180://"):
        return True
    return "junb.io.vn" in plain or "thanhtai.io" in plain


def find_first_convertible_url(text: str) -> Optional[str]:
    for match in URL_PATTERN.finditer(text or ""):
        url = match.group(0)
        if extract_thanhtai_countdown_room_id(url):
            return url

    for match in URL_PATTERN.finditer(text or ""):
        url = match.group(0)
        if "junb.io.vn" in url and is_live_shortlink_url(url):
            return url

    for match in URL_PATTERN.finditer(text or ""):
        url = match.group(0)
        if is_live_shortlink_url(url):
            return url

    return None


def find_countdown_url_for_open(text: str) -> Optional[str]:
    """Ưu tiên link countdown gắn trên anchor 50/25, không lấy URL đầu tiên trong blob."""
    if not text:
        return None

    for match in ANCHOR_PATTERN.finditer(text):
        href = normalize_url_href(match.group(1) or "")
        inner_plain = TAG_PATTERN.sub("", match.group(2) or "").strip()
        if not COIN_RATIO_PATTERN.search(inner_plain):
            continue
        if is_junb_box_countdown_url(href) or is_thanhtai_countdown_url(href):
            return href

    countdowns: list[str] = []
    seen: set[str] = set()
    for match in ANCHOR_PATTERN.finditer(text):
        href = normalize_url_href(match.group(1) or "")
        if not (is_junb_box_countdown_url(href) or is_thanhtai_countdown_url(href)):
            continue
        if href in seen:
            continue
        seen.add(href)
        countdowns.append(href)
    if len(countdowns) == 1:
        return countdowns[0]

    for match in URL_PATTERN.finditer(text):
        url = normalize_url_href(match.group(0).rstrip(".,);]"))
        if is_junb_box_countdown_url(url) or is_thanhtai_countdown_url(url):
            return url

    return None


def find_first_countdown_url(text: str) -> Optional[str]:
    """URL trang countdown gắn trong tin (junb box-countdown hoặc thanhtai countdow)."""
    found = find_countdown_url_for_open(text)
    if found:
        return found

    if not text:
        return None

    for match in ANCHOR_PATTERN.finditer(text):
        href = normalize_url_href(match.group(1) or "")
        if is_junb_box_countdown_url(href):
            return href

    for match in URL_PATTERN.finditer(text):
        url = normalize_url_href(match.group(0).rstrip(".,);]"))
        if is_junb_box_countdown_url(url):
            return url

    for match in ANCHOR_PATTERN.finditer(text):
        href = normalize_url_href(match.group(1) or "")
        if is_thanhtai_countdown_url(href):
            return href

    for match in URL_PATTERN.finditer(text):
        url = normalize_url_href(match.group(0).rstrip(".,);]"))
        if is_thanhtai_countdown_url(url):
            return url

    return None


def extract_countdown_url(message_text: str = "", payload: Optional[dict] = None) -> str:
    """Countdown đúng của tin: chỉ từ telegram_html / message, không từ source_url deeplink cũ."""
    payload = payload or {}
    telegram_html = str(payload.get("telegram_html") or "").strip()
    if telegram_html:
        display_html, _ = replace_urls_in_html_for_queue_display(telegram_html)
        found = find_countdown_url_for_open(display_html)
        if found:
            return found

    found = find_countdown_url_for_open(message_text or "")
    if found:
        return found

    return ""


def resolve_countdown_open_url(text: str, *, room_id: str = "") -> str:
    found = find_countdown_url_for_open(text) or find_first_countdown_url(text)
    if found:
        return found
    clean_room = (room_id or "").strip()
    if clean_room.isdigit():
        return build_thanhtai_countdown_url(clean_room)
    from_room = extract_thanhtai_countdown_room_id(text or "")
    if from_room:
        return build_thanhtai_countdown_url(from_room)
    return ""


def replace_urls_in_html_for_queue_display(html_text: str) -> Tuple[str, int]:
    """Giữ countdown trong tin; không thay href bằng TikTok open/live."""
    if not html_text:
        return html_text, 0

    countdown = find_countdown_url_for_open(html_text) or find_first_countdown_url(html_text)
    replaced = 0

    def _anchor_sub(match: re.Match[str]) -> str:
        nonlocal replaced
        url, inner = match.group(1), match.group(2)
        if is_countdown_page_url(url):
            return match.group(0)
        if countdown:
            inner_plain = TAG_PATTERN.sub("", inner or "").strip()
            if re.search(r"\d+\s*/\s*\d+", inner_plain):
                safe = countdown.replace("&", "&amp;")
                if url.strip() != countdown.strip():
                    replaced += 1
                return f'<a href="{safe}">{inner}</a>'
        return match.group(0)

    updated = ANCHOR_PATTERN.sub(_anchor_sub, html_text)
    return updated, replaced


def replace_urls_in_text(text: str) -> Tuple[str, int]:
    if not text:
        return text, 0

    replaced = 0

    def _sub(match: re.Match[str]) -> str:
        nonlocal replaced
        original = match.group(0)
        resolved = resolve_live_url(original, text)
        if resolved != original and resolved.startswith(DEEPLINK_PREFIX):
            replaced += 1
            return resolved
        return original

    return URL_PATTERN.sub(_sub, text), replaced


def replace_urls_as_deeplink_hyperlinks(text: str) -> Tuple[str, int]:
    if not text:
        return text, 0

    replaced = 0

    def _sub(match: re.Match[str]) -> str:
        nonlocal replaced
        original = match.group(0)
        resolved = resolve_live_url(original, text)
        if not resolved.startswith(DEEPLINK_PREFIX):
            return original
        replaced += 1
        return deeplink_hyperlink(resolved, original)

    return URL_PATTERN.sub(_sub, text), replaced


def replace_urls_in_html(
    html_text: str,
    *,
    resolved_deeplink: Optional[str] = None,
    source_url: Optional[str] = None,
) -> Tuple[str, int]:
    if not html_text:
        return html_text, 0

    replaced = 0
    context_deeplink = resolved_deeplink or resolve_deeplink_from_text(html_text)

    def _use_resolved_for_url(url: str) -> bool:
        if not resolved_deeplink:
            return False
        if source_url and url.strip() == source_url.strip():
            return True
        if "thanhtai.io" in url and "/r/" in url:
            code_match = re.search(r"/r/([A-Za-z0-9_-]+)", url)
            return bool(code_match and is_thanhtai_hex_code(code_match.group(1)))
        return False

    def _anchor_sub(match: re.Match[str]) -> str:
        nonlocal replaced
        url, inner = match.group(1), match.group(2)
        if _use_resolved_for_url(url):
            replaced += 1
            if _inner_looks_like_url(inner, url):
                return deeplink_hyperlink(resolved_deeplink, url)
            open_href = deeplink_open_href(resolved_deeplink).replace("&", "&amp;")
            return f'<a href="{open_href}">{inner}</a>'
        deeplink = resolve_live_url(url, html_text)
        if not deeplink.startswith(DEEPLINK_PREFIX):
            if (
                context_deeplink
                and "thanhtai.io" in url
                and _inner_looks_like_url(inner, url)
            ):
                replaced += 1
                return deeplink_hyperlink(context_deeplink, url)
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
        if _use_resolved_for_url(original):
            replaced += 1
            return deeplink_hyperlink(resolved_deeplink, original)
        deeplink = resolve_live_url(original, html_text)
        if not deeplink.startswith(DEEPLINK_PREFIX):
            return original
        replaced += 1
        return deeplink_hyperlink(deeplink, original)

    updated = URL_PATTERN.sub(_plain_sub, updated)
    return updated, replaced


def enrich_payload_with_deeplink(message_text: str, payload: dict) -> dict:
    enriched = dict(payload or {})
    if enriched.get("deeplink"):
        return enriched

    combined = message_text or ""
    if enriched.get("telegram_html"):
        combined = f"{combined}\n{enriched['telegram_html']}"

    room_id = extract_thanhtai_countdown_room_id(combined)
    if room_id:
        enriched["deeplink"] = f"{DEEPLINK_PREFIX}{room_id}"
        enriched["room_id"] = room_id
        hex_url = find_thanhtai_hex_url(combined)
        if hex_url:
            enriched.setdefault("source_url", hex_url)
        else:
            source_url = find_first_convertible_url(combined)
            if source_url:
                enriched.setdefault("source_url", source_url)
        return enriched

    hex_url = find_thanhtai_hex_url(combined)
    if hex_url:
        api_deeplink = resolve_via_deeplink_api(hex_url, hex_url)
        if api_deeplink:
            enriched["deeplink"] = api_deeplink
            enriched["source_url"] = hex_url
            room_id = extract_room_id(api_deeplink)
            if room_id:
                enriched["room_id"] = room_id
            return enriched

    deeplink = resolve_deeplink_from_text(combined)
    if not deeplink:
        source_url = find_first_convertible_url(combined)
        if source_url and "thanhtai.io" in source_url and "/r/" in source_url:
            deeplink = resolve_via_deeplink_api(source_url, combined)
    if not deeplink:
        return enriched

    enriched["deeplink"] = deeplink
    source_url = find_first_convertible_url(combined)
    if source_url:
        enriched.setdefault("source_url", source_url)
    room_id = extract_room_id(deeplink)
    if room_id:
        enriched.setdefault("room_id", room_id)
    return enriched


def build_thanhtai_countdown_url(room_id: str) -> str:
    clean = (room_id or "").strip()
    if not clean.isdigit():
        return ""
    encoded = base64.b64encode(clean.encode("ascii")).decode("ascii").rstrip("=")
    return f"https://thanhtai.io/countdow?data={encoded}"


def item_context_from_parts(message_text: str = "", payload: Optional[dict] = None) -> str:
    payload = payload or {}
    parts: list[str] = []
    message = (message_text or "").strip()
    if message:
        parts.append(message)
    telegram_html = str(payload.get("telegram_html") or "").strip()
    if telegram_html:
        parts.append(telegram_html)
    for key in ("url", "link", "live_url", "room_url", "source_url"):
        value = str(payload.get(key) or "").strip()
        if value:
            parts.append(value)
    return "\n".join(parts)


def resolve_deeplink_for_broadcast(message_text: str = "", payload: Optional[dict] = None) -> Optional[str]:
    """Same deeplink resolution as broadcast worker (replace_urls_in_html / enrich)."""
    payload = dict(payload or {})
    message_text = message_text or ""

    existing = str(payload.get("deeplink") or "").strip()
    if existing.startswith(DEEPLINK_PREFIX):
        return existing

    enriched = enrich_payload_with_deeplink(message_text, payload)
    pre_resolved = str(enriched.get("deeplink") or "").strip()
    if pre_resolved.startswith(DEEPLINK_PREFIX):
        return pre_resolved

    source_url = str(enriched.get("source_url") or payload.get("source_url") or "").strip() or None
    html_text = str(payload.get("telegram_html") or "").strip()
    if html_text:
        replace_urls_in_html(
            html_text,
            resolved_deeplink=pre_resolved if pre_resolved.startswith(DEEPLINK_PREFIX) else None,
            source_url=source_url,
        )
        for match in ANCHOR_PATTERN.finditer(html_text):
            url = normalize_url_href(match.group(1))
            if is_countdown_page_url(url):
                room_id = extract_thanhtai_countdown_room_id(url) or ""
                if room_id:
                    return f"{DEEPLINK_PREFIX}{room_id}"
            resolved = resolve_live_url(url, html_text)
            if resolved.startswith(DEEPLINK_PREFIX):
                return resolved
        for match in URL_PATTERN.finditer(html_text):
            if _is_inside_href(html_text, match.start()):
                continue
            resolved = resolve_live_url(match.group(0), html_text)
            if resolved.startswith(DEEPLINK_PREFIX):
                return resolved

    plain = (message_text or "").strip()
    if plain:
        converted, link_count = replace_urls_as_deeplink_hyperlinks(plain)
        if link_count:
            room_id = extract_room_id(converted)
            if room_id:
                return f"{DEEPLINK_PREFIX}{room_id}"

    combined = item_context_from_parts(message_text, payload)
    fallback = resolve_deeplink_from_text(combined)
    if fallback and fallback.startswith(DEEPLINK_PREFIX):
        return fallback
    return None


def resolve_link_for_open(url: str, context: str = "") -> dict[str, Any]:
    """Resolve queue link via profile_playwright API and build countdown open URL."""
    source_url = (url or "").strip()
    combined = (context or "").strip() or source_url
    if not source_url:
        return {"ok": False, "error": "Missing url"}

    if is_countdown_page_url(source_url):
        source_url = normalize_url_href(source_url)
        room_id = extract_thanhtai_countdown_room_id(source_url) or ""
        if not room_id and is_junb_box_countdown_url(source_url):
            deeplink_from_context = resolve_deeplink_from_text(combined) or ""
            room_id = extract_room_id(deeplink_from_context) or ""
        deeplink = f"{DEEPLINK_PREFIX}{room_id}" if room_id else ""
        return {
            "ok": True,
            "source_url": source_url,
            "deeplink": deeplink,
            "room_id": room_id,
            "countdown_url": source_url,
            "open_url": source_url,
        }

    deeplink = ""
    combined = (context or "").strip() or source_url
    resolved_source = find_first_convertible_url(combined) or source_url

    hex_url = find_thanhtai_hex_url(combined)
    if hex_url:
        api_deeplink = resolve_via_deeplink_api(hex_url, combined)
        if api_deeplink:
            deeplink = api_deeplink
            resolved_source = hex_url

    if not deeplink:
        deeplink = resolve_deeplink_from_text(combined) or ""

    if not deeplink and is_live_shortlink_url(source_url):
        api_deeplink = resolve_via_deeplink_api(source_url, combined)
        if api_deeplink:
            deeplink = api_deeplink
            resolved_source = source_url

    if not deeplink:
        candidate = resolve_live_url(source_url, combined)
        if candidate.startswith(DEEPLINK_PREFIX):
            deeplink = candidate

    room_id = extract_room_id(deeplink) if deeplink else ""
    countdown_url = resolve_countdown_open_url(combined, room_id=room_id)
    if not countdown_url and room_id:
        countdown_url = build_thanhtai_countdown_url(room_id)
    open_url = countdown_url or find_first_countdown_url(combined) or source_url

    if not countdown_url and not deeplink:
        return {
            "ok": False,
            "error": "Không giải mã được link qua profile_playwright",
            "source_url": source_url,
            "deeplink": "",
            "room_id": "",
            "countdown_url": "",
            "open_url": source_url,
        }

    return {
        "ok": True,
        "source_url": resolved_source,
        "deeplink": deeplink,
        "room_id": room_id,
        "countdown_url": countdown_url or open_url,
        "open_url": open_url,
    }
