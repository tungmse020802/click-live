#!/usr/bin/env bash
# Tạo .env.app2 cho acc Telethon thứ 2 (+84567660222) — API app "tele reader" riêng.
#
# Usage:
#   cd server/telegram_bot
#   bash setup_app2_tele_reader.sh
#
#   # Nhóm khác app-1:
#   TELEGRAM_CLIENT_TARGETS_APP2='#-100111;#-100222' bash setup_app2_tele_reader.sh
#
# Login local:
#   bash login_telethon_app2.sh
#
# Login trên server (upload + OTP):
#   SERVER_PASS='...' bash login_app2_tele_reader_remote.sh

set -euo pipefail

cd "$(dirname "$0")"

ENV_APP2="${ENV_APP2:-.env.app2}"
ENV_MAIN="${ENV_MAIN:-.env}"

PHONE="${TELEGRAM_PHONE_APP2:-+84567660222}"
API_ID="${TELEGRAM_API_ID_APP2:-34689959}"
API_HASH="${TELEGRAM_API_HASH_APP2:-7d02feb77b3fad33fbe5aafbdba59e2d}"
TARGETS="${TELEGRAM_CLIENT_TARGETS_APP2:-OliverNguyen|#-3734576353;OliverNguyen_2|#-3832976333}"

if [[ -z "$TARGETS" && -f "$ENV_MAIN" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_MAIN"
  # Acc app-2 (hipzp) thường ở nhóm OliverNguyen — khác app-1 nếu chưa copy từ .env
  TARGETS="${TELEGRAM_CLIENT_TARGETS_APP2:-${TELEGRAM_WEB_TARGETS:-${TELEGRAM_CLIENT_TARGETS:-}}}"
  if [[ -n "$TARGETS" ]]; then
    echo "Targets từ env (đổi TELEGRAM_CLIENT_TARGETS_APP2 nếu acc-2 vào nhóm khác)"
  fi
fi

if [[ -z "$TARGETS" ]]; then
  echo "Nhóm acc app-2 (vd: #-1003431776950;#-1003792359700)"
  read -r -p "TELEGRAM_CLIENT_TARGETS_APP2: " TARGETS
fi
if [[ -z "$TARGETS" ]]; then
  echo "Cần TELEGRAM_CLIENT_TARGETS_APP2" >&2
  exit 1
fi

if [[ -f "$ENV_APP2" ]]; then
  cp "$ENV_APP2" "${ENV_APP2}.bak.$(date +%Y%m%d%H%M%S)"
  echo "Đã backup $ENV_APP2"
fi

BOT_DB="${BOT_DB_PATH:-data/chatbot.sqlite3}"
if [[ -f "$ENV_MAIN" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_MAIN"
  BOT_DB="${BOT_DB_PATH:-data/chatbot.sqlite3}"
fi

cat > "$ENV_APP2" <<EOF
# Telethon app-2 — acc +84567660222, API "app tele reader" (my.telegram.org).
# Tạo bởi setup_app2_tele_reader.sh — không commit file này.

TELEGRAM_CLIENT_READER_ID=app2
TELEGRAM_CLIENT_USE_ENV_TARGETS=false

TELEGRAM_API_ID=${API_ID}
TELEGRAM_API_HASH=${API_HASH}
TELEGRAM_PHONE=${PHONE}
TELEGRAM_CLIENT_SESSION=data/telegram_client_app2.session

TELEGRAM_CLIENT_TARGETS="${TARGETS}"

BOT_DB_PATH=${BOT_DB}
BOT_LOG_LEVEL=ERROR
BOT_BROADCAST_ENABLED=true
BOT_QUEUE_DEFAULT_PRIORITY=100
BOT_QUEUE_TTL_SECONDS=1800

TELEGRAM_CLIENT_ENQUEUE=true
TELEGRAM_CLIENT_SKIP_EXISTING_ON_START=true
TELEGRAM_CLIENT_INCLUDE_OUTGOING=false
TELEGRAM_CLIENT_QUEUE_MAX_AGE_SECONDS=300
TELEGRAM_CLIENT_HISTORY_POLL_SECONDS=1
TELEGRAM_CLIENT_HISTORY_POLL_LIMIT=1
TELEGRAM_CLIENT_QUEUE_ONLY_NEWEST=true
TELEGRAM_CLIENT_SUPERSEDE_PENDING=false
TELEGRAM_CLIENT_FILTER_ENABLED=true
TELEGRAM_CLIENT_FILTER_CONFIG_PATH=data/message_filters.json
TELEGRAM_CLIENT_FILTER_RELOAD_SECONDS=1
EOF

echo ""
echo "OK — $ENV_APP2"
echo "  Phone   : $PHONE"
echo "  API ID  : $API_ID"
echo "  Targets : $TARGETS"
echo "  Session : data/telegram_client_app2.session"
echo ""
echo "Login OTP:"
echo "  bash login_telethon_app2.sh"
echo "  SERVER_PASS='...' bash login_app2_tele_reader_remote.sh"
