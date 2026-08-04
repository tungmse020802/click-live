#!/usr/bin/env bash
# Bootstrap Telethon app-2 trên server (acc + nhóm riêng trong .env.app2).
#
# Usage:
#   cd server/telegram_bot
#
#   # Tạo .env.app2 trực tiếp trên server + mở login (nhập OTP trong terminal):
#   SERVER_PASS='...' \
#   TELEGRAM_PHONE_APP2=+849xxxxxxxx \
#   TELEGRAM_CLIENT_TARGETS_APP2='#-100111;#-100222' \
#   bash setup_app2_remote.sh --bootstrap --login
#
#   # Hoặc đã có .env.app2 local:
#   bash setup_app2.sh
#   SERVER_PASS='...' bash setup_app2_remote.sh --login

set -euo pipefail

cd "$(dirname "$0")"

SERVER_HOST="${SERVER_HOST:-160.30.19.215}"
SERVER_USER="${SERVER_USER:-root}"
SERVER_PASS="${SERVER_PASS:-}"
REMOTE_DIR="${REMOTE_DIR:-/root/click-live/server/telegram_bot}"
DO_LOGIN=0
DO_BOOTSTRAP=0

for arg in "$@"; do
  case "$arg" in
    --login) DO_LOGIN=1 ;;
    --bootstrap) DO_BOOTSTRAP=1 ;;
  esac
done

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
RSYNC_SSH="sshpass -p ${SERVER_PASS} ssh ${SSH_OPTS[*]}"

echo "==> Rsync telegram_bot (code app-2, giữ data/.env server)"
rsync -az \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'data/' \
  --exclude '.env' \
  --exclude '.env.app2' \
  -e "$RSYNC_SSH" \
  ./ "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}/"

if [[ "$DO_BOOTSTRAP" == "1" ]]; then
  echo "==> Bootstrap .env.app2 trên server"
  PHONE="${TELEGRAM_PHONE_APP2:-}"
  TARGETS="${TELEGRAM_CLIENT_TARGETS_APP2:-}"
  if [[ -z "$PHONE" ]]; then
    read -r -p "Số Telegram acc 2 (vd +849xxxxxxxx): " PHONE
  fi
  if [[ -z "$TARGETS" ]]; then
    echo "Nhóm acc app-2 (chat id, vd: #-1003431776950;#-1003792359700)"
    read -r -p "TELEGRAM_CLIENT_TARGETS_APP2: " TARGETS
  fi
  "${SSH[@]}" "${SERVER_USER}@${SERVER_HOST}" \
    "TELEGRAM_PHONE_APP2=$(printf '%q' "$PHONE") TELEGRAM_CLIENT_TARGETS_APP2=$(printf '%q' "$TARGETS") bash -s" \
    <<'REMOTE'
set -euo pipefail
cd /root/click-live/server/telegram_bot
export TELEGRAM_PHONE_APP2 TELEGRAM_CLIENT_TARGETS_APP2
bash setup_app2_on_server.sh
REMOTE
elif [[ -f .env.app2 ]]; then
  echo "==> Upload .env.app2 local -> server"
  "${SCP[@]}" .env.app2 "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}/.env.app2"
  "${SSH[@]}" "${SERVER_USER}@${SERVER_HOST}" bash -s <<REMOTE
set -euo pipefail
cd '${REMOTE_DIR}'
install -m 644 systemd/click-live-telegram-reader-app2.service /etc/systemd/system/
systemctl daemon-reload
systemctl stop click-live-telegram-reader-app2.service 2>/dev/null || true
REMOTE
else
  echo "Chưa có .env.app2 local — dùng --bootstrap hoặc chạy setup_app2.sh trước." >&2
  exit 1
fi

if [[ "$DO_LOGIN" == "1" ]]; then
  echo ""
  echo "==> Login Telethon app-2 — nhập mã OTP Telegram trong terminal bên dưới"
  echo ""
  SERVER_PASS="$SERVER_PASS" bash login_telethon_app2_remote.sh
else
  echo ""
  echo "Bootstrap xong. Login:"
  echo "  SERVER_PASS='...' bash login_telethon_app2_remote.sh"
  echo ""
  echo "Log reader app-2:"
  echo "  ssh ${SERVER_USER}@${SERVER_HOST} journalctl -u click-live-telegram-reader-app2.service -f"
fi
