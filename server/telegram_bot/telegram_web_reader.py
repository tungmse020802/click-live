import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from playwright.sync_api import Page, sync_playwright

from config import TelegramWebTarget, WebReaderConfig, load_web_reader_config
from db import ChatDatabase
from message_filter import BoxSignal, MessageFilterEngine, parse_box_signal


logger = logging.getLogger(__name__)

PLATFORM = "telegram_web"

MESSAGE_EXTRACTOR_JS = """
(limit) => {
  const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const attr = (el, names) => {
    for (const name of names) {
      const value = el.getAttribute(name);
      if (value) return value;
    }
    return '';
  };
  const textFromNode = (node) => {
    if (!node) return '';

    const clone = node.cloneNode(true);
    clone.querySelectorAll([
      'time',
      '.time',
      '.message-time',
      '.message-date',
      '.edited',
      '.reactions',
      '.quick-reaction',
      '.peer-title',
      '.bubble-name-rank',
      '.colored-name',
      '.name'
    ].join(',')).forEach((child) => child.remove());

    return normalize(clone.innerText)
      .replace(/\\s+\\d{1,2}:\\d{2}\\s?(AM|PM)$/i, '')
      .trim();
  };
  const messageText = (el) => {
    const candidates = [
      el.querySelector('.message .translatable-message'),
      el.querySelector('.message .text-content'),
      el.querySelector('.message .message-text'),
      el.querySelector('.message'),
      el.querySelector('.text-content'),
      el.querySelector('.message-text'),
      el.querySelector('.translatable-message')
    ];

    for (const candidate of candidates) {
      const text = textFromNode(candidate);
      if (text) return text;
    }

    return textFromNode(el);
  };

  const primary = Array.from(document.querySelectorAll(
    '[data-mid], [data-message-id], [data-message-id-id]'
  ));
  const fallback = Array.from(document.querySelectorAll(
    '.Message, .message, .message-list-item, [class*="message"]'
  ));
  const nodes = primary.length ? primary : fallback;
  const uniqueNodes = [];
  const seen = new Set();

  for (const node of nodes) {
    if (!node || seen.has(node)) continue;
    seen.add(node);
    uniqueNodes.push(node);
  }

  return uniqueNodes.slice(-limit).map((el, index) => {
    const timeNode = el.querySelector('time, .time, [datetime]');
    const senderNode = el.querySelector(
      '.colored-name .peer-title, .peer-title.bubble-name-first, .message-title, .sender-title'
    );
    const className = String(el.className || '');
    const text = messageText(el);
    const timestamp = attr(timeNode || el, ['datetime', 'title', 'aria-label']);
    const senderName = normalize(senderNode ? senderNode.innerText : '');
    const outgoing = /(^|\\s)(own|out|is-out|message-out)(\\s|$)/i.test(className)
      || Boolean(el.closest('.own, .is-out, .message-out'));
    const messageKey = attr(el, [
      'data-mid',
      'data-message-id',
      'data-message-id-id',
      'data-id',
      'id',
    ]);

    return {
      index,
      message_key: messageKey,
      text,
      sender_name: senderName,
      timestamp,
      outgoing,
    };
  }).filter((item) => item.text);
}
"""

TITLE_EXTRACTOR_JS = """
() => {
  const selectors = [
    'header [dir="auto"]',
    '.chat-info .title',
    '.topbar .title',
    '[class*="ChatInfo"] [dir="auto"]',
    '[class*="chat"] [class*="title"]'
  ];

  for (const selector of selectors) {
    const node = document.querySelector(selector);
    const text = node && node.innerText && node.innerText.trim();
    if (text) return text;
  }

  return document.title || '';
}
"""


SCROLL_TO_LATEST_JS = """
() => {
  const selectors = [
    '#column-center .scrollable-y',
    '#column-center .scrollable',
    '#column-center [class*="scrollable"]',
    '.bubbles-inner',
    '.bubbles',
    '.chat',
    'main'
  ];
  let changed = false;

  for (const selector of selectors) {
    for (const node of document.querySelectorAll(selector)) {
      if (!node || node.scrollHeight <= node.clientHeight) continue;
      const before = node.scrollTop;
      node.scrollTop = node.scrollHeight;
      changed = changed || node.scrollTop !== before;
    }
  }

  window.scrollTo(0, document.body.scrollHeight);
  return changed;
}
"""


