#!/usr/bin/env bash
# Deploy telegram_bot panel lên VPS.
# Usage:
#   cd server/telegram_bot
#   bash deploy_to_server.sh
#
# Tuỳ chọn env:
#   SERVER_HOST=160.30.19.215 SERVER_USER=root SERVER_PASS='...' bash deploy_to_server.sh

set -euo pipefail

cd "$(dirname "$0")"
ROOT_DIR="$(pwd)"
REMOTE_DIR="${REMOTE_DIR:-/root/click-live/server/telegram_bot}"

SERVER_HOST="${SERVER_HOST:-160.30.19.215}"
SERVER_USER="${SERVER_USER:-root}"
SERVER_PASS="${SERVER_PASS:-}"

QUEUE_UI_USERNAME="${QUEUE_UI_USERNAME:-admin}"
QUEUE_UI_PASSWORD="${QUEUE_UI_PASSWORD:-Admin123@}"

if ! command -v sshpass >/dev/null 2>&1; then
  echo "Cần sshpass. macOS: brew install sshpass" >&2
  exit 1
fi

if [[ -z "$SERVER_PASS" ]]; then
  read -r -s -p "SSH password for ${SERVER_USER}@${SERVER_HOST}: " SERVER_PASS
  echo
fi

SSH_OPTS=(-o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no)
SSH=(sshpass -p "$SERVER_PASS" ssh "${SSH_OPTS[@]}" "${SERVER_USER}@${SERVER_HOST}")
RSYNC_SSH="sshpass -p ${SERVER_PASS} ssh ${SSH_OPTS[*]}"

echo "==> Rsync code -> ${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}"
rsync -az --delete \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'data/' \
  --exclude '.env' \
  --exclude 'data.zip' \
  -e "$RSYNC_SSH" \
  "$ROOT_DIR/" "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}/"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  echo "Missing local .env" >&2
  exit 1
fi

echo "==> Upload .env (giữ session/sqlite trên server)"
TMP_ENV="$(mktemp)"
trap 'rm -f "$TMP_ENV"' EXIT
cp "$ROOT_DIR/.env" "$TMP_ENV"

upsert_env() {
  local key="$1"
  local value="$2"
  python3 - "$key" "$value" "$TMP_ENV" <<'PY'
import sys
from pathlib import Path

key, value, path = sys.argv[1:4]
lines = Path(path).read_text(encoding="utf-8").splitlines()
out = []
found = False
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    k = line.split("=", 1)[0].strip()
    if k == key:
        out.append(f"{key}={value}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}={value}")
Path(path).write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
PY
}

upsert_env "QUEUE_UI_HOST" "0.0.0.0"
upsert_env "QUEUE_UI_REFRESH_SECONDS" "3"
upsert_env "DESKTOP_OPEN_DEDUP_SECONDS" "90"
upsert_env "QUEUE_UI_USERNAME" "$QUEUE_UI_USERNAME"
upsert_env "QUEUE_UI_PASSWORD" "$QUEUE_UI_PASSWORD"
QUEUE_UI_USERS_SEED="admin:Admin123@,admin1:Admin123@,admin2:Admin123@,admin3:Admin123@,admin4:Admin123@,admin5:Admin123@,admin6:Admin123@,admin7:Admin123@,admin8:Admin123@,admin9:Admin123@,admin10:Admin123@"
upsert_env "QUEUE_UI_USERS" "$QUEUE_UI_USERS_SEED"
upsert_env "BOT_BROADCAST_ENABLED" "true"
upsert_env "BOT_BROADCAST_WORKERS" "4"
upsert_env "TELEGRAM_CLIENT_SESSION" "data/telegram_client.session"
upsert_env "TELEGRAM_CLIENT_HISTORY_POLL_SECONDS" "1"
upsert_env "BOT_QUEUE_POLL_INTERVAL_SECONDS" "0.05"
upsert_env "BOT_QUEUE_TTL_SECONDS" "1800"
upsert_env "BOT_LOG_LEVEL" "ERROR"
upsert_env "TELEGRAM_CLIENT_HISTORY_POLL_LIMIT" "1"
upsert_env "TELEGRAM_CLIENT_QUEUE_ONLY_NEWEST" "true"
upsert_env "TELEGRAM_CLIENT_SUPERSEDE_PENDING" "false"
upsert_env "TELEGRAM_CLIENT_FILTER_ENABLED" "true"
upsert_env "TELEGRAM_CLIENT_FILTER_CONFIG_PATH" "data/message_filters.json"
upsert_env "PHONE_SYNC_BROADCAST" "true"
upsert_env "PHONE_SYNC_LEAD_SECONDS" "2.5"

