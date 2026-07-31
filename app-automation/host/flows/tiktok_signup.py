from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from host.config import AppConfig, TikTokAccount
from host.wda_client import WdaClient


LogFn = Callable[[str], None]


def run_tiktok_signup(
    wda: WdaClient,
    config: AppConfig,
    account: TikTokAccount,
    *,
    otp_code: str | None = None,
    wait_for_otp: bool = True,
    screenshot_dir: Path | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    """Drive TikTok to the signup form, fill fields, then pause/wait for OTP."""

    def _log(message: str) -> None:
        if log:
            log(message)
        else:
            print(message, flush=True)

    cfg = config.tiktok_signup
    bundle_id = config.apps.tiktok_bundle_id
    shot_dir = screenshot_dir or config.screenshot_path
    shot_dir.mkdir(parents=True, exist_ok=True)
    method = (cfg.method or "email").strip().lower()
    delay = max(0.2, float(cfg.step_delay_seconds))

    identifier = (account.email if method == "email" else account.phone).strip()
    if not identifier:
        identifier = (account.email or account.phone).strip()
    if not identifier:
        return {"ok": False, "error": "account email/phone is empty"}
    if not account.password:
        return {"ok": False, "error": "account password is empty"}

    _log(f"[tiktok] activate {bundle_id}")
    wda.activate_app(bundle_id)
    time.sleep(delay)
    if config.automation.dismiss_alerts:
        wda.dismiss_system_alerts(config.automation.alert_accept_labels)

    _shot(wda, shot_dir, "tiktok_home", _log)

    if not wda.wait_and_tap_labels(cfg.open_labels, timeout_seconds=15):
        return {"ok": False, "error": "Sign up button not found", "step": "open_signup"}
    time.sleep(delay)
    if config.automation.dismiss_alerts:
        wda.dismiss_system_alerts(config.automation.alert_accept_labels)

    option_labels = cfg.email_option_labels if method == "email" else cfg.phone_option_labels
    if not wda.wait_and_tap_labels(option_labels, timeout_seconds=12):
        _log("[tiktok] phone/email option not found; continuing (UI may already be on form)")
    time.sleep(delay)

    # Some TikTok builds ask birthday before contact method.
    _fill_birthday_if_present(wda, cfg.birthday, log=_log)
    time.sleep(delay)
    wda.tap_labels(cfg.continue_labels, contains=True)
    time.sleep(delay)

    _log(f"[tiktok] filling identifier ({method}): {identifier}")
    filled = wda.fill_fields_by_index([identifier, account.password])
    if filled < 1:
        wda.fill_first_text_field(identifier)
        time.sleep(0.4)
        wda.tap_labels(cfg.continue_labels, contains=True)
        time.sleep(delay)
        wda.fill_first_text_field(account.password)

    time.sleep(delay)
    wda.tap_labels(cfg.continue_labels, contains=True)
    time.sleep(delay)
    if config.automation.dismiss_alerts:
        wda.dismiss_system_alerts(config.automation.alert_accept_labels)

    form_shot = _shot(wda, shot_dir, "tiktok_form_filled", _log)

    # OTP step: inject code, wait for operator, or hand control back to job runner.
    otp_submitted = False
    if otp_code and otp_code.strip():
        _log("[tiktok] submitting provided OTP")
        wda.fill_first_text_field(otp_code.strip())
        time.sleep(0.4)
        wda.tap_labels(cfg.continue_labels, contains=True)
        otp_submitted = True
    elif wait_for_otp:
        _log(
            f"[tiktok] waiting up to {cfg.otp_wait_seconds}s for OTP "
            "(POST /api/jobs/{id}/otp or panel input)"
        )
        deadline = time.time() + cfg.otp_wait_seconds
        while time.time() < deadline:
            if wda.page_contains(["Create username", "Create password", "For You", "Following"]):
                _log("[tiktok] left OTP screen (progress detected)")
                otp_submitted = True
                break
            time.sleep(1.5)
        if not otp_submitted:
            return {
                "ok": False,
                "error": "OTP not provided / timed out",
                "step": "otp",
                "needs_otp": True,
                "identifier": identifier,
                "screenshot": str(form_shot),
            }
    else:
        # Job runner will enter waiting_otp and accept code via API/panel.
        _log("[tiktok] paused before OTP — waiting for panel/API")
        return {
            "ok": False,
            "error": "OTP required",
            "step": "otp",
            "needs_otp": True,
            "identifier": identifier,
            "screenshot": str(form_shot),
        }

    if account.username:
        time.sleep(delay)
        if wda.page_contains(["username", "tên người dùng", "Create username"]):
            wda.fill_first_text_field(account.username)
            wda.tap_labels(cfg.continue_labels, contains=True)

    done_shot = _shot(wda, shot_dir, "tiktok_signup_done", _log)
    _log("[tiktok] signup flow finished (verify manually if captcha appeared)")
    return {
        "ok": True,
        "method": method,
        "identifier": identifier,
        "otp_submitted": otp_submitted,
        "screenshot": str(done_shot),
    }


def submit_otp(wda: WdaClient, code: str, continue_labels: list[str] | None = None) -> dict[str, Any]:
    code = (code or "").strip()
    if not code:
        return {"ok": False, "error": "empty otp"}
    wda.fill_first_text_field(code)
    time.sleep(0.3)
    labels = continue_labels or ["Continue", "Next", "Tiếp", "Confirm", "Xác nhận"]
    wda.tap_labels(labels, contains=True)
    return {"ok": True}


def _fill_birthday_if_present(wda: WdaClient, birthday: str, *, log: LogFn) -> None:
    birthday = (birthday or "").strip()
    if not birthday:
        return
    if not wda.page_contains(["When's your birthday", "birthday", "Ngày sinh", "tuổi"]):
        return
    log(f"[tiktok] birthday screen detected; using {birthday}")
    # Best-effort: type ISO date into first field / picker text entry when available.
    # Many locales use wheel pickers; operator may need to adjust ratios later.
    try:
        year, month, day = birthday.split("-")
        wda.fill_fields_by_index([month, day, year])
    except Exception as exc:  # noqa: BLE001
        log(f"[tiktok] birthday fill best-effort failed: {exc}")


def _shot(wda: WdaClient, shot_dir: Path, prefix: str, log: LogFn) -> Path | None:
    path = shot_dir / f"{prefix}_{int(time.time())}.png"
    try:
        wda.save_screenshot(path)
        log(f"[tiktok] screenshot {path.name}")
        return path
    except Exception as exc:  # noqa: BLE001
        log(f"[tiktok] screenshot failed: {exc}")
        return None
