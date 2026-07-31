import time

from playwright.sync_api import BrowserContext, Page

from config import DEVICE_ID, LOCALE, PROFILE_DIR, TIMEZONE_ID, VIEWPORT


def launch_context(playwright, *, headless: bool = False, inject_device: bool | None = None) -> BrowserContext:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        viewport=VIEWPORT,
        locale=LOCALE,
        timezone_id=TIMEZONE_ID,
    )

    should_inject = inject_device if inject_device is not None else bool(DEVICE_ID)
    if should_inject and DEVICE_ID:
        page = context.pages[0] if context.pages else context.new_page()
        ensure_device_cookie(context, page)

    return context


def ensure_device_cookie(context: BrowserContext, page: Page | None = None) -> None:
    """Replace stale device_id from persistent profile before any thanhtai.io request."""
    if not DEVICE_ID:
        raise RuntimeError("DEVICE_ID trong config.py dang trong. Dung setup_profile.py de dang ky truoc.")

    if page is None:
        page = context.pages[0] if context.pages else context.new_page()

    device_cookie = {
        "name": "device_id",
        "value": DEVICE_ID,
        "domain": "thanhtai.io",
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "sameSite": "Lax",
        "expires": int(time.time()) + 365 * 24 * 3600,
    }

    remaining = [
        cookie
        for cookie in context.cookies()
        if cookie.get("name") != "device_id" or "thanhtai" not in cookie.get("domain", "")
    ]
    context.clear_cookies()
    if remaining:
        context.add_cookies(remaining)

    client = context.new_cdp_session(page)
    client.send("Network.enable")
    for domain in ("thanhtai.io", ".thanhtai.io"):
        client.send("Network.deleteCookies", {"name": "device_id", "domain": domain})

    client.send("Network.setCookie", device_cookie)
    context.add_cookies([device_cookie])

    cookies = client.send(
        "Network.getCookies",
        {"urls": ["https://thanhtai.io/", "https://thanhtai.io/r/525ddbd53026"]},
    )["cookies"]
    current = next((cookie for cookie in cookies if cookie["name"] == "device_id"), None)
    if not current or current["value"] != DEVICE_ID:
        raise RuntimeError(
            f"Khong set duoc device_id cookie. "
            f"Mong doi {DEVICE_ID}, thuc te {current!r}"
        )


def read_device_cookie(context: BrowserContext) -> str | None:
    cookies = context.cookies("https://thanhtai.io")
    match = next((cookie for cookie in cookies if cookie["name"] == "device_id"), None)
    value = (match or {}).get("value") or ""
    return value or None


def ensure_device_cookie_if_missing(context: BrowserContext, page: Page | None = None) -> str | None:
    """Add device_id only when absent. Never clears profile or other cookies."""
    current = read_device_cookie(context)
    if current:
        return current
    if not DEVICE_ID:
        return None

    if page is None:
        page = context.pages[0] if context.pages else context.new_page()

    device_cookie = {
        "name": "device_id",
        "value": DEVICE_ID,
        "domain": "thanhtai.io",
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "sameSite": "Lax",
        "expires": int(time.time()) + 365 * 24 * 3600,
    }
    context.add_cookies([device_cookie])

    client = context.new_cdp_session(page)
    client.send("Network.enable")
    client.send("Network.setCookie", device_cookie)
    return read_device_cookie(context)