TUNNEL_URL="$("${SSH[@]}" 'cat /root/click-live/tunnel/public.url 2>/dev/null' || true)"
TUNNEL_URL="$(echo "$TUNNEL_URL" | tr -d '\r\n' | sed 's:/*$::')"
if [[ -n "$TUNNEL_URL" ]]; then
  echo "==> DEEPLINK_OPEN_BASE_URL from Cloudflare tunnel: ${TUNNEL_URL}"
  upsert_env "DEEPLINK_OPEN_BASE_URL" "${TUNNEL_URL}"
  upsert_env "PUBLIC_QUEUE_BASE_URL" "${TUNNEL_URL}"
else
  upsert_env "DEEPLINK_OPEN_BASE_URL" "http://${SERVER_HOST}:8792"
fi
upsert_env "DEEPLINK_API_BASE_URL" "http://127.0.0.1:8792"

sshpass -p "$SERVER_PASS" scp "${SSH_OPTS[@]}" "$TMP_ENV" \
  "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}/.env"

echo "==> Setup venv + systemd on server"
"${SSH[@]}" bash -s <<REMOTE
set -euo pipefail
REMOTE_DIR="$REMOTE_DIR"
cd "\$REMOTE_DIR"
mkdir -p data/logs

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

install -m 644 systemd/click-live-queue.service /etc/systemd/system/
install -m 644 systemd/click-live-telegram-reader.service /etc/systemd/system/
install -m 644 systemd/click-live-telegram-reader-app2.service /etc/systemd/system/
install -m 644 systemd/click-live-broadcast.service /etc/systemd/system/
systemctl daemon-reload

mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/click-live.conf <<'JOURNAL'
[Journal]
SystemMaxUse=100M
MaxRetentionSec=3day
JOURNAL
systemctl restart systemd-journald || true
journalctl --vacuum-size=100M || true

# Dừng process cũ chạy ngoài systemd
pkill -f "python3 queue_ui.py" 2>/dev/null || true
pkill -f "python3 telethon_reader.py" 2>/dev/null || true
pkill -f "python3 broadcast_worker.py" 2>/dev/null || true
sleep 1

systemctl enable click-live-queue.service click-live-telegram-reader.service click-live-broadcast.service
systemctl restart click-live-queue.service
systemctl restart click-live-telegram-reader.service
systemctl restart click-live-broadcast.service

if [[ -f .env.app2 ]]; then
  systemctl enable click-live-telegram-reader-app2.service
  systemctl restart click-live-telegram-reader-app2.service
else
  echo "Skip app-2 reader: chưa có .env.app2 (copy .env.app2.example rồi login_telethon_app2.sh)"
fi

echo
echo "=== Service status ==="
systemctl is-active click-live-queue.service click-live-telegram-reader.service click-live-broadcast.service
if [[ -f .env.app2 ]]; then
  systemctl is-active click-live-telegram-reader-app2.service || true
fi
ss -lntp | grep 8787 || true
REMOTE

echo
echo "Deploy xong."
echo "Panel: http://${SERVER_HOST}:8787/login"
echo "User:  ${QUEUE_UI_USERNAME}"
echo "Pass:  ${QUEUE_UI_PASSWORD}"
echo
echo "Login lại Telethon session trên server:"
echo "  bash login_telethon_remote.sh"
