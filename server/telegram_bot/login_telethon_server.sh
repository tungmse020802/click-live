#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -d ".venv" ]]; then
  echo "Missing .venv. Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

source .venv/bin/activate

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl stop click-live-telegram-reader.service >/dev/null 2>&1 || true
fi
pkill -f "python3 telethon_reader.py" >/dev/null 2>&1 || true
sleep 1

export PYTHONUNBUFFERED=1
export TELEGRAM_CLIENT_SESSION="${TELEGRAM_CLIENT_SESSION:-data/telegram_client.session}"

if [[ "${RESET_SESSION:-0}" == "1" ]]; then
  rm -f "${TELEGRAM_CLIENT_SESSION}" "${TELEGRAM_CLIENT_SESSION}"-journal
  echo "Removed old session: ${TELEGRAM_CLIENT_SESSION}"
fi

python3 login_telethon.py

echo
echo "Login done. Start reader on server with:"
echo "  systemctl restart click-live-telegram-reader.service"
echo "  journalctl -u click-live-telegram-reader.service -f"
