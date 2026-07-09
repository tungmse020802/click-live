#!/usr/bin/env python3
"""Persist correct device_id cookie into browser-data (run while browser closed)."""

from playwright.sync_api import sync_playwright

from browser import ensure_device_cookie, launch_context, read_device_cookie
from config import DEVICE_ID

WARMUP_URL = "https://thanhtai.io/device"


def main() -> None:
    with sync_playwright() as playwright:
        context = launch_context(playwright, headless=True)
        page = context.pages[0] if context.pages else context.new_page()

        page.goto(WARMUP_URL, wait_until="networkidle")
        ensure_device_cookie(context, page)
        page.reload(wait_until="networkidle")

        cookie = read_device_cookie(context)
        body = page.inner_text("body")
        context.close()

    print("DEVICE_ID:", DEVICE_ID)
    print("COOKIE   :", cookie)
    print("PAGE     :", body[:200])
    if cookie != DEVICE_ID or DEVICE_ID not in body:
        raise SystemExit("Cookie chua duoc persist dung. Thu lai sau khi dong het Chromium.")


if __name__ == "__main__":
    main()
