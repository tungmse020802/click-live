#!/usr/bin/env bash
# Tạo .env.app2 từ .env (API chung) + số acc Telegram thứ hai.
#
# Usage:
#   cd server/telegram_bot
#   TELEGRAM_PHONE_APP2=+849xxxxxxxx bash setup_app2.sh
#   TELEGRAM_CLIENT_TARGETS_APP2='#-100111;#-100222' bash setup_app2.sh
#
# Sau đó login:
#   bash login_telethon_app2.sh

set -euo pipefail

cd "$(dirname "$0")"
ENV_MAIN="${ENV_MAIN:-.env}"
ENV_APP2="${ENV_APP2:-.env.app2}"
EXAMPLE="${EXAMPLE:-.env.app2.example}"

if [[ ! -f "$ENV_MAIN" ]]; then
  echo "Missing $ENV_MAIN" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_MAIN"

PHONE="${TELEGRAM_PHONE_APP2:-}"
TARGETS="${TELEGRAM_CLIENT_TARGETS_APP2:-${TELEGRAM_CLIENT_TARGETS:-}}"

if [[ -z "$PHONE" ]]; then
  read -r -p "Số Telegram acc 2 (vd +849xxxxxxxx): " PHONE
fi
if [[ -z "$PHONE" ]]; then
  echo "Cần TELEGRAM_PHONE_APP2 hoặc nhập số điện thoại." >&2
  exit 1
fi

if [[ -z "$TARGETS" ]]; then
  echo "Nhóm app-2 (cùng format .env: #-100xxx hoặc Label|#-100xxx;...)"
  read -r -p "TELEGRAM_CLIENT_TARGETS: " TARGETS
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
# Telethon reader app-2 — acc Telegram riêng, cùng queue với app-1.
# Tạo bởi setup_app2.sh — chỉnh tay nếu cần.

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
echo "OK — đã tạo $ENV_APP2"
echo "  Phone  : $PHONE"
echo "  Targets: $TARGETS"
echo "  Session: data/telegram_client_app2.session"
echo ""
echo "Bước tiếp — login Telegram (nhập OTP trong terminal):"
echo "  bash login_telethon_app2.sh"
echo ""
echo "Trên server (sau khi scp .env.app2 hoặc chạy setup trên VPS):"
echo "  bash login_telethon_app2_remote.sh"
