import logging
import time

from logging_setup import setup_logging
from telegram import Bot

from chatbot import ChatbotService
from config import load_config
from db import ChatDatabase
from worker import QueueWorker


logger = logging.getLogger(__name__)


def main() -> None:
    config = load_config()
    setup_logging(config.log_level)

    if not config.token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN in .env before running broadcast worker")

    db = ChatDatabase(config.db_path)
    db.init_schema()
    db.seed_broadcast_bots_from_tokens(list(config.bot_tokens))
    db.delete_broadcast_bots_without_tokens()
    all_tokens = [token.strip() for token in config.bot_tokens if token.strip()]
    if not all_tokens:
        raise RuntimeError("No bot tokens in .env. Set TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKENS")

    primary_token = all_tokens[0]
    bots = [Bot(token) for token in all_tokens]
    chatbot = ChatbotService(reply_prefix=config.reply_prefix)

    # One logical queue per listening room: fair claim + N parallel workers.
    # Default 4 matches typical watch-group count; override with BOT_BROADCAST_WORKERS.
    worker_count = max(1, min(int(config.broadcast_workers), 16))
    workers = []
    for index in range(worker_count):
        worker = QueueWorker(
            db=db,
            chatbot=chatbot,
            bot=Bot(primary_token) if index == 0 else bots[index % len(bots)],
            bots=bots,
            lease_seconds=max(config.queue_lease_seconds, 120),
            poll_interval_seconds=min(config.queue_poll_interval_seconds, 0.02),
            retry_delay_seconds=config.queue_retry_delay_seconds,
            consumer_id=f"broadcast-worker-{index + 1}",
            prefer_fair=True,
            prefer_newest=False,
            skip_older_pending=config.broadcast_skip_older_pending,
            skip_older_after_seconds=config.broadcast_skip_older_after_seconds,
        )
        workers.append(worker)

    logger.warning(
        "Starting broadcast workers count=%s mode=fair-per-room db=%s bot_count=%s",
        worker_count,
        config.db_path,
        len(all_tokens),
    )
    for worker in workers:
        worker.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping broadcast workers")
    finally:
        for worker in workers:
            worker.stop()


if __name__ == "__main__":
    main()
