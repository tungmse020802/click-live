#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -d ".venv" ]]; then
  echo "Missing .venv. Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

source .venv/bin/activate

if command -v systemctl >/dev/null 2>&1; then
  systemctl stop click-live-telegram-reader.service >/dev/null 2>&1 || true
fi

export PYTHONUNBUFFERED=1
export TELEGRAM_CLIENT_SESSION="${TELEGRAM_CLIENT_SESSION:-data/telegram_server.session}"

if [[ "${RESET_SESSION:-0}" == "1" ]]; then
  rm -f "${TELEGRAM_CLIENT_SESSION}" "${TELEGRAM_CLIENT_SESSION}"-journal
  echo "Removed old session: ${TELEGRAM_CLIENT_SESSION}"
fi

python3 - <<'PY'
import asyncio
import getpass
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from config import load_telegram_client_config


def prompt_tty(prompt: str, secret: bool = False) -> str:
    try:
        with open("/dev/tty", "r+", encoding="utf-8") as tty:
            if secret:
                return getpass.getpass(prompt, stream=tty).strip()
            tty.write(prompt)
            tty.flush()
            return tty.readline().strip()
    except OSError:
        if secret:
            return getpass.getpass(prompt).strip()
        return input(prompt).strip()


async def main() -> None:
    config = load_telegram_client_config()
    Path(config.session_path).parent.mkdir(parents=True, exist_ok=True)

    print(f"Session: {config.session_path}")
    print(f"Phone: {config.phone or '(empty TELEGRAM_PHONE)'}")
    if not config.phone:
        raise RuntimeError("Set TELEGRAM_PHONE in .env before login")

    client = TelegramClient(config.session_path, config.api_id, config.api_hash)
    await client.connect()
    try:
        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"Already logged in as: {getattr(me, 'username', None) or getattr(me, 'first_name', None) or me.id}")
            return

        print("Telegram login required.")
        sent = await client.send_code_request(config.phone)
        code = prompt_tty("Please enter the Telegram code: ")
        try:
            await client.sign_in(config.phone, code, phone_code_hash=sent.phone_code_hash)
        except SessionPasswordNeededError:
            password = prompt_tty("Please enter your Telegram 2FA password: ", secret=True)
            await client.sign_in(password=password)
        me = await client.get_me()
        print(f"Login OK: {getattr(me, 'username', None) or getattr(me, 'first_name', None) or me.id}")
    finally:
        await client.disconnect()


asyncio.run(main())
PY

echo
echo "Login done. Start reader on server with:"
echo "  systemctl restart click-live-telegram-reader.service"
echo "  journalctl -u click-live-telegram-reader.service -f"
