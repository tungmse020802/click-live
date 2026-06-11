import logging
import os
import socket
import threading
import time
import uuid
from typing import Optional

from telegram import Bot

from chatbot import ChatMessage, ChatbotService
from db import ChatDatabase, QueueJob


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
    ):
        self.db = db
        self.chatbot = chatbot
        self.bot = bot
        self.lease_seconds = lease_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.retry_delay_seconds = retry_delay_seconds
        self.consumer_id = consumer_id or _default_consumer_id()
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
        logger.info("Queue worker started consumer_id=%s", self.consumer_id)

        while not self._stop_event.is_set():
            try:
                released = self.db.release_expired_jobs()
                if released:
                    logger.info("Released expired queue jobs count=%s", released)

                job = self.db.claim_next(self.consumer_id, self.lease_seconds)
                if not job:
                    self._stop_event.wait(self.poll_interval_seconds)
                    continue

                self._process_job(job)
            except Exception:
                logger.exception("Queue worker loop failed")
                self._stop_event.wait(self.poll_interval_seconds)

        logger.info("Queue worker stopped consumer_id=%s", self.consumer_id)

    def _process_job(self, job: QueueJob) -> None:
        logger.info(
            "Processing queue job id=%s priority=%s attempt=%s/%s",
            job.id,
            job.priority,
            job.attempts,
            job.max_attempts,
        )

        try:
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

            reply_transport = job.payload.get("reply_transport", "bot_api")
            if reply_transport == "none":
                self.db.insert_chat_message(
                    room_id=job.room_id,
                    user_id=None,
                    platform_message_id=None,
                    direction="system",
                    text=reply.text,
                )
                if not self.db.complete_job(job.id, self.consumer_id):
                    logger.warning(
                        "Queue job was not completed because lease is no longer valid job_id=%s",
                        job.id,
                    )
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
