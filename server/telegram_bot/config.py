import os
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, List, Optional, Tuple

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class BotConfig:
    token: str
    mode: str
    log_level: str
    allowed_user_ids: FrozenSet[int]
    reply_prefix: str
    db_path: str
    worker_enabled: bool
    queue_ack: bool
    queue_default_priority: int
    queue_lease_seconds: int
    queue_poll_interval_seconds: float
    queue_max_attempts: int
    queue_retry_delay_seconds: int


@dataclass(frozen=True)
class TelegramWebTarget:
    label: str
    url: str
    room_key: str


@dataclass(frozen=True)
class WebReaderConfig:
    log_level: str
    db_path: str
    queue_default_priority: int
    queue_max_attempts: int
    queue_max_items: int
    telegram_web_url: str
    telegram_web_profile_dir: str
    telegram_web_headless: bool
    telegram_web_targets: List[TelegramWebTarget]
    telegram_web_poll_interval_seconds: float
    telegram_web_reload_seconds: int
    telegram_web_message_scan_limit: int
    telegram_web_queue_max_age_seconds: int
    telegram_web_enqueue: bool
    telegram_web_skip_existing_on_start: bool
    telegram_web_include_outgoing: bool
    telegram_web_filter_enabled: bool
    telegram_web_filter_config_path: str
    telegram_web_filter_reload_seconds: float


@dataclass(frozen=True)
class QueueJsonConfig:
    log_level: str
    db_path: str
    output_path: str
    poll_interval_seconds: float
    limit: int
    statuses: Tuple[str, ...]
    pretty: bool


@dataclass(frozen=True)
class QueueUiConfig:
    log_level: str
    db_path: str
    host: str
    port: int
    limit: int
    refresh_seconds: float
    queue_lease_seconds: int
    queue_retry_delay_seconds: int
    filter_config_path: str


def _parse_user_ids(raw_value: str) -> FrozenSet[int]:
    user_ids = set()

    for value in raw_value.split(","):
        value = value.strip()
        if not value:
            continue

        try:
            user_ids.add(int(value))
        except ValueError as exc:
            raise RuntimeError(
                "BOT_ALLOWED_USER_IDS must be a comma-separated list of numeric Telegram user IDs"
            ) from exc

    return frozenset(user_ids)


def _parse_bool(raw_value: str, default: bool) -> bool:
    value = raw_value.strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise RuntimeError(f"Invalid boolean value: {raw_value}")


def _parse_int(name: str, default: int, min_value: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc

    if value < min_value:
        raise RuntimeError(f"{name} must be >= {min_value}")
    return value


def _parse_float(name: str, default: float, min_value: float) -> float:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default

    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc

    if value < min_value:
        raise RuntimeError(f"{name} must be >= {min_value}")
    return value


def _resolve_path(raw_value: str, default: str) -> str:
    value = raw_value.strip() or default
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path)


def _parse_web_targets(raw_value: str, base_url: str) -> List[TelegramWebTarget]:
    targets = []

    for raw_target in raw_value.split(";"):
        raw_target = raw_target.strip()
        if not raw_target:
            continue

        label: Optional[str] = None
        url = raw_target
        if "|" in raw_target:
            label, url = [value.strip() for value in raw_target.split("|", 1)]

        if url.startswith("#"):
            url = base_url.rstrip("/") + "/" + url

        room_key = _room_key_from_url(url) or (label or url)
        targets.append(
            TelegramWebTarget(
                label=label or room_key,
                url=url,
                room_key=room_key,
            )
        )

    return targets


def _parse_csv(raw_value: str) -> Tuple[str, ...]:
    return tuple(value.strip() for value in raw_value.split(",") if value.strip())


def _room_key_from_url(url: str) -> str:
    if "#" not in url:
        return ""
    return url.split("#", 1)[1].strip() or ""


def load_config() -> BotConfig:
    load_dotenv(BASE_DIR / ".env")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN environment variable in .env")

    mode = (os.environ.get("BOT_MODE") or os.environ.get("MODE") or "polling").strip().lower()

    return BotConfig(
        token=token,
        mode=mode,
        log_level=os.environ.get("BOT_LOG_LEVEL", "INFO").strip().upper(),
        allowed_user_ids=_parse_user_ids(os.environ.get("BOT_ALLOWED_USER_IDS", "")),
        reply_prefix=os.environ.get("BOT_REPLY_PREFIX", "").strip(),
        db_path=_resolve_path(os.environ.get("BOT_DB_PATH", ""), "data/chatbot.sqlite3"),
        worker_enabled=_parse_bool(os.environ.get("BOT_WORKER_ENABLED", ""), True),
        queue_ack=_parse_bool(os.environ.get("BOT_QUEUE_ACK", ""), False),
        queue_default_priority=_parse_int("BOT_QUEUE_DEFAULT_PRIORITY", 100, 0),
        queue_lease_seconds=_parse_int("BOT_QUEUE_LEASE_SECONDS", 30, 1),
        queue_poll_interval_seconds=_parse_float("BOT_QUEUE_POLL_INTERVAL_SECONDS", 0.1, 0.05),
        queue_max_attempts=_parse_int("BOT_QUEUE_MAX_ATTEMPTS", 5, 1),
        queue_retry_delay_seconds=_parse_int("BOT_QUEUE_RETRY_DELAY_SECONDS", 2, 0),
    )


