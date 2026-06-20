# Telegram Chatbot (scaffold)

Mô tả: khung đơn giản cho chatbot Telegram nhận tin nhắn và xử lý.
Tin nhắn được lưu vào SQLite theo từng phòng chat, sau đó đưa vào queue để worker xử lý.

Yêu cầu:
- Python 3.8+
- Biến môi trường trong `.env`: `TELEGRAM_BOT_TOKEN` nếu chạy bot bằng `main.py`

Cài đặt (local):

```bash
cd server/telegram_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# chỉnh .env: thêm TELEGRAM_BOT_TOKEN=...
python3 main.py
```

Biến môi trường:

```env
TELEGRAM_BOT_TOKEN=      # token lấy từ BotFather
BOT_MODE=polling         # hiện scaffold đang hỗ trợ polling
BOT_LOG_LEVEL=INFO       # DEBUG, INFO, WARNING, ERROR
BOT_ALLOWED_USER_IDS=    # ví dụ: 123456,789012; bỏ trống để public
BOT_REPLY_PREFIX=        # ví dụ: [Bot]
BOT_DB_PATH=data/chatbot.sqlite3
BOT_WORKER_ENABLED=true
BOT_QUEUE_ACK=false
BOT_QUEUE_DEFAULT_PRIORITY=100
BOT_QUEUE_LEASE_SECONDS=30
BOT_QUEUE_POLL_INTERVAL_SECONDS=0.1
BOT_QUEUE_MAX_ATTEMPTS=5
BOT_QUEUE_RETRY_DELAY_SECONDS=2
BOT_QUEUE_MAX_ITEMS=1000

TELEGRAM_WEB_URL=https://web.telegram.org/k/
TELEGRAM_WEB_PROFILE_DIR=data/telegram_web_profile
TELEGRAM_WEB_HEADLESS=true
TELEGRAM_WEB_TARGETS=""     # ví dụ: "Group A|https://web.telegram.org/k/#-100xxx;Group B|https://web.telegram.org/k/#@group_username"
TELEGRAM_WEB_POLL_INTERVAL_SECONDS=0.2
TELEGRAM_WEB_RELOAD_SECONDS=900
TELEGRAM_WEB_QUEUE_MAX_AGE_SECONDS=300
TELEGRAM_WEB_MESSAGE_SCAN_LIMIT=30
TELEGRAM_WEB_ENQUEUE=true
TELEGRAM_WEB_SKIP_EXISTING_ON_START=false
TELEGRAM_WEB_INCLUDE_OUTGOING=false
TELEGRAM_WEB_FILTER_ENABLED=false
TELEGRAM_WEB_FILTER_CONFIG_PATH=data/message_filters.json
TELEGRAM_WEB_FILTER_RELOAD_SECONDS=1

QUEUE_JSON_PATH=data/message_queue.json
QUEUE_JSON_POLL_INTERVAL_SECONDS=0.2
QUEUE_JSON_LIMIT=50
QUEUE_JSON_STATUSES=pending
QUEUE_JSON_PRETTY=false

QUEUE_UI_HOST=127.0.0.1
QUEUE_UI_PORT=8787
QUEUE_UI_LIMIT=100
QUEUE_UI_REFRESH_SECONDS=0.5
```

Database/queue:
- SQLite là lựa chọn nhẹ nhất cho scaffold này, mặc định lưu ở `data/chatbot.sqlite3`.
- `chat_rooms` lưu từng phòng chat theo `platform + chat_id`.
- `chat_messages` lưu lịch sử incoming/outgoing theo `room_id`.
- `message_queue` lưu job xử lý với `priority`, `status`, `locked_by`, `locked_until`.
- Worker claim job theo `priority` cao trước. Nếu job bị giữ quá `BOT_QUEUE_LEASE_SECONDS` giây mà chưa hoàn tất, job được đưa lại về `pending` để worker khác nhận.
- Gõ `/history` trong một phòng để xem nhanh lịch sử gần nhất của phòng đó.
- Gõ `/status` để xem thống kê queue.

Chạy bằng Docker:

