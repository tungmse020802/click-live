#!/usr/bin/env python3
"""Verify device_id cookie is set before referral navigation."""

from playwright.sync_api import sync_playwright

from browser import ensure_device_cookie, launch_context, read_device_cookie
from config import DEVICE_ID, TARGET_URL

WARMUP_URL = "https://thanhtai.io/device"


def main() -> None:
    with sync_playwright() as playwright:
        context = launch_context(playwright, headless=True)
        page = context.pages[0] if context.pages else context.new_page()

        page.goto(WARMUP_URL, wait_until="networkidle")
        ensure_device_cookie(context, page)

        cookie_before = read_device_cookie(context)
        page.goto(TARGET_URL, wait_until="networkidle")
        cookie_after = read_device_cookie(context)
        body = page.inner_text("body")
        context.close()

    print("EXPECTED :", DEVICE_ID)
    print("BEFORE   :", cookie_before)
    print("AFTER    :", cookie_after)
    print("PAGE     :", body[:200])

    if cookie_before != DEVICE_ID or cookie_after != DEVICE_ID:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
