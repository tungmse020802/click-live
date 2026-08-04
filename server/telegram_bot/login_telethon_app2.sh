#!/usr/bin/env bash
# Login Telethon session cho app-2 (.env.app2 — acc Telegram riêng).
#
# Usage:
#   cd server/telegram_bot
#   bash login_telethon_app2.sh

set -euo pipefail

cd "$(dirname "$0")"
ENV_FILE="${ENV_FILE:-.env.app2}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE — copy from .env.app2.example" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "Login app-2 reader (session=${TELEGRAM_CLIENT_SESSION:-?}) phone=${TELEGRAM_PHONE:-?}"
python3 login_telethon.py
