#!/usr/bin/env python3
"""Headless check: verify device_id cookie and referral page status."""

import json

from playwright.sync_api import sync_playwright

from browser import launch_context
from config import DEVICE_ID, TARGET_URL


def main() -> None:
    with sync_playwright() as playwright:
        context = launch_context(playwright, headless=True)
        page = context.pages[0] if context.pages else context.new_page()

        page.goto("https://thanhtai.io/device", wait_until="networkidle")
        device_page = page.inner_text("body")

        page.goto(TARGET_URL, wait_until="networkidle")
        referral_page = page.inner_text("body")

        cookies = context.cookies("https://thanhtai.io")
        context.close()

    print("DEVICE_ID:", DEVICE_ID)
    print("\n=== /device ===")
    print(device_page)
    print("\n=== referral ===")
    print(referral_page)
    print("\n=== cookie ===")
    print(json.dumps([c for c in cookies if c["name"] == "device_id"], indent=2))


if __name__ == "__main__":
    main()
