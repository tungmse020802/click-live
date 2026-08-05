#!/usr/bin/env bash
# Setup .env.app2 (acc tele reader) + upload server + login OTP app-2.
#
# Usage:
#   cd server/telegram_bot
#   SERVER_PASS='mat-khau-ssh' bash login_app2_tele_reader_remote.sh
#
#   TELEGRAM_CLIENT_TARGETS_APP2='#-100...' SERVER_PASS='...' bash login_app2_tele_reader_remote.sh
#
# Login lại (xóa session cũ):
#   RESET_SESSION=1 SERVER_PASS='...' bash login_app2_tele_reader_remote.sh

set -euo pipefail

cd "$(dirname "$0")"

export TELEGRAM_PHONE_APP2="${TELEGRAM_PHONE_APP2:-+84567660222}"
export TELEGRAM_API_ID_APP2="${TELEGRAM_API_ID_APP2:-34689959}"
export TELEGRAM_API_HASH_APP2="${TELEGRAM_API_HASH_APP2:-7d02feb77b3fad33fbe5aafbdba59e2d}"

bash setup_app2_tele_reader.sh

echo ""
echo "==> Upload + login trên server (nhập OTP Telegram khi được hỏi)..."
echo ""

bash setup_app2_remote.sh --login
