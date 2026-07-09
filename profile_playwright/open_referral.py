#!/usr/bin/env python3
"""Open referral link with registered device_id cookie."""

import sys

from playwright.sync_api import sync_playwright

from browser import ensure_device_cookie, launch_context, read_device_cookie
from config import DEVICE_ID, TARGET_URL

WARMUP_URL = "https://thanhtai.io/device"


def main() -> None:
    if not DEVICE_ID:
        print("DEVICE_ID trong config.py dang trong.")
        print("Chay setup_profile.py de dang ky thiet bi truoc.")
        sys.exit(1)

    with sync_playwright() as playwright:
        context = launch_context(playwright, headless=False)
        page = context.pages[0] if context.pages else context.new_page()

        print(f"Device ID : {DEVICE_ID}")

        # Warm up on thanhtai.io so cookie is bound before referral navigation.
        page.goto(WARMUP_URL, wait_until="domcontentloaded")
        ensure_device_cookie(context, page)
        print(f"Cookie jar: {read_device_cookie(context)}")

        print(f"Opening   : {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="domcontentloaded")

        print()
        print("Kiem tra tab Network: request phai co")
        print(f"  device_id={DEVICE_ID}")
        print("Dong Chromium (Cmd+Q) de luu cookie vao profile.")
        print()

        try:
            context.wait_for_event("close", timeout=0)
        except Exception:
            pass


if __name__ == "__main__":
    main()
