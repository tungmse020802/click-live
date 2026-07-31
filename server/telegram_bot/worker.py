import logging
import os
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

from telegram import Bot
from telegram.error import BadRequest, RetryAfter

from chatbot import ChatMessage, ChatbotService
from db import ChatDatabase, QueueJob
from logging_setup import setup_logging
from message_format import broadcast_text_from_payload


logger = logging.getLogger(__name__)


class QueueWorker:
    def __init__(
        self,
        db: ChatDatabase,
        chatbot: ChatbotService,
        bot: Bot,
        lease_seconds: int,
        poll_interval_seconds: float,
        retry_delay_seconds: int,
        consumer_id: Optional[str] = None,
        prefer_newest: bool = False,
        prefer_fair: bool = False,
        stale_skip_seconds: Optional[float] = None,
        bots: Optional[List[Bot]] = None,
    ):
        self.db = db
        self.chatbot = chatbot
        self.bot = bot
        self.bots = bots or [bot]
        self._bot_index = 0
        self._bot_lock = threading.Lock()
        self._bot_cache: dict[str, Bot] = {}
        self.lease_seconds = lease_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.retry_delay_seconds = retry_delay_seconds
        self.consumer_id = consumer_id or _default_consumer_id()
        self.prefer_newest = prefer_newest
        self.prefer_fair = prefer_fair
        self.stale_skip_seconds = stale_skip_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(
            target=self._run,
            name=f"queue-worker-{self.consumer_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        logger.warning("Queue worker started consumer_id=%s", self.consumer_id)

        while not self._stop_event.is_set():
            try:
                released = self.db.release_expired_jobs()
                if released:
                    logger.debug("Released expired queue jobs count=%s", released)

                if self.stale_skip_seconds:
                    skipped = self.db.skip_stale_pending_jobs(self.stale_skip_seconds)
                    if skipped:
                        logger.debug("Skipped stale pending queue jobs count=%s", skipped)

                if self.prefer_fair:
                    job = self.db.claim_next_fair(self.consumer_id, self.lease_seconds)
                elif self.prefer_newest:
                    job = self.db.claim_next_newest(self.consumer_id, self.lease_seconds)
                else:
                    job = self.db.claim_next(self.consumer_id, self.lease_seconds)
                if not job:
                    self._stop_event.wait(self.poll_interval_seconds)
                    continue

                self._process_job(job)
            except Exception:
                logger.exception("Queue worker loop failed")
                self._stop_event.wait(self.poll_interval_seconds)

        logger.warning("Queue worker stopped consumer_id=%s", self.consumer_id)

    def _process_job(self, job: QueueJob) -> None:
        logger.debug(
            "Processing queue job id=%s priority=%s attempt=%s/%s",
            job.id,
            job.priority,
            job.attempts,
            job.max_attempts,
        )

        try:
            if not self.db.is_job_lock_valid(job.id, self.consumer_id):
                logger.warning(
                    "Queue job lease expired before processing job_id=%s consumer_id=%s",
                    job.id,
                    self.consumer_id,
                )
                self.db.release_expired_jobs()
                return

            reply_transport = job.payload.get("reply_transport", "bot_api")
            if reply_transport == "none":
                self._complete_system_job(job, "processed without reply")
                return

            if reply_transport == "bot_broadcast":
                self._broadcast_job(job)
                return

            reply = self.chatbot.handle_text(
                ChatMessage(
                    text=job.message_text,
                    user_id=_safe_int(job.platform_user_id),
                    username=job.username,
                    chat_id=_safe_int(job.room_chat_id),
                )
            )

            if not self.db.is_job_lock_valid(job.id, self.consumer_id):
                logger.warning(
                    "Queue job lease expired before reply job_id=%s consumer_id=%s",
                    job.id,
                    self.consumer_id,
                )
                self.db.release_expired_jobs()
                return

            if reply_transport != "bot_api":
                raise RuntimeError(f"Unsupported reply_transport: {reply_transport}")

            sent_message = self.bot.send_message(
                chat_id=_telegram_chat_id(job),
                text=reply.text,
            )
            self.db.insert_chat_message(
                room_id=job.room_id,
                user_id=None,
                platform_message_id=str(sent_message.message_id),
                direction="outgoing",
                text=reply.text,
            )

            if not self.db.complete_job(job.id, self.consumer_id):
                logger.warning(
                    "Queue job was not completed because lease is no longer valid job_id=%s",
                    job.id,
                )
        except Exception as exc:
            logger.exception("Queue job failed job_id=%s", job.id)
            self.db.fail_job(
                job_id=job.id,
                consumer_id=self.consumer_id,
                error_message=str(exc),
                retry_delay_seconds=self.retry_delay_seconds,
            )

    def _broadcast_job(self, job: QueueJob) -> None:
        groups = self.db.list_enabled_broadcast_groups()
        if not groups:
            raise RuntimeError("No approved broadcast destination groups")

        text = (job.message_text or "").strip()
        if not text:
            raise RuntimeError("Broadcast job has empty message text")

        send_text, parse_mode = broadcast_text_from_payload(text, job.payload)
        target_room = str(job.payload.get("target_room") or job.room_chat_id or "").strip()
        has_bot_assignment = bool(self.db.get_bot_ids_for_watch_chat_id(target_room))
        bot_records = self.db.list_enabled_bots_for_watch_chat_id(target_room)
        active_bots = self._bots_from_records(bot_records, fallback=not has_bot_assignment)
        if not active_bots:
            raise RuntimeError(
                f"No enabled bots for watch_room={target_room or '-'} "
                f"(assigned={has_bot_assignment})"
            )
        logger.debug(
            "Broadcast job id=%s watch_room=%s bots=%s destinations=%s",
            job.id,
            target_room or "-",
            len(active_bots),
            len(groups),
        )
        sent_count, errors = self._send_broadcast(
            send_text,
            groups,
            parse_mode=parse_mode,
            bots=active_bots,
        )
        if sent_count == 0:
            raise RuntimeError("; ".join(errors) or "Broadcast failed for all groups")

        superseded = self.db.skip_older_pending_for_room(job.room_id, job.id)
        if superseded:
            logger.debug(
                "Superseded older pending jobs room_id=%s count=%s after job_id=%s",
                job.room_id,
                superseded,
                job.id,
            )

        note = f"broadcast sent={sent_count}/{len(groups)}"
        if errors:
            note = f"{note}; errors={' | '.join(errors)}"
        self._complete_system_job(job, note)

    def _send_broadcast(
        self,
        text: str,
        groups: List[dict],
        parse_mode: Optional[str] = None,
        bots: Optional[List[Bot]] = None,
    ) -> Tuple[int, List[str]]:
        active_bots = bots or self.bots
        if len(groups) <= 1 or len(active_bots) <= 1:
            return self._send_broadcast_sequential(
                text,
                groups,
                parse_mode=parse_mode,
                bots=active_bots,
            )

        sent_count = 0
        errors: List[str] = []
        max_workers = min(len(groups), len(active_bots), 12)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    self._send_to_group,
                    group,
                    text,
                    parse_mode,
                    active_bots,
                ): group
                for group in groups
            }
            for future in as_completed(futures):
                group = futures[future]
                name = str(group.get("name") or group.get("chat_id"))
                chat_id = group.get("chat_id")
                try:
                    future.result()
                    sent_count += 1
                    logger.debug(
                        "Broadcast sent group=%s chat_id=%s chars=%s",
                        name,
                        chat_id,
                        len(text),
                    )
                except Exception as exc:
                    message = f"{name}({chat_id}): {exc}"
                    errors.append(message)
                    logger.warning(
                        "Broadcast failed group=%s chat_id=%s error=%s",
                        name,
                        chat_id,
                        exc,
                    )
        return sent_count, errors

    def _send_to_group(
        self,
        group: dict,
        text: str,
        parse_mode: Optional[str] = None,
        bots: Optional[List[Bot]] = None,
    ) -> None:
        chat_id = _safe_int(group.get("chat_id"))
        active_bots = bots or self.bots
        last_exc: Optional[Exception] = None
        for _ in range(len(active_bots)):
            bot = self._next_bot(active_bots)
            try:
                self._send_with_flood_retry(bot, chat_id, text, parse_mode=parse_mode)
                return
            except BadRequest as exc:
                if _is_missing_chat_error(exc):
                    last_exc = exc
                    continue
                raise
        if last_exc is not None:
            raise last_exc

    def _next_bot(self, bots: Optional[List[Bot]] = None) -> Bot:
        active_bots = bots or self.bots
        with self._bot_lock:
            bot = active_bots[self._bot_index % len(active_bots)]
            self._bot_index += 1
            return bot

    def _bots_from_records(self, records: List[dict], *, fallback: bool = True) -> List[Bot]:
        bots: List[Bot] = []
        for record in records:
            token = str(record.get("token") or "").strip()
            if not token:
                continue
            cached = self._bot_cache.get(token)
            if cached is None:
                cached = Bot(token)
                self._bot_cache[token] = cached
            bots.append(cached)
        if bots:
            return bots
        return self.bots if fallback else []

    def _send_broadcast_sequential(
        self,
        text: str,
        groups: List[dict],
        parse_mode: Optional[str] = None,
        bots: Optional[List[Bot]] = None,
    ) -> Tuple[int, List[str]]:
        active_bots = bots or self.bots
        sent_count = 0
        errors: List[str] = []
        for group in groups:
            chat_id = _safe_int(group.get("chat_id"))
            name = str(group.get("name") or chat_id)
            try:
                self._send_to_group(group, text, parse_mode=parse_mode, bots=active_bots)
                sent_count += 1
                logger.debug(
                    "Broadcast sent group=%s chat_id=%s chars=%s",
                    name,
                    chat_id,
                    len(text),
                )
            except Exception as exc:
                message = f"{name}({chat_id}): {exc}"
                errors.append(message)
                logger.warning("Broadcast failed group=%s chat_id=%s error=%s", name, chat_id, exc)
        return sent_count, errors

    def _send_with_flood_retry(
        self,
        bot: Bot,
        chat_id: int,
        text: str,
        parse_mode: Optional[str] = None,
        max_attempts: int = 4,
    ) -> None:
        for attempt in range(max_attempts):
            try:
                kwargs = {"chat_id": chat_id, "text": text}
                if parse_mode:
                    kwargs["parse_mode"] = parse_mode
                bot.send_message(**kwargs)
                return
            except RetryAfter as exc:
                wait_seconds = float(getattr(exc, "retry_after", 1.0)) + 0.5
                logger.warning(
                    "Broadcast flood wait %.1fs chat_id=%s attempt=%s/%s",
                    wait_seconds,
                    chat_id,
                    attempt + 1,
                    max_attempts,
                )
                if attempt + 1 >= max_attempts:
                    raise
                time.sleep(wait_seconds)

    def _complete_system_job(self, job: QueueJob, note: str) -> None:
        self.db.insert_chat_message(
            room_id=job.room_id,
            user_id=None,
            platform_message_id=None,
            direction="system",
            text=note,
        )
        if not self.db.complete_job(job.id, self.consumer_id):
            logger.warning(
                "Queue job was not completed because lease is no longer valid job_id=%s",
                job.id,
            )


def _telegram_chat_id(job: QueueJob) -> int:
    return _safe_int(job.payload.get("telegram_chat_id") or job.room_chat_id)


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _default_consumer_id() -> str:
    host = socket.gethostname()
    pid = os.getpid()
    suffix = uuid.uuid4().hex[:8]
    return f"{host}-{pid}-{suffix}"


def _is_missing_chat_error(exc: BadRequest) -> bool:
    message = str(exc).lower()
    return (
        "chat not found" in message
        or "bot was kicked" in message
        or "group chat was upgraded" in message
    )
