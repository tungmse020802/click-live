#!/usr/bin/env python3
import asyncio
import getpass
import os
import re
import sys

from pathlib import Path

from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from config import load_telegram_client_config


def normalize_otp(raw: str) -> str:
    return re.sub(r"\D", "", (raw or "").strip())


def read_tty(prompt: str) -> str:
    """Đọc từ terminal thật (/dev/tty) — tránh stdin rỗng qua SSH."""
    env_code = os.environ.get("TELEGRAM_OTP", "").strip()
    if env_code and "OTP" in prompt.upper():
        print(f"{prompt}[dùng TELEGRAM_OTP]", flush=True)
        return normalize_otp(env_code)
    try:
        with open("/dev/tty", "w") as tty_out:
            tty_out.write(prompt)
            tty_out.flush()
        with open("/dev/tty", "r") as tty_in:
            line = tty_in.readline()
    except OSError:
        line = input(prompt)
    code = normalize_otp(line)
    if code:
        print(f">>> Đã nhận OTP {len(code)} số", flush=True)
    return code


def read_tty_password(prompt: str) -> str:
    env_pwd = os.environ.get("TELEGRAM_2FA_PASSWORD", "").strip()
    if env_pwd:
        print(f"{prompt}[dùng TELEGRAM_2FA_PASSWORD]", flush=True)
        return env_pwd
    try:
        with open("/dev/tty", "w") as tty_out:
            return getpass.getpass(prompt, stream=tty_out)
    except OSError:
        return getpass.getpass(prompt)


async def main() -> None:
    config = load_telegram_client_config()
    Path(config.session_path).parent.mkdir(parents=True, exist_ok=True)

    print(f"Session: {config.session_path}", flush=True)
    print(f"Phone: {config.phone or '(empty TELEGRAM_PHONE)'}", flush=True)
    print(f"API ID: {config.api_id}", flush=True)
    if not config.phone:
        raise RuntimeError("Set TELEGRAM_PHONE in .env before login")

    client = TelegramClient(config.session_path, config.api_id, config.api_hash)

    def code_callback() -> str:
        print("", flush=True)
        print(f">>> Mã OTP gửi vào app Telegram ({config.phone}) — dùng mã MỚI NHẤT.", flush=True)
        print(">>> Mỗi lần chạy lại script = mã cũ hết hiệu lực.", flush=True)
        return read_tty(">>> Nhập OTP (5-6 số): ")

    def password_callback() -> str:
        return read_tty_password(">>> Nhập mật khẩu 2FA Telegram: ")

    try:
        await client.start(
            phone=config.phone,
            code_callback=code_callback,
            password=password_callback,
        )
    except PhoneCodeInvalidError:
        print("", flush=True)
        print("OTP sai hoặc đã hết hạn.", flush=True)
        print("Chạy lại từ đầu (xóa session nếu cần):", flush=True)
        print("  rm -f data/telegram_client_app2.session*")
        print("  set -a && source .env.app2 && set +a && python3 -u login_telethon.py")
        raise
    except PhoneCodeExpiredError:
        print("OTP hết hạn — chạy lại script để nhận mã mới.", flush=True)
        raise

    try:
        me = await client.get_me()
        name = getattr(me, "username", None) or getattr(me, "first_name", None) or me.id
        print(f"Login OK: {name}", flush=True)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nĐã hủy.", file=sys.stderr)
        raise SystemExit(130)
