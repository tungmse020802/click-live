#!/usr/bin/env bash
# Chạy TRÊN SERVER — tạo .env.app2 từ .env (acc Telethon thứ 2, nhóm riêng trong .env.app2).
#
# Usage (trên VPS):
#   cd /root/click-live/server/telegram_bot
#   TELEGRAM_PHONE_APP2=+849xxxxxxxx \
#   TELEGRAM_CLIENT_TARGETS_APP2='#-100111;#-100222' \
#   bash setup_app2_on_server.sh
#
# Sau đó login OTP:
#   bash login_telethon_app2.sh
#   systemctl enable --now click-live-telegram-reader-app2.service

set -euo pipefail

cd "$(dirname "$0")"
ENV_MAIN="${ENV_MAIN:-.env}"
ENV_APP2="${ENV_APP2:-.env.app2}"

if [[ ! -f "$ENV_MAIN" ]]; then
  echo "Missing $ENV_MAIN on server" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_MAIN"

PHONE="${TELEGRAM_PHONE_APP2:-}"
TARGETS="${TELEGRAM_CLIENT_TARGETS_APP2:-}"

if [[ -z "$PHONE" ]]; then
  read -r -p "Số Telegram acc 2 (vd +849xxxxxxxx): " PHONE
fi
if [[ -z "$PHONE" ]]; then
  echo "Cần TELEGRAM_PHONE_APP2" >&2
  exit 1
fi

if [[ -z "$TARGETS" ]]; then
  echo "Nhóm acc app-2 (format giống .env app-1: #-100xxx hoặc Label|#-100xxx;...)"
  echo "Acc 2 thường vào nhóm KHÁC app-1 — nhập chat id nhóm acc này được mời."
  read -r -p "TELEGRAM_CLIENT_TARGETS_APP2: " TARGETS
fi
if [[ -z "$TARGETS" ]]; then
  echo "Cần TELEGRAM_CLIENT_TARGETS_APP2" >&2
  exit 1
fi

API_ID="${TELEGRAM_API_ID:-}"
API_HASH="${TELEGRAM_API_HASH:-}"
if [[ -z "$API_ID" || -z "$API_HASH" ]]; then
  echo "Thiếu TELEGRAM_API_ID / TELEGRAM_API_HASH trong $ENV_MAIN" >&2
  exit 1
fi

if [[ -f "$ENV_APP2" ]]; then
  cp "$ENV_APP2" "${ENV_APP2}.bak.$(date +%Y%m%d%H%M%S)"
  echo "Đã backup $ENV_APP2"
fi

cat > "$ENV_APP2" <<EOF
# Telethon reader app-2 — acc Telegram riêng, nhóm cố định .env.app2 (không đọc panel watch_groups).

TELEGRAM_CLIENT_READER_ID=app2
TELEGRAM_CLIENT_USE_ENV_TARGETS=true

TELEGRAM_API_ID=${API_ID}
TELEGRAM_API_HASH=${API_HASH}
TELEGRAM_PHONE=${PHONE}
TELEGRAM_CLIENT_SESSION=data/telegram_client_app2.session

TELEGRAM_CLIENT_TARGETS="${TARGETS}"

BOT_DB_PATH=${BOT_DB_PATH:-data/chatbot.sqlite3}
BOT_LOG_LEVEL=${BOT_LOG_LEVEL:-ERROR}
BOT_BROADCAST_ENABLED=${BOT_BROADCAST_ENABLED:-true}
BOT_QUEUE_DEFAULT_PRIORITY=${BOT_QUEUE_DEFAULT_PRIORITY:-100}
BOT_QUEUE_TTL_SECONDS=${BOT_QUEUE_TTL_SECONDS:-1800}

TELEGRAM_CLIENT_ENQUEUE=true
TELEGRAM_CLIENT_SKIP_EXISTING_ON_START=true
TELEGRAM_CLIENT_INCLUDE_OUTGOING=false
TELEGRAM_CLIENT_QUEUE_MAX_AGE_SECONDS=${TELEGRAM_CLIENT_QUEUE_MAX_AGE_SECONDS:-300}
TELEGRAM_CLIENT_HISTORY_POLL_SECONDS=${TELEGRAM_CLIENT_HISTORY_POLL_SECONDS:-1}
TELEGRAM_CLIENT_HISTORY_POLL_LIMIT=${TELEGRAM_CLIENT_HISTORY_POLL_LIMIT:-1}
TELEGRAM_CLIENT_QUEUE_ONLY_NEWEST=true
TELEGRAM_CLIENT_SUPERSEDE_PENDING=false
TELEGRAM_CLIENT_FILTER_ENABLED=true
TELEGRAM_CLIENT_FILTER_CONFIG_PATH=${TELEGRAM_CLIENT_FILTER_CONFIG_PATH:-data/message_filters.json}
TELEGRAM_CLIENT_FILTER_RELOAD_SECONDS=${TELEGRAM_CLIENT_FILTER_RELOAD_SECONDS:-1}
EOF

echo ""
echo "OK — $ENV_APP2"
echo "  Phone  : $PHONE"
echo "  Targets: $TARGETS"
echo "  Session: data/telegram_client_app2.session"
echo ""

install -m 644 systemd/click-live-telegram-reader-app2.service /etc/systemd/system/
systemctl daemon-reload

systemctl stop click-live-telegram-reader-app2.service 2>/dev/null || true
systemctl disable click-live-telegram-reader-app2.service 2>/dev/null || true

echo "App-2 reader đã dừng — sẵn sàng login."
echo ""
echo "  bash login_telethon_app2.sh"
echo ""
echo "Sau khi login xong:"
echo "  systemctl enable --now click-live-telegram-reader-app2.service"
echo "  journalctl -u click-live-telegram-reader-app2.service -f"
