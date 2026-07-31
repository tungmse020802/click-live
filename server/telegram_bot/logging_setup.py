import logging
import os

NOISY_LOGGERS = (
    "telethon",
    "telegram",
    "telegram.ext",
    "telegram.vendor",
    "telegram.vendor.ptb_urllib3.urllib3.connectionpool",
    "urllib3.connectionpool",
    "httpx",
    "httpcore",
    "asyncio",
)


def setup_logging(log_level: str | None = None) -> None:
    level_name = (log_level or os.environ.get("BOT_LOG_LEVEL", "ERROR")).strip().upper()
    level = getattr(logging, level_name, logging.ERROR)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=True,
    )

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.ERROR)
