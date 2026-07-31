from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from host.config import AppConfig, ExpressVpnConfig
from host.wda_client import WdaClient


LogFn = Callable[[str], None]


def run_expressvpn_connect(
    wda: WdaClient,
    config: AppConfig,
    *,
    screenshot_dir: Path | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    """Open ExpressVPN, optionally pick a location, then connect and wait for Connected."""

    def _log(message: str) -> None:
        if log:
            log(message)
        else:
            print(message, flush=True)

    vpn = config.expressvpn
    bundle_id = config.apps.expressvpn_bundle_id
    shot_dir = screenshot_dir or config.screenshot_path
    shot_dir.mkdir(parents=True, exist_ok=True)

    _log(f"[expressvpn] activate {bundle_id}")
    wda.activate_app(bundle_id)
    time.sleep(vpn.settle_seconds)
    if config.automation.dismiss_alerts:
        wda.dismiss_system_alerts(config.automation.alert_accept_labels)

    before = shot_dir / f"expressvpn_before_{int(time.time())}.png"
    try:
        wda.save_screenshot(before)
        _log(f"[expressvpn] screenshot {before.name}")
    except Exception as exc:  # noqa: BLE001
        _log(f"[expressvpn] screenshot failed: {exc}")

    if vpn.preferred_location.strip():
        _select_location(wda, vpn, log=_log)
        time.sleep(vpn.settle_seconds)

    if wda.page_contains(vpn.connected_texts):
        _log("[expressvpn] already connected")
        return {"ok": True, "already_connected": True, "screenshot": str(before)}

    tapped = wda.wait_and_tap_labels(vpn.connect_labels, timeout_seconds=12)
    if not tapped:
        _log(
            "[expressvpn] connect label not found; tapping power button fallback "
            f"({vpn.power_button_x_ratio}, {vpn.power_button_y_ratio})"
        )
        try:
            wda.tap_ratio(vpn.power_button_x_ratio, vpn.power_button_y_ratio)
            tapped = True
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"connect control not found: {exc}"}

    _log("[expressvpn] waiting for Connected…")
    connected = wda.wait_for_texts(vpn.connected_texts, timeout_seconds=vpn.connect_timeout_seconds)
    after = shot_dir / f"expressvpn_after_{int(time.time())}.png"
    try:
        wda.save_screenshot(after)
    except Exception as exc:  # noqa: BLE001
        _log(f"[expressvpn] after screenshot failed: {exc}")

    if not connected:
        return {
            "ok": False,
            "error": "timed out waiting for Connected state",
            "tapped_connect": tapped,
            "screenshot": str(after),
        }

    _log("[expressvpn] connected")
    return {
        "ok": True,
        "already_connected": False,
        "tapped_connect": tapped,
        "screenshot": str(after),
    }


def _select_location(wda: WdaClient, vpn: ExpressVpnConfig, *, log: LogFn) -> None:
    location = vpn.preferred_location.strip()
    if not location:
        return
    log(f"[expressvpn] selecting location: {location}")
    opened = wda.wait_and_tap_labels(vpn.location_search_labels, timeout_seconds=8)
    if not opened:
        log("[expressvpn] location picker not found; continuing with current server")
        return
    time.sleep(1.0)
    # Try search field then type country/city.
    try:
        wda.fill_first_text_field(location)
        time.sleep(1.0)
    except Exception as exc:  # noqa: BLE001
        log(f"[expressvpn] location search type failed: {exc}")
    if not wda.tap_labels([location], contains=True):
        log("[expressvpn] preferred location row not tapped; leaving picker as-is")
    time.sleep(0.8)