@dataclass(frozen=True)
class WebMessage:
    key: str
    text: str
    sender_name: Optional[str]
    is_outgoing: bool
    signal: Optional[BoxSignal]


@dataclass
class TargetPage:
    target: TelegramWebTarget
    page: Page


class TelegramWebReader:
    def __init__(self, config: WebReaderConfig, db: ChatDatabase):
        self.config = config
        self.db = db
        self.seen_keys: Dict[str, Set[str]] = {}
        self.initialized_rooms: Set[str] = set()
        self.room_ids: Dict[str, int] = {}
        self.filter_engine = MessageFilterEngine(
            enabled=config.telegram_web_filter_enabled,
            config_path=config.telegram_web_filter_config_path,
            reload_seconds=config.telegram_web_filter_reload_seconds,
            default_priority=config.queue_default_priority,
        )

    def run(self) -> None:
        self.db.init_schema()

        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=self.config.telegram_web_profile_dir,
                headless=self.config.telegram_web_headless,
                viewport={"width": 1440, "height": 960},
            )

            try:
                pages = self._open_pages(context)
                self._poll_pages(pages)
            finally:
                context.close()

    def _open_pages(self, context) -> List[TargetPage]:
        targets = self.config.telegram_web_targets
        if not targets:
            targets = [
                TelegramWebTarget(
                    label="active-chat",
                    url=self.config.telegram_web_url,
                    room_key="active-chat",
                )
            ]

        pages = []
        for index, target in enumerate(targets):
            page = context.pages[index] if index < len(context.pages) else context.new_page()
            logger.info("Opening Telegram Web target label=%s url=%s", target.label, target.url)
            page.goto(target.url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            pages.append(TargetPage(target=target, page=page))

        logger.info(
            "Telegram Web reader ready. If login is required, complete it in the opened browser."
        )
        return pages

    def _poll_pages(self, pages: List[TargetPage]) -> None:
        logger.info("Polling Telegram Web messages targets=%s", len(pages))

        while True:
            for target_page in pages:
                try:
                    self._scan_page(target_page)
                except Exception:
                    logger.exception("Failed to scan Telegram Web target=%s", target_page.target.label)

            time.sleep(self.config.telegram_web_poll_interval_seconds)

    def _scan_page(self, target_page: TargetPage) -> None:
        page = target_page.page
        target = target_page.target
        self._scroll_to_latest(page)
        room_key = self._room_key(page, target)
        room_id = self._room_id(page, target, room_key)

        messages = self._read_messages(page, room_key)
        if not messages:
            return

        room_seen = self.seen_keys.setdefault(room_key, set())
        is_first_scan = room_key not in self.initialized_rooms
        inserted_count = 0

        for message in messages:
            if message.key in room_seen:
                continue
            room_seen.add(message.key)

            if is_first_scan and self.config.telegram_web_skip_existing_on_start:
                continue

            if message.is_outgoing and not self.config.telegram_web_include_outgoing:
                continue

            filter_result = self.filter_engine.evaluate(message.text, message.signal)
            if not filter_result.matched:
                logger.debug(
                    "Skipped Telegram Web message room=%s message=%s reason=%s",
                    room_key,
                    message.key,
                    filter_result.reason,
                )
                continue

            user_id = None
            if message.sender_name and not message.is_outgoing:
                user_id = self.db.upsert_chat_user(
                    platform=PLATFORM,
                    user_id=f"{room_key}:{message.sender_name}",
                    username=message.sender_name,
                    first_name=message.sender_name,
                    last_name=None,
                )

            direction = "outgoing" if message.is_outgoing else "incoming"
            chat_message_id = self.db.insert_chat_message_if_new(
                room_id=room_id,
                user_id=user_id,
                platform_message_id=message.key,
                direction=direction,
                text=message.text,
            )
            if chat_message_id is None:
                continue

            inserted_count += 1
            if direction == "incoming" and self.config.telegram_web_enqueue:
                queue_priority = (
                    filter_result.priority
                    if filter_result.priority is not None
                    else self.config.queue_default_priority
                )
                queue_id = self.db.enqueue_message(
                    message_id=chat_message_id,
                    room_id=room_id,
                    priority=queue_priority,
                    payload={
                        "source": PLATFORM,
                        "reply_transport": "none",
                        "target_label": target.label,
                        "target_url": target.url,
                        "message_key": message.key,
                        "matched_filter": (
                            filter_result.rule.to_payload(self.config.queue_default_priority)
                            if filter_result.rule is not None
                            else None
                        ),
                        "box_signal": (
                            filter_result.signal.to_payload()
                            if filter_result.signal is not None
                            else None
                        ),
                    },
                    max_attempts=self.config.queue_max_attempts,
                )
                logger.debug(
                    "Stored Telegram Web message room=%s message=%s queue=%s",
                    room_key,
                    message.key,
                    queue_id,
                )

        self.initialized_rooms.add(room_key)
        if inserted_count:
            logger.info("Inserted Telegram Web messages room=%s count=%s", room_key, inserted_count)

    def _read_messages(self, page: Page, room_key: str) -> List[WebMessage]:
        raw_items = page.evaluate(MESSAGE_EXTRACTOR_JS, self.config.telegram_web_message_scan_limit)
        messages = []
        for index, item in enumerate(raw_items):
            text = str(item.get("text") or "").strip()
            if not text:
                continue

            key = self._message_key(room_key, item, index)
            messages.append(
                WebMessage(
                    key=key,
                    text=text,
                    sender_name=(item.get("sender_name") or None),
                    is_outgoing=bool(item.get("outgoing")),
                    signal=parse_box_signal(text),
                )
            )

        return messages

    def _read_title(self, page: Page) -> str:
        try:
            title = page.evaluate(TITLE_EXTRACTOR_JS)
            title = str(title or "").strip()
            if "\n" in title or len(title) > 80:
                return ""
            return title
        except Exception:
            return ""

    def _scroll_to_latest(self, page: Page) -> None:
        try:
            changed = page.evaluate(SCROLL_TO_LATEST_JS)
            if changed:
                page.wait_for_timeout(35)
        except Exception:
            logger.debug("Could not scroll Telegram Web to latest", exc_info=True)

    def _room_id(self, page: Page, target: TelegramWebTarget, room_key: str) -> int:
        room_id = self.room_ids.get(room_key)
        if room_id is not None:
            return room_id

        title = self._read_title(page) or target.label
        room_id = self.db.upsert_chat_room(
            platform=PLATFORM,
            chat_id=room_key,
            chat_type="web",
            title=title,
        )
        self.room_ids[room_key] = room_id
        return room_id

    def _room_key(self, page: Page, target: TelegramWebTarget) -> str:
        if target.room_key != "active-chat":
            return target.room_key

        if "#" in page.url:
            value = page.url.split("#", 1)[1].strip()
            if value:
                return value

        title = self._read_title(page)
        return _hash_key(title or target.label)

    def _message_key(self, room_key: str, item: dict, index: int) -> str:
        raw_key = str(item.get("message_key") or "").strip()
        if raw_key:
            return raw_key

        fingerprint = "|".join(
            [
                room_key,
                str(item.get("sender_name") or ""),
                str(item.get("timestamp") or ""),
                str(item.get("text") or ""),
                str(index),
            ]
        )
        return _hash_key(fingerprint)


def setup_logging(log_level: str) -> None:
    level = getattr(logging, log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> None:
    config = load_web_reader_config()
    setup_logging(config.log_level)

    logger.info("Starting Telegram Web reader profile=%s", config.telegram_web_profile_dir)
    reader = TelegramWebReader(
        config=config,
        db=ChatDatabase(config.db_path),
    )
    reader.run()


if __name__ == "__main__":
    main()
