#!/usr/bin/env python3
"""Open Chromium to register a new device on thanhtai.io/device."""

import re

from playwright.sync_api import sync_playwright

from browser import launch_context, read_device_cookie
from config import DEVICE_URL


def main() -> None:
    with sync_playwright() as playwright:
        context = launch_context(playwright, headless=False, inject_device=False)
        page = context.pages[0] if context.pages else context.new_page()

        print(f"Opening: {DEVICE_URL}")
        page.goto(DEVICE_URL, wait_until="domcontentloaded")

        body = page.inner_text("body")
        match = re.search(r"device_[a-f0-9-]+", body)
        cookie = read_device_cookie(context)

        print()
        print("=== Device moi ===")
        print(cookie or match.group(0) if match else body[:300])
        print()
        print("1. Copy Device ID tren trang.")
        print("2. Gui cho Chu BOT / Thanh Tai de cap quyen.")
        print("3. Dien DEVICE_ID vao config.py sau khi co ma.")
        print("4. Dong Chromium (Cmd+Q) de luu profile.")
        print()

        try:
            context.wait_for_event("close", timeout=0)
        except Exception:
            pass


if __name__ == "__main__":
    main()
