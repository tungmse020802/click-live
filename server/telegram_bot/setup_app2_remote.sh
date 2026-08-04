#!/usr/bin/env bash
# Copy .env.app2 lên server + hướng dẫn login app-2 (interactive OTP qua SSH).
#
# Usage:
#   cd server/telegram_bot
#   bash setup_app2.sh                    # tạo .env.app2 local trước
#   SERVER_PASS='...' bash setup_app2_remote.sh
#   SERVER_PASS='...' bash setup_app2_remote.sh --login   # upload + login luôn

set -euo pipefail

cd "$(dirname "$0")"

SERVER_HOST="${SERVER_HOST:-160.30.19.215}"
SERVER_USER="${SERVER_USER:-root}"
SERVER_PASS="${SERVER_PASS:-}"
REMOTE_DIR="${REMOTE_DIR:-/root/click-live/server/telegram_bot}"
DO_LOGIN=0

for arg in "$@"; do
  case "$arg" in
    --login) DO_LOGIN=1 ;;
  esac
done

if [[ ! -f .env.app2 ]]; then
  echo "Chưa có .env.app2 — chạy trước:" >&2
  echo "  TELEGRAM_PHONE_APP2=+84... bash setup_app2.sh" >&2
  exit 1
fi

if ! command -v sshpass >/dev/null 2>&1; then
  echo "Cần sshpass: brew install sshpass" >&2
  exit 1
fi

if [[ -z "$SERVER_PASS" ]]; then
  read -r -s -p "SSH password ${SERVER_USER}@${SERVER_HOST}: " SERVER_PASS
  echo
fi

SSH_OPTS=(-o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no)
SCP=(sshpass -p "$SERVER_PASS" scp "${SSH_OPTS[@]}")
SSH=(sshpass -p "$SERVER_PASS" ssh "${SSH_OPTS[@]}")

echo "==> Upload .env.app2 -> ${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}/"
"${SCP[@]}" .env.app2 "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}/.env.app2"

echo "==> Install systemd unit app-2 (nếu chưa có)"
"${SSH[@]}" "${SERVER_USER}@${SERVER_HOST}" bash -s <<REMOTE
set -euo pipefail
cd '${REMOTE_DIR}'
install -m 644 systemd/click-live-telegram-reader-app2.service /etc/systemd/system/ 2>/dev/null || true
systemctl daemon-reload
REMOTE

if [[ "$DO_LOGIN" == "1" ]]; then
  echo "==> Login Telethon app-2 (nhập OTP Telegram trong terminal)..."
  bash login_telethon_app2_remote.sh
else
  echo ""
  echo "Đã upload .env.app2. Login trên server:"
  echo "  SERVER_PASS='...' bash login_telethon_app2_remote.sh"
  echo ""
  echo "Log sau khi chạy:"
  echo "  ssh ${SERVER_USER}@${SERVER_HOST} journalctl -u click-live-telegram-reader-app2.service -f"
fi
