"""Resolve thanhtai.io referral links via Playwright + network capture."""

from __future__ import annotations

import atexit
import queue
import re
import threading
import time
from typing import Any, Callable

from playwright.sync_api import Page, Playwright, Request, sync_playwright

from browser import ensure_device_cookie_if_missing, launch_context, read_device_cookie
from thanhtai_http import extract_deeplink_from_html

DEEPLINK_PATTERN = re.compile(r"snssdk1180://live\?room_id=\d+")
JUNB_LIVE_PATTERN = re.compile(r"https://i\.junb\.io\.vn/i/\?[A-Za-z0-9_-]+")

_playwright: Playwright | None = None
_context = None
_worker_thread: threading.Thread | None = None
_task_queue: queue.Queue[tuple[str, dict[str, Any], threading.Event] | None] | None = None
_worker_lock = threading.Lock()


def _collect_deeplinks(target: list[str], source: str) -> None:
    for match in DEEPLINK_PATTERN.findall(source or ""):
        if match not in target:
            target.append(match)


def _attach_capture(page: Page, captured: list[str], done: threading.Event) -> None:
    def on_request(request: Request) -> None:
        before = len(captured)
        _collect_deeplinks(captured, request.url)
        if len(captured) > before:
            done.set()

    page.on("request", on_request)


def _wait_capture(
    page: Page,
    captured: list[str],
    done: threading.Event,
    *,
    timeout_ms: int,
    after_goto: Callable[[], None] | None = None,
) -> str | None:
    if after_goto is not None:
        after_goto()

    if done.wait(timeout=max(0, timeout_ms) / 1000):
        return captured[0]

    if captured:
        return captured[0]

    _collect_deeplinks(captured, page.content())
    return captured[0] if captured else None


def _ensure_browser(*, headless: bool = True) -> None:
    global _playwright, _context

    if _context is not None:
        return

    _playwright = sync_playwright().start()
    _context = launch_context(_playwright, headless=headless, inject_device=False)
    page = _context.pages[0] if _context.pages else _context.new_page()
    ensure_device_cookie_if_missing(_context, page)
    if not read_device_cookie(_context):
        raise ValueError(
            "Missing thanhtai device_id cookie. "
            "Set THANHTAI_DEVICE_ID env or register device via setup_profile.py."
        )


def _resolve_on_worker(
    url: str,
    *,
    timeout_ms: int = 12000,
    headless: bool = True,
) -> str:
    clean_url = (url or "").strip()
    if not clean_url:
        raise ValueError("Missing thanhtai URL")

    _ensure_browser(headless=headless)

    captured: list[str] = []
    done = threading.Event()
    page = _context.new_page()
    try:
        _attach_capture(page, captured, done)

        def _after_goto() -> None:
            page.goto(clean_url, wait_until="commit", timeout=timeout_ms)
            html_deeplink = extract_deeplink_from_html(page.content())
            if html_deeplink:
                captured.append(html_deeplink)
                done.set()
                return
            if done.is_set():
                return
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

        deeplink = _wait_capture(
            page,
            captured,
            done,
            timeout_ms=timeout_ms,
            after_goto=_after_goto,
        )
        if deeplink:
            return deeplink

        junb_match = JUNB_LIVE_PATTERN.search(page.content())
        if junb_match:
            from junb_decoder import decode_live_url

            return decode_live_url(junb_match.group(0))

        raise ValueError(
            "Playwright did not capture snssdk1180 deeplink. "
            "Check thanhtai profile/device access."
        )
    finally:
        page.close()


def _worker_loop() -> None:
    assert _task_queue is not None
    while True:
        item = _task_queue.get()
        try:
            if item is None:
                return
            url, holder, event = item
            try:
                if url == "__warm__":
                    _ensure_browser(headless=bool(holder.get("headless", True)))
                    holder["result"] = "ok"
                else:
                    holder["result"] = _resolve_on_worker(
                        url,
                        timeout_ms=int(holder.get("timeout_ms", 12000)),
                        headless=bool(holder.get("headless", True)),
                    )
            except Exception as exc:
                holder["error"] = exc
            finally:
                event.set()
        finally:
            _task_queue.task_done()


def _ensure_worker() -> None:
    global _worker_thread, _task_queue
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _task_queue = queue.Queue()
        _worker_thread = threading.Thread(
            target=_worker_loop,
            name="thanhtai-playwright",
            daemon=True,
        )
        _worker_thread.start()


def _shutdown_browser() -> None:
    global _playwright, _context, _worker_thread, _task_queue

    if _task_queue is not None:
        _task_queue.put(None)
    if _worker_thread is not None:
        _worker_thread.join(timeout=5)
        _worker_thread = None
        _task_queue = None

    if _context is not None:
        try:
            _context.close()
        except Exception:
            pass
        _context = None
    if _playwright is not None:
        try:
            _playwright.stop()
        except Exception:
            pass
        _playwright = None


atexit.register(_shutdown_browser)


def warm_browser(*, headless: bool = True) -> None:
    """Pre-launch Chromium on the dedicated worker thread."""
    _ensure_worker()
    assert _task_queue is not None

    holder: dict[str, Any] = {"headless": headless}
    event = threading.Event()
    _task_queue.put(("__warm__", holder, event))
    if not event.wait(timeout=60):
        raise TimeoutError("Playwright warm-up timed out")
    if holder.get("error"):
        raise holder["error"]


def resolve_thanhtai_via_playwright(
    url: str,
    *,
    timeout_ms: int = 12000,
    headless: bool = True,
) -> str:
    """Queue resolve on the Playwright worker thread (sync API is not thread-safe)."""
    if url == "__warm__":
        raise ValueError("Reserved warm-up URL")

    _ensure_worker()
    assert _task_queue is not None

    holder: dict[str, Any] = {"headless": headless, "timeout_ms": timeout_ms}
    event = threading.Event()
    _task_queue.put((url, holder, event))
    if not event.wait(timeout=(timeout_ms / 1000) + 30):
        raise TimeoutError(f"Playwright resolve timed out for {url}")

    if holder.get("error"):
        raise holder["error"]
    result = holder.get("result")
    if not result:
        raise ValueError("Playwright resolve returned empty result")
    return result
