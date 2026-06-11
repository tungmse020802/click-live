from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ChatMessage:
    text: str
    user_id: int
    username: Optional[str]
    chat_id: int


@dataclass(frozen=True)
class ChatReply:
    text: str


class ChatbotService:
    """Business layer for chatbot message processing."""

    def __init__(self, reply_prefix: str = ""):
        self.reply_prefix = reply_prefix

    def handle_text(self, message: ChatMessage) -> ChatReply:
        text = (message.text or "").strip()
        if not text:
            return self._reply("Mình chưa nhận được nội dung tin nhắn.")

        normalized = text.casefold()

        if normalized in {"hi", "hello", "xin chào", "chào", "chao"}:
            return self._reply("Xin chào! Bạn gửi nội dung cần xử lý, mình sẽ nhận và phản hồi.")

        if normalized in {"help", "tro giup", "trợ giúp", "?"}:
            return self._reply(
                "Bạn có thể gửi tin nhắn bất kỳ để bot xử lý. "
                "Gửi 'echo nội dung' để test phản hồi nhanh."
            )

        if normalized.startswith("echo "):
            echo_text = text[5:].strip()
            return self._reply(echo_text or "Bạn chưa nhập nội dung để echo.")

        return self._reply(
            "Đã nhận tin nhắn. Khung xử lý hiện đang ở chế độ mẫu.\n"
            f"User: {message.username or message.user_id}\n"
            f"Nội dung: {text}"
        )

    def _reply(self, text: str) -> ChatReply:
        if self.reply_prefix:
            return ChatReply(text=f"{self.reply_prefix} {text}")
        return ChatReply(text=text)
