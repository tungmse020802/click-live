from typing import Optional, Tuple

from deeplink_resolve import (
    replace_urls_as_deeplink_hyperlinks,
    replace_urls_in_html,
    replace_urls_in_html_for_queue_display,
)


def telethon_message_to_html(message) -> Optional[str]:
    from telethon.extensions import html

    text = message.message or message.raw_text or ""
    entities = message.entities
    if not text or not entities:
        return None
    return html.unparse(text, entities)


def broadcast_text_from_payload(message_text: str, payload: dict) -> Tuple[str, Optional[str]]:
    html_text = str(payload.get("telegram_html") or "").strip()
    if html_text:
        converted, _ = replace_urls_in_html(html_text)
        return converted, "HTML"

    plain = (message_text or "").strip()
    converted, link_count = replace_urls_as_deeplink_hyperlinks(plain)
    if link_count:
        return converted, "HTML"
    return plain, None


def queue_display_from_payload(message_text: str, payload: dict) -> Tuple[str, Optional[str]]:
    """Queue UI: hiển thị link đã giải mã giống bot broadcast."""
    return broadcast_text_from_payload(message_text, payload)
