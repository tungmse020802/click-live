import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from telethon import TelegramClient, events
from telethon.tl.custom.message import Message

from config import TelegramClientConfig, TelegramClientTarget, load_telegram_client_config
from db import ChatDatabase
from message_filter import MessageFilterEngine, parse_box_signal


logger = logging.getLogger(__name__)

PLATFORM = "telegram_web"
TRANSPORT = "telegram_client"


class TelethonReader:
    def __init__(self, config: TelegramClientConfig, db: ChatDatabase):
        self.config = config
        self.db = db
        self.room_ids: Dict[str, int] = {}
        self.entity_to_target: Dict[int, TelegramClientTarget] = {}
        self._unknown_chat_ids_logged: Set[int] = set()
        self._last_prune_at = 0.0
        self.filter_engine = MessageFilterEngine(
            enabled=config.filter_enabled,
            config_path=config.filter_config_path,
            reload_seconds=config.filter_reload_seconds,
            default_priority=config.queue_default_priority,
        )

    async def run(self) -> None:
        self.db.init_schema()
        self._prune_queue(force=True)

        while True:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Telegram client reader crashed; reconnecting soon")

            logger.warning("Telegram client reader disconnected; reconnecting in 5s")
            await asyncio.sleep(5)

    async def _run_once(self) -> None:
        client = TelegramClient(
            self.config.session_path,
            self.config.api_id,
            self.config.api_hash,
        )

        await client.connect()
        try:
            if not await client.is_user_authorized():
                if not self.config.phone:
                    raise RuntimeError("Set TELEGRAM_PHONE in .env for first login")
                logger.info("Starting Telegram login phone=%s", _mask_phone(self.config.phone))
                await client.start(phone=self.config.phone)

            entities = []
            watch_targets: List[Tuple[TelegramClientTarget, Any, int]] = []
            for target in self.config.targets:
                entity = await client.get_entity(_entity_ref_value(target.entity_ref))
                peer_id = _marked_peer_id(entity)
                if peer_id in self.entity_to_target:
                    logger.info(
                        "Skipping duplicate Telegram client target label=%s room=%s already_label=%s",
                        target.label,
                        target.room_key,
                        self.entity_to_target[peer_id].label,
                    )
                    continue

                for alias_id in _peer_id_aliases(peer_id):
                    self.entity_to_target[alias_id] = target
                entities.append(entity)
                watch_targets.append((target, entity, peer_id))
                title = _entity_title(entity) or target.label
                self.room_ids[target.room_key] = self.db.upsert_chat_room(
                    platform=PLATFORM,
                    chat_id=target.room_key,
                    chat_type="client",
                    title=title,
                )
                logger.info(
                    "Watching Telegram target label=%s room=%s entity=%s title=%r",
                    target.label,
                    target.room_key,
                    peer_id,
                    title,
                )

            if not entities:
                raise RuntimeError("No Telegram client targets configured")

            @client.on(events.NewMessage())
            async def on_new_message(event) -> None:
                try:
                    await self._handle_message(event.message, event.chat_id)
                except Exception:
                    logger.exception("Failed to handle Telegram client message chat_id=%s", event.chat_id)

            logger.info("Telegram client reader ready targets=%s", len(entities))
            heartbeat_task = asyncio.create_task(self._heartbeat(client, len(entities)))
            history_poll_task = asyncio.create_task(self._poll_history(client, watch_targets))
            try:
                await client.run_until_disconnected()
            finally:
                heartbeat_task.cancel()
                history_poll_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
                try:
                    await history_poll_task
                except asyncio.CancelledError:
                    pass
        finally:
            await client.disconnect()

    async def _heartbeat(self, client: TelegramClient, target_count: int) -> None:
        while True:
            await asyncio.sleep(60)
            logger.info(
                "Telegram client reader heartbeat connected=%s targets=%s",
                client.is_connected(),
                target_count,
            )

    async def _poll_history(
        self,
        client: TelegramClient,
        watch_targets: List[Tuple[TelegramClientTarget, Any, int]],
    ) -> None:
        while True:
            for target, entity, peer_id in watch_targets:
                try:
                    messages = []
                    async for message in client.iter_messages(
                        entity,
                        limit=self.config.history_poll_limit,
                    ):
                        messages.append(message)
                    for message in reversed(messages):
                        await self._handle_message(message, peer_id)
                except Exception:
                    logger.exception("Failed to poll Telegram history target=%s", target.label)
            await asyncio.sleep(self.config.history_poll_seconds)

    async def _handle_message(self, message: Message, event_chat_id: Optional[int]) -> None:
        text = (message.raw_text or "").strip()
        if not text:
            return

        target = self._target_for_message(message, event_chat_id)
        if target is None:
            for raw_id in _message_chat_ids(message, event_chat_id):
                if raw_id not in self._unknown_chat_ids_logged:
                    self._unknown_chat_ids_logged.add(raw_id)
                    logger.info("Skipping Telegram message for unknown chat_id=%s", raw_id)
            return

        if message.out and not self.config.include_outgoing:
            logger.info(
                "Skipping outgoing Telegram client message room=%s message=%s include_outgoing=false",
                target.room_key,
                message.id,
            )
            return

        timestamp_ms = _message_timestamp_ms(message.date)
        if not _is_recent_message(timestamp_ms, self.config.queue_max_age_seconds):
            logger.info(
                "Skipped stale Telegram client message room=%s message=%s timestamp_ms=%s",
                target.room_key,
                message.id,
                timestamp_ms,
            )
            return

        signal = parse_box_signal(text)
        filter_result = self.filter_engine.evaluate(text, signal)
        if not filter_result.matched:
            logger.debug(
                "Skipped Telegram client message room=%s message=%s reason=%s",
                target.room_key,
                message.id,
                filter_result.reason,
            )
            return

        sender = await message.get_sender()
        user_id = None
        if sender is not None and not message.out:
            sender_id = str(getattr(sender, "id", "") or "")
            sender_name = _sender_name(sender)
            user_id = self.db.upsert_chat_user(
                platform=PLATFORM,
                user_id=f"{target.room_key}:{sender_id or sender_name}",
                username=getattr(sender, "username", None) or sender_name,
                first_name=getattr(sender, "first_name", None) or sender_name,
                last_name=getattr(sender, "last_name", None),
            )

        room_id = self.room_ids[target.room_key]
        direction = "outgoing" if message.out else "incoming"
        platform_message_id = f"{target.room_key}:{message.id}"
        chat_message_id = self.db.insert_chat_message_if_new(
            room_id=room_id,
            user_id=user_id,
            platform_message_id=platform_message_id,
            direction=direction,
            text=text,
        )
        if chat_message_id is None:
            return

        if direction == "incoming" and self.config.enqueue:
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
                    "source_transport": TRANSPORT,
                    "reply_transport": "none",
                    "target_label": target.label,
                    "target_url": _target_web_url(target.room_key),
                    "message_key": platform_message_id,
                    "target_room": target.room_key,
                    "entity_ref": target.entity_ref,
                    "telegram_message_id": message.id,
                    "telegram_timestamp_ms": timestamp_ms,
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
            logger.info(
                "Enqueued Telegram client message room=%s message=%s queue=%s",
                target.room_key,
                message.id,
                queue_id,
            )
            self._prune_queue()

    def _target_for_message(
        self,
        message: Message,
        event_chat_id: Optional[int],
    ) -> Optional[TelegramClientTarget]:
        for raw_id in _message_chat_ids(message, event_chat_id):
            for alias_id in _peer_id_aliases(raw_id):
                target = self.entity_to_target.get(alias_id)
                if target is not None:
                    return target
        return None

    def _prune_queue(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_prune_at < 30:
            return
        self._last_prune_at = now

        ttl_deleted = self.db.prune_queue_older_than(self.config.queue_ttl_seconds)
        size_deleted = self.db.prune_queue(self.config.queue_max_items)
        deleted = {
            "queue": ttl_deleted["queue"] + size_deleted["queue"],
            "messages": ttl_deleted["messages"] + size_deleted["messages"],
        }
        if deleted["queue"] or deleted["messages"]:
            logger.info(
                "Pruned queue queue=%s messages=%s ttl=%ss max_items=%s",
                deleted["queue"],
                deleted["messages"],
                self.config.queue_ttl_seconds,
                self.config.queue_max_items,
            )


def setup_logging(log_level: str) -> None:
    level = getattr(logging, log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _entity_ref_value(entity_ref: str):
    if entity_ref.lstrip("-").isdigit():
        return int(entity_ref)
    return entity_ref


def _marked_peer_id(entity) -> int:
    entity_id = int(getattr(entity, "id"))
    if getattr(entity, "megagroup", False) or entity.__class__.__name__ == "Channel":
        return int(f"-100{entity_id}")
    if entity.__class__.__name__ == "Chat":
        return -entity_id
    return entity_id


def _message_chat_ids(message: Message, event_chat_id: Optional[int]) -> List[int]:
    ids: List[int] = []
    for raw_id in (event_chat_id, message.chat_id):
        if raw_id is None:
            continue
        chat_id = int(raw_id)
        if chat_id not in ids:
            ids.append(chat_id)
    return ids


def _peer_id_aliases(peer_id: int) -> List[int]:
    aliases = [peer_id]
    peer_text = str(peer_id)
    if peer_text.startswith("-100") and len(peer_text) > 4:
        aliases.append(-int(peer_text[4:]))
    elif peer_id < 0:
        aliases.append(-int(f"100{abs(peer_id)}"))
    elif peer_id > 0:
        aliases.append(-int(f"100{peer_id}"))
    return list(dict.fromkeys(aliases))


def _entity_title(entity) -> str:
    return (
        getattr(entity, "title", None)
        or getattr(entity, "username", None)
        or "Telegram"
    )


def _sender_name(sender) -> str:
    parts = [
        getattr(sender, "first_name", None),
        getattr(sender, "last_name", None),
    ]
    name = " ".join(part for part in parts if part).strip()
    return name or getattr(sender, "username", None) or str(getattr(sender, "id", ""))


def _message_timestamp_ms(value: Optional[datetime]) -> Optional[int]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


def _target_web_url(room_key: str) -> str:
    return "https://web.telegram.org/k/#" + room_key


def _is_recent_message(
    timestamp_ms: Optional[int],
    max_age_seconds: int,
    now_ms: Optional[int] = None,
) -> bool:
    if timestamp_ms is None:
        return False
    current_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    age_ms = current_ms - timestamp_ms
    return 0 <= age_ms <= max_age_seconds * 1000


def _mask_phone(phone: str) -> str:
    if len(phone) <= 4:
        return "***"
    return phone[:3] + "***" + phone[-2:]


async def async_main() -> None:
    config = load_telegram_client_config()
    setup_logging(config.log_level)
    logger.info("Starting Telegram client reader session=%s", config.session_path)
    reader = TelethonReader(config=config, db=ChatDatabase(config.db_path))
    await reader.run()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
