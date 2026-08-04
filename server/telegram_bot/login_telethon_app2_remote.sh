#!/usr/bin/env bash
# SSH login Telethon app-2 trên server (.env.app2).
#
# Usage:
#   cd server/telegram_bot
#   bash login_telethon_app2_remote.sh
#   RESET_SESSION=1 bash login_telethon_app2_remote.sh

set -euo pipefail

cd "$(dirname "$0")"

SERVER_HOST="${SERVER_HOST:-160.30.19.215}"
SERVER_USER="${SERVER_USER:-root}"
SERVER_PASS="${SERVER_PASS:-}"
REMOTE_DIR="${REMOTE_DIR:-/root/click-live/server/telegram_bot}"
RESET_SESSION="${RESET_SESSION:-0}"

SSH_OPTS=(-o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no)
if [[ -n "$SERVER_PASS" ]] && command -v sshpass >/dev/null 2>&1; then
  SSH=(sshpass -p "$SERVER_PASS" ssh -tt "${SSH_OPTS[@]}")
else
  SSH=(ssh -tt "${SSH_OPTS[@]}")
fi

echo "Login Telethon app-2 trên ${SERVER_USER}@${SERVER_HOST}..."
echo

"${SSH[@]}" "${SERVER_USER}@${SERVER_HOST}" bash -s <<REMOTE
set -euo pipefail
cd '${REMOTE_DIR}'
if [[ ! -f .env.app2 ]]; then
  echo "Missing .env.app2 on server — copy .env.app2.example and configure" >&2
  exit 1
fi
systemctl stop click-live-telegram-reader-app2.service 2>/dev/null || true
if [[ '${RESET_SESSION}' == '1' ]]; then
  set -a
  source .env.app2
  set +a
  rm -f "\${TELEGRAM_CLIENT_SESSION}" "\${TELEGRAM_CLIENT_SESSION}-journal" 2>/dev/null || true
  echo "Đã xóa session app-2"
fi
bash login_telethon_app2.sh
systemctl enable click-live-telegram-reader-app2.service
systemctl restart click-live-telegram-reader-app2.service
REMOTE

echo
echo "Xong. Log app-2:"
echo "  journalctl -u click-live-telegram-reader-app2.service -f"
