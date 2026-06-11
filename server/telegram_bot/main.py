import logging

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler, Filters, MessageHandler, Updater

from chatbot import ChatbotService
from config import BotConfig, load_config
from db import ChatDatabase
from worker import QueueWorker


logger = logging.getLogger(__name__)


def setup_logging(log_level: str) -> None:
    level = getattr(logging, log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def get_config(context: CallbackContext) -> BotConfig:
    return context.bot_data["config"]


def get_chatbot(context: CallbackContext) -> ChatbotService:
    return context.bot_data["chatbot"]


def get_db(context: CallbackContext) -> ChatDatabase:
    return context.bot_data["db"]


def is_allowed(update: Update, config: BotConfig) -> bool:
    if not config.allowed_user_ids:
        return True

    user = update.effective_user
    return bool(user and user.id in config.allowed_user_ids)


def require_access(update: Update, context: CallbackContext) -> bool:
    if is_allowed(update, get_config(context)):
        return True

    message = update.effective_message
    if message:
        message.reply_text("Bạn chưa được cấp quyền sử dụng bot này.")
    return False


def start(update: Update, context: CallbackContext) -> None:
    if not require_access(update, context):
        return

    update.effective_message.reply_text(
        "Xin chào! Tôi là chatbot. Gõ /help để xem lệnh và gửi tin nhắn để xử lý."
    )


def help_cmd(update: Update, context: CallbackContext) -> None:
    if not require_access(update, context):
        return

    update.effective_message.reply_text(
        "Lệnh: /start, /help, /status, /history, /ping\n"
        "Tin nhắn thường: bot sẽ nhận nội dung và chuyển qua khung xử lý."
    )


def ping(update: Update, context: CallbackContext) -> None:
    if not require_access(update, context):
        return

    update.effective_message.reply_text("pong")


def status(update: Update, context: CallbackContext) -> None:
    if not require_access(update, context):
        return

    config = get_config(context)
    stats = get_db(context).get_queue_stats()
    access_mode = "limited" if config.allowed_user_ids else "public"
    queue_status = ", ".join(
        f"{status}={total}" for status, total in sorted(stats.items())
    ) or "empty"
    update.effective_message.reply_text(
        f"Bot đang chạy (mode={config.mode}, access={access_mode})\n"
        f"DB: {config.db_path}\n"
        f"Queue: {queue_status}"
    )


def history(update: Update, context: CallbackContext) -> None:
    if not require_access(update, context):
        return

    chat = update.effective_chat
    if not chat:
        update.effective_message.reply_text("Không xác định được phòng chat hiện tại.")
        return

    messages = get_db(context).get_recent_messages("telegram", str(chat.id), limit=10)
    if not messages:
        update.effective_message.reply_text("Phòng này chưa có lịch sử chat được lưu.")
        return

    lines = []
    for message in messages:
        author = "Bot" if message.direction == "outgoing" else (
            message.username or message.platform_user_id or "User"
        )
        text = " ".join(message.text.split())
        if len(text) > 120:
            text = text[:117] + "..."
        lines.append(f"{author}: {text}")

    update.effective_message.reply_text("\n".join(lines))


def message_handler(update: Update, context: CallbackContext) -> None:
    if not require_access(update, context):
        return

    user = update.effective_user
    message = update.effective_message
    chat = update.effective_chat
    if not user or not message or not chat:
        logger.warning("Skipping update without user/message/chat: %s", update)
        return

    text = message.text or ""
    logger.info(
        "Received message user_id=%s username=%s chat_id=%s text=%r",
        user.id,
        user.username,
        chat.id,
        text,
    )

    db = get_db(context)
    room_id = db.upsert_chat_room(
        platform="telegram",
        chat_id=str(chat.id),
        chat_type=chat.type,
        title=chat.title,
    )
    chat_user_id = db.upsert_chat_user(
        platform="telegram",
        user_id=str(user.id),
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )
    chat_message_id = db.insert_chat_message(
        room_id=room_id,
        user_id=chat_user_id,
        platform_message_id=str(message.message_id),
        direction="incoming",
        text=text,
    )
    queue_id = db.enqueue_message(
        message_id=chat_message_id,
        room_id=room_id,
        priority=get_config(context).queue_default_priority,
        payload={
            "source": "telegram",
            "reply_transport": "bot_api",
            "telegram_chat_id": chat.id,
            "telegram_message_id": message.message_id,
        },
        max_attempts=get_config(context).queue_max_attempts,
    )
    logger.info("Enqueued message queue_id=%s chat_message_id=%s", queue_id, chat_message_id)

    if get_config(context).queue_ack:
        message.reply_text(f"Đã nhận tin nhắn và đưa vào queue #{queue_id}.")


def unknown_command(update: Update, context: CallbackContext) -> None:
    if not require_access(update, context):
        return

    update.effective_message.reply_text("Lệnh chưa được hỗ trợ. Gõ /help để xem lệnh.")


def error_handler(update: object, context: CallbackContext) -> None:
    error = context.error
    if isinstance(error, BaseException):
        logger.error(
            "Error while processing Telegram update: %s",
            error,
            exc_info=(type(error), error, error.__traceback__),
        )
    else:
        logger.error("Error while processing Telegram update: %s", error)

    if isinstance(update, Update) and update.effective_message:
        update.effective_message.reply_text(
            "Có lỗi khi xử lý tin nhắn. Vui lòng thử lại sau."
        )


def build_updater(config: BotConfig) -> Updater:
    db = ChatDatabase(config.db_path)
    db.init_schema()

    updater = Updater(config.token, use_context=True)
    dp = updater.dispatcher
    dp.bot_data["config"] = config
    dp.bot_data["chatbot"] = ChatbotService(reply_prefix=config.reply_prefix)
    dp.bot_data["db"] = db

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("ping", ping))
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CommandHandler("history", history))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, message_handler))
    dp.add_handler(MessageHandler(Filters.command, unknown_command))
    dp.add_error_handler(error_handler)

    return updater


def main() -> None:
    config = load_config()
    setup_logging(config.log_level)

    updater = build_updater(config)
    worker = None
    if config.mode != "polling":
        logger.warning("Only polling mode is implemented; falling back to polling")

    if config.worker_enabled:
        worker = QueueWorker(
            db=updater.dispatcher.bot_data["db"],
            chatbot=updater.dispatcher.bot_data["chatbot"],
            bot=updater.bot,
            lease_seconds=config.queue_lease_seconds,
            poll_interval_seconds=config.queue_poll_interval_seconds,
            retry_delay_seconds=config.queue_retry_delay_seconds,
        )
        worker.start()

    logger.info("Starting Telegram bot in polling mode")
    try:
        updater.start_polling()
        updater.idle()
    finally:
        if worker:
            worker.stop()


if __name__ == "__main__":
    main()
