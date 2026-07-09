import logging

from telegram import Bot

from chatbot import ChatbotService
from config import load_config
from db import ChatDatabase
from worker import QueueWorker


logger = logging.getLogger(__name__)


def setup_logging(log_level: str) -> None:
    level = getattr(logging, log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def main() -> None:
    config = load_config()
    setup_logging(config.log_level)

    if not config.token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN in .env before running broadcast worker")

    db = ChatDatabase(config.db_path)
    db.init_schema()

    worker = QueueWorker(
        db=db,
        chatbot=ChatbotService(reply_prefix=config.reply_prefix),
        bot=Bot(config.token),
        bots=[Bot(token) for token in config.bot_tokens],
        lease_seconds=max(config.queue_lease_seconds, 120),
        poll_interval_seconds=min(config.queue_poll_interval_seconds, 0.02),
        retry_delay_seconds=config.queue_retry_delay_seconds,
        consumer_id="broadcast-worker",
        prefer_fair=True,
    )

    logger.info(
        "Starting broadcast worker db=%s bot_count=%s",
        config.db_path,
        len(config.bot_tokens),
    )
    worker.start()
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping broadcast worker")
    finally:
        worker.stop()


if __name__ == "__main__":
    main()
