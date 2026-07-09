#!/usr/bin/env bash
# SSH vào server và login lại Telethon (nhập mã Telegram trên terminal).
#
# Usage:
#   cd server/telegram_bot
#   bash login_telethon_remote.sh              # giữ session cũ, login nếu chưa có
#   RESET_SESSION=1 bash login_telethon_remote.sh   # xóa session cũ, login lại từ đầu
#
# Env:
#   SERVER_HOST=103.38.237.7
#   SERVER_USER=root
#   SERVER_PASS=...        # nếu trống sẽ hỏi hoặc dùng SSH key

set -euo pipefail

cd "$(dirname "$0")"

SERVER_HOST="${SERVER_HOST:-103.38.237.7}"
SERVER_USER="${SERVER_USER:-root}"
SERVER_PASS="${SERVER_PASS:-}"
REMOTE_DIR="${REMOTE_DIR:-/root/click-live/server/telegram_bot}"
RESET_SESSION="${RESET_SESSION:-0}"

if [[ -n "$SERVER_PASS" ]] && command -v sshpass >/dev/null 2>&1; then
  SSH=(sshpass -p "$SERVER_PASS" ssh -tt -o StrictHostKeyChecking=no)
else
  SSH=(ssh -tt -o StrictHostKeyChecking=no)
fi

echo "Kết nối ${SERVER_USER}@${SERVER_HOST} để login Telethon..."
echo "Bạn sẽ được hỏi mã OTP Telegram (và 2FA nếu có)."
echo

"${SSH[@]}" "${SERVER_USER}@${SERVER_HOST}" \
  "cd '${REMOTE_DIR}' && RESET_SESSION='${RESET_SESSION}' bash login_telethon_server.sh"

echo
echo "Xong. Kiểm tra reader:"
echo "  ssh ${SERVER_USER}@${SERVER_HOST} 'systemctl restart click-live-telegram-reader.service && journalctl -u click-live-telegram-reader.service -f'"
