#!/usr/bin/env bash
# Chạy TRỰC TIẾP trên server (ssh -tt) — login app-2, prompt OTP rõ ràng.
#
#   ssh -tt root@160.30.19.215
#   cd /root/click-live/server/telegram_bot
#   bash login_app2_on_server_manual.sh

set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env.app2 ]]; then
  echo "Thiếu .env.app2" >&2
  exit 1
fi

systemctl stop click-live-telegram-reader-app2.service 2>/dev/null || true

echo "Xóa session cũ (nếu login lỗi trước đó)..."
set -a
# shellcheck disable=SC1091
source .env.app2
set +a
rm -f "${TELEGRAM_CLIENT_SESSION}" "${TELEGRAM_CLIENT_SESSION}-journal" 2>/dev/null || true

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo ""
echo "Phone: ${TELEGRAM_PHONE}"
echo "Session: ${TELEGRAM_CLIENT_SESSION}"
echo ""
python3 -u login_telethon.py

echo ""
read -r -p "Bật service app-2? [Y/n] " ans
if [[ "${ans:-Y}" =~ ^[Yy]$ ]]; then
  systemctl enable click-live-telegram-reader-app2.service
  systemctl restart click-live-telegram-reader-app2.service
  systemctl is-active click-live-telegram-reader-app2.service
  echo "Log: journalctl -u click-live-telegram-reader-app2.service -f"
fi
