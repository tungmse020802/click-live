#!/usr/bin/env python3
"""Resolve junb.io.vn shortlink to TikTok deeplink using authorized Playwright profile."""

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from browser import launch_context, read_device_cookie
from config import DEVICE_URL, PROFILE_DIR

JUNB_URL = "https://i.junb.io.vn/i/?b7YVmORSncRD4"


def decode_junb_offline(url: str) -> str | None:
    """Same algorithm as ios_wda_controller/worker.js resolveJunbUrl()."""
    match = re.search(r"[?&]([A-Za-z0-9_-]+)(?:$|&)", url)
    if not match:
        return None

    param = match.group(1)
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    w = param[:-1] if param.endswith("=") else param
    w = w[::-1]

    y = 0
    for ch in w:
        y = y * 62 + chars.index(ch)
    y -= 0xE6875

    decoded = str(y)[1:][::-1]
    if not decoded:
        return None

    t = decoded[0]
    rest = decoded[1:]
    trim = int(t) if t.isdigit() else 0
    room_id = rest[: max(0, len(rest) - trim)]
    if not room_id.isdigit():
        return None
    return f"snssdk1180://live?room_id={room_id}"


def resolve_via_browser() -> dict:
    result = {
        "final_url": None,
        "deeplinks": [],
        "responses": [],
        "body_preview": "",
        "device_id": None,
    }

    with sync_playwright() as playwright:
        context = launch_context(playwright, headless=True, inject_device=False)
        page = context.pages[0] if context.pages else context.new_page()
        result["device_id"] = read_device_cookie(context)

        def on_response(resp):
            url = resp.url
            if "junb.io.vn" in url or "thanhtai.io" in url:
                entry = {"url": url, "status": resp.status}
                try:
                    if "text" in resp.headers.get("content-type", ""):
                        text = resp.text()
                        entry["body_preview"] = text[:500]
                        for match in re.findall(r"snssdk1180://[^\s\"'<>]+", text):
                            result["deeplinks"].append(match)
                except Exception as exc:
                    entry["error"] = str(exc)
                result["responses"].append(entry)

        page.on("response", on_response)

        # Warm up thanhtai session if profile has device cookie
        if result["device_id"]:
            page.goto(DEVICE_URL, wait_until="domcontentloaded", timeout=60000)

        page.goto(JUNB_URL, wait_until="networkidle", timeout=60000)
        result["final_url"] = page.url
        body = page.inner_text("body")
        result["body_preview"] = body[:1000]

        for match in re.findall(r"snssdk1180://[^\s\"'<>]+", body):
            result["deeplinks"].append(match)

        # Try click "MỞ LINK" if verification page
        for label in ("MỞ LINK", "MO LINK", "Mở link"):
            btn = page.get_by_text(label, exact=False)
            if btn.count():
                try:
                    with page.expect_navigation(timeout=15000):
                        btn.first.click()
                except Exception:
                    btn.first.click()
                    page.wait_for_timeout(3000)
                break

        result["final_url_after_click"] = page.url
        body2 = page.inner_text("body")
        result["body_after_click"] = body2[:1000]
        for match in re.findall(r"snssdk1180://[^\s\"'<>]+", body2):
            result["deeplinks"].append(match)

        for anchor in page.locator("a[href*='snssdk1180']").all():
            href = anchor.get_attribute("href")
            if href:
                result["deeplinks"].append(href)

        context.close()

    result["deeplinks"] = list(dict.fromkeys(result["deeplinks"]))
    return result


def main() -> None:
    offline = decode_junb_offline(JUNB_URL)
    browser = resolve_via_browser()

    print("JUNB_URL:", JUNB_URL)
    print("\n=== Offline decode (worker.js algorithm) ===")
    print(offline)
    print("\n=== Browser profile ===")
    print("device_id:", browser.get("device_id"))
    print("final_url:", browser.get("final_url"))
    print("final_url_after_click:", browser.get("final_url_after_click"))
    print("deeplinks:", browser.get("deeplinks"))
    print("\n=== Page preview ===")
    print(browser.get("body_preview"))
    if browser.get("body_after_click"):
        print("\n=== After click ===")
        print(browser.get("body_after_click"))

    out = Path(__file__).resolve().parent / "junb_resolve_result.json"
    out.write_text(
        json.dumps({"offline": offline, "browser": browser}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