```bash
cd server/telegram_bot
docker build -t telegram-bot .
docker run --env-file .env --rm telegram-bot
```

Mở rộng:
- Thay thế logic trong `ChatbotService.handle_text` ở `chatbot.py` để thêm logic NLP, lưu vào DB, gọi API ngoài.
- Dùng `config.py` để thêm biến môi trường mới khi cần cấu hình thêm.
- Dùng `ChatDatabase.enqueue_message` để set priority riêng theo loại tin nhắn hoặc phòng chat.
- Để dùng webhook, thêm endpoint HTTP và cấu hình webhook của Telegram.

Telegram Web reader:
```bash
cd server/telegram_bot
source .venv/bin/activate
python3 -m playwright install chromium
python3 telegram_web_reader.py
```

Chạy bằng Docker:
```bash
cd server/telegram_bot
docker build -t telegram-bot .
docker run --env-file .env --rm telegram-bot python telegram_web_reader.py
```

Ghi chú:
- Trên server, dùng `TELEGRAM_WEB_HEADLESS=true` với profile đã đăng nhập. Nếu chưa
  có profile, đăng nhập một lần trên máy có GUI rồi chuyển profile lên server.
- `TELEGRAM_WEB_TARGETS` nhận dạng `label|url`, ngăn cách nhiều target bằng dấu `;`.
- Nếu để trống `TELEGRAM_WEB_TARGETS`, reader sẽ mở Telegram Web và đọc chat đang active.
- Bật `TELEGRAM_WEB_FILTER_ENABLED=true` để chỉ enqueue message rương đạt filter trong `TELEGRAM_WEB_FILTER_CONFIG_PATH`.
- Reader chỉ enqueue message Telegram có timestamp trong vòng
  `TELEGRAM_WEB_QUEUE_MAX_AGE_SECONDS` gần nhất, mặc định 5 phút. Tin cũ hoặc
  không xác định được timestamp sẽ không vào queue.
- Đặt `TELEGRAM_WEB_SKIP_EXISTING_ON_START=false` để sau khi restart vẫn nhận
  các tin chưa lưu trong cửa sổ 5 phút; SQLite tự chống trùng theo message ID.
- Reader tự reload file filter theo `TELEGRAM_WEB_FILTER_RELOAD_SECONDS`, nên có thể sửa filter mà không cần restart.
- Mỗi filter dùng AND logic bên trong filter đó. Nhiều filter dùng OR logic: match một filter bất kỳ là được enqueue.
- Nếu file filter không có rule (`"filters": []`) hoặc toàn bộ rule bị tắt, reader sẽ nhận tất cả message.
- `BOX: 100/25` là một BOX; các field `min_box1/max_box1` lọc giá trị 1 (`100`), `min_box2/max_box2` lọc giá trị 2 (`25`).
- `reply_transport=none` nghĩa là job sẽ được xử lý và lưu trace, nhưng không gửi reply ngược bằng Bot API.

Ví dụ `data/message_filters.json`:

```json
{
  "filters": [
    {
      "name": "kr_100_25_low_view",
      "enabled": true,
      "priority": 100,
      "min_box1": 100,
      "max_box1": 100,
      "min_box2": 25,
      "max_box2": 25,
      "countries": ["KR"],
      "badges": ["💎", "🏅"],
      "min_rate": 4,
      "max_rate": 8,
      "min_views": 0,
      "max_views": 20,
      "note_contains": ["Rương ít view"]
    },
    {
      "name": "jp_50_1",
      "enabled": true,
      "priority": 80,
      "min_box1": 50,
      "max_box1": 50,
      "min_box2": 1,
      "max_box2": 1,
      "countries": ["JP"],
      "min_rate": 20
    }
  ]
}
```

Queue JSON client:
```bash
cd server/telegram_bot
source .venv/bin/activate
python3 queue_json_client.py
```

Client này ghi snapshot queue liên tục vào `QUEUE_JSON_PATH`.

Queue UI:
```bash
cd server/telegram_bot
source .venv/bin/activate
python3 queue_ui.py
```

Mặc định mở tại `http://127.0.0.1:8787`.