def load_web_reader_config() -> WebReaderConfig:
    load_dotenv(BASE_DIR / ".env")

    telegram_web_url = os.environ.get(
        "TELEGRAM_WEB_URL",
        "https://web.telegram.org/k/",
    ).strip()

    return WebReaderConfig(
        log_level=os.environ.get("BOT_LOG_LEVEL", "INFO").strip().upper(),
        db_path=_resolve_path(os.environ.get("BOT_DB_PATH", ""), "data/chatbot.sqlite3"),
        queue_default_priority=_parse_int("BOT_QUEUE_DEFAULT_PRIORITY", 100, 0),
        queue_max_attempts=_parse_int("BOT_QUEUE_MAX_ATTEMPTS", 5, 1),
        queue_max_items=_parse_int("BOT_QUEUE_MAX_ITEMS", 1000, 100),
        telegram_web_url=telegram_web_url,
        telegram_web_profile_dir=_resolve_path(
            os.environ.get("TELEGRAM_WEB_PROFILE_DIR", ""),
            "data/telegram_web_profile",
        ),
        telegram_web_headless=_parse_bool(os.environ.get("TELEGRAM_WEB_HEADLESS", ""), True),
        telegram_web_targets=_parse_web_targets(
            os.environ.get("TELEGRAM_WEB_TARGETS", ""),
            telegram_web_url,
        ),
        telegram_web_poll_interval_seconds=_parse_float(
            "TELEGRAM_WEB_POLL_INTERVAL_SECONDS",
            0.2,
            0.05,
        ),
        telegram_web_reload_seconds=_parse_int(
            "TELEGRAM_WEB_RELOAD_SECONDS",
            900,
            60,
        ),
        telegram_web_message_scan_limit=_parse_int("TELEGRAM_WEB_MESSAGE_SCAN_LIMIT", 30, 1),
        telegram_web_queue_max_age_seconds=_parse_int(
            "TELEGRAM_WEB_QUEUE_MAX_AGE_SECONDS",
            300,
            1,
        ),
        telegram_web_enqueue=_parse_bool(os.environ.get("TELEGRAM_WEB_ENQUEUE", ""), True),
        telegram_web_skip_existing_on_start=_parse_bool(
            os.environ.get("TELEGRAM_WEB_SKIP_EXISTING_ON_START", ""),
            False,
        ),
        telegram_web_include_outgoing=_parse_bool(
            os.environ.get("TELEGRAM_WEB_INCLUDE_OUTGOING", ""),
            False,
        ),
        telegram_web_filter_enabled=_parse_bool(
            os.environ.get("TELEGRAM_WEB_FILTER_ENABLED", ""),
            False,
        ),
        telegram_web_filter_config_path=_resolve_path(
            os.environ.get("TELEGRAM_WEB_FILTER_CONFIG_PATH", ""),
            "data/message_filters.json",
        ),
        telegram_web_filter_reload_seconds=_parse_float(
            "TELEGRAM_WEB_FILTER_RELOAD_SECONDS",
            1.0,
            0.1,
        ),
    )


def load_queue_json_config() -> QueueJsonConfig:
    load_dotenv(BASE_DIR / ".env")

    return QueueJsonConfig(
        log_level=os.environ.get("BOT_LOG_LEVEL", "INFO").strip().upper(),
        db_path=_resolve_path(os.environ.get("BOT_DB_PATH", ""), "data/chatbot.sqlite3"),
        output_path=_resolve_path(
            os.environ.get("QUEUE_JSON_PATH", ""),
            "data/message_queue.json",
        ),
        poll_interval_seconds=_parse_float("QUEUE_JSON_POLL_INTERVAL_SECONDS", 0.2, 0.05),
        limit=_parse_int("QUEUE_JSON_LIMIT", 200, 1),
        statuses=_parse_csv(os.environ.get("QUEUE_JSON_STATUSES", "")),
        pretty=_parse_bool(os.environ.get("QUEUE_JSON_PRETTY", ""), True),
    )


def load_queue_ui_config() -> QueueUiConfig:
    load_dotenv(BASE_DIR / ".env")

    return QueueUiConfig(
        log_level=os.environ.get("BOT_LOG_LEVEL", "INFO").strip().upper(),
        db_path=_resolve_path(os.environ.get("BOT_DB_PATH", ""), "data/chatbot.sqlite3"),
        host=os.environ.get("QUEUE_UI_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_parse_int("QUEUE_UI_PORT", 8787, 1),
        limit=_parse_int("QUEUE_UI_LIMIT", 100, 1),
        refresh_seconds=_parse_float("QUEUE_UI_REFRESH_SECONDS", 0.5, 0.2),
        queue_lease_seconds=_parse_int("BOT_QUEUE_LEASE_SECONDS", 90, 1),
        queue_retry_delay_seconds=_parse_int("BOT_QUEUE_RETRY_DELAY_SECONDS", 2, 0),
        filter_config_path=_resolve_path(
            os.environ.get("TELEGRAM_WEB_FILTER_CONFIG_PATH", ""),
            "data/message_filters.json",
        ),
    )
