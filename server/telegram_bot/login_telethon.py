#!/usr/bin/env python3
import asyncio
from pathlib import Path

from telethon import TelegramClient

from config import load_telegram_client_config


async def main() -> None:
    config = load_telegram_client_config()
    Path(config.session_path).parent.mkdir(parents=True, exist_ok=True)

    print(f"Session: {config.session_path}")
    print(f"Phone: {config.phone or '(empty TELEGRAM_PHONE)'}")
    if not config.phone:
        raise RuntimeError("Set TELEGRAM_PHONE in .env before login")

    client = TelegramClient(config.session_path, config.api_id, config.api_hash)
    await client.start(phone=config.phone)
    try:
        me = await client.get_me()
        name = getattr(me, "username", None) or getattr(me, "first_name", None) or me.id
        print(f"Login OK: {name}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
