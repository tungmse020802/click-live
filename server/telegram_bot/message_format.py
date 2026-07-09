from typing import Optional, Tuple

from telethon.extensions import html
from telethon.tl.custom.message import Message

from deeplink_resolve import replace_urls_as_deeplink_hyperlinks, replace_urls_in_html


def telethon_message_to_html(message: Message) -> Optional[str]:
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
