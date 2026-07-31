#!/usr/bin/env python3
"""Deep inspect thanhtai.io auth: network, storage, scripts."""

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from browser import ensure_device_cookie, launch_context
from config import DEVICE_ID, TARGET_URL

OUT = Path(__file__).resolve().parent / "auth_analysis.json"


def main() -> None:
    events = {"requests": [], "responses": [], "storage": {}, "scripts": [], "html_snippets": []}

    with sync_playwright() as playwright:
        context = launch_context(playwright, headless=True)
        page = context.pages[0] if context.pages else context.new_page()

        def on_request(req):
            if any(h in req.url for h in ("thanhtai", "junb", "cloudflare", "firebase", "google")):
                events["requests"].append(
                    {
                        "method": req.method,
                        "url": req.url,
                        "resource_type": req.resource_type,
                        "headers": dict(req.headers),
                    }
                )

        def on_response(resp):
            url = resp.url
            if not any(h in url for h in ("thanhtai", "junb", "firebase", "google")):
                return
            entry = {"url": url, "status": resp.status, "headers": dict(resp.headers)}
            try:
                ct = resp.headers.get("content-type", "")
                if any(t in ct for t in ("json", "text", "javascript", "html")):
                    body = resp.text()
                    entry["body_preview"] = body[:4000]
                    if "device" in body.lower() or "fingerprint" in body.lower() or "auth" in body.lower():
                        events["html_snippets"].append({"url": url, "snippet": body[:8000]})
            except Exception as exc:
                entry["body_error"] = str(exc)
            events["responses"].append(entry)

        page.on("request", on_request)
        page.on("response", on_response)

        for url in ("https://thanhtai.io/device", TARGET_URL, "https://thanhtai.io/app"):
            page.goto(url, wait_until="networkidle", timeout=60000)
            events["storage"][url] = {
                "localStorage": page.evaluate(
                    """() => Object.fromEntries([...Array(localStorage.length)].map(i => [localStorage.key(i), localStorage.getItem(localStorage.key(i))]))"""
                ),
                "sessionStorage": page.evaluate(
                    """() => Object.fromEntries([...Array(sessionStorage.length)].map(i => [sessionStorage.key(i), sessionStorage.getItem(sessionStorage.key(i))]))"""
                ),
                "body": page.inner_text("body")[:500],
            }

        events["cookies"] = context.cookies()
        events["indexeddb"] = page.evaluate(
            """async () => {
                if (!indexedDB.databases) return {error: 'no databases()'};
                const dbs = await indexedDB.databases();
                return dbs;
            }"""
        )

        scripts = page.evaluate(
            """() => [...document.scripts].map(s => s.src || s.textContent.slice(0, 500))"""
        )
        events["scripts"] = scripts

        context.close()

    OUT.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"Requests: {len(events['requests'])}")
    print(f"Responses: {len(events['responses'])}")
    print(f"Cookies: {[c['name'] for c in events['cookies']]}")


if __name__ == "__main__":
    main()
