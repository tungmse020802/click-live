#!/usr/bin/env python3
"""Debug queue TIME vs Telegram/queue clocks.

Usage:
  python3 scripts/debug_queue_timing.py --url http://127.0.0.1:8787 --user admin --password '...'
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from time_parse import extract_time_from_item  # noqa: E402


def login(base: str, user: str, password: str) -> urllib.request.OpenerDirector:
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(
        f"{base.rstrip('/')}/api/auth/login",
        data=json.dumps({"username": user, "password": password}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "login failed")
    return opener


def fetch_queue(opener: urllib.request.OpenerDirector, base: str, limit: int) -> dict:
    url = f"{base.rstrip('/')}/api/queue?limit={limit}"
    with opener.open(url, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fmt_ts(value: float | int | None) -> str:
    if value is None:
        return "—"
    sec = float(value)
    if sec > 1e12:
        sec /= 1000.0
    return datetime.fromtimestamp(sec).strftime("%H:%M:%S")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8787")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", required=True)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    try:
        opener = login(args.url, args.user, args.password)
        data = fetch_queue(opener, args.url, args.limit)
    except (urllib.error.URLError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    now = datetime.now()
    print(f"server generated_at: {data.get('generated_at')}")
    print(f"local now: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"latest_id: {data.get('latest_id')}")
    print()

    issues = 0
    for item in data.get("items") or []:
        text = (item.get("message") or {}).get("text") or ""
        if "TIME" not in text and "time" not in text.lower():
            continue
        meta = item.get("time_meta") or extract_time_from_item(item)
        tg = (item.get("payload") or {}).get("telegram_timestamp_ms")
        target = str(meta.get("target_time_hhmmss") or "")
        print(f"#{item.get('id')} [{item.get('status')}] label={meta.get('label')}")
        print(f"  telegram: {fmt_ts(tg)}  queue: {fmt_ts(item.get('created_at'))}")
        if target:
            hh, mm, ss = map(int, target.split(":"))
            t = now.replace(hour=hh % 24, minute=mm, second=ss, microsecond=0)
            print(f"  target:   {target}  in {(t - now).total_seconds():.0f}s")
        if item.get("time_meta") is None:
            print("  WARN: API chưa có time_meta — deploy queue_ui mới")
            issues += 1
        delay_s = (meta.get("click_after_ms") or 0) / 1000.0
        if tg and target and delay_s:
            hh, mm, ss = map(int, target.split(":"))
            t = datetime.fromtimestamp(tg / 1000).replace(
                hour=hh % 24, minute=mm, second=ss, microsecond=0
            )
            skew = (t - datetime.fromtimestamp(tg / 1000)).total_seconds() - delay_s
            if abs(skew) > 5:
                print(f"  WARN: countdown lệch {skew:.0f}s so với label")
                issues += 1
        junb = item.get("junb_end_time_ms")
        if junb and target:
            hh, mm, ss = map(int, target.split(":"))
            msg_target = now.replace(hour=hh % 24, minute=mm, second=ss, microsecond=0)
            drift = (junb / 1000.0) - msg_target.timestamp()
            if abs(drift) > 2:
                print(f"  WARN: junb end_time lệch {drift:.1f}s so với TIME tin")
                issues += 1
        print()

    print(f"done — {issues} warning(s)")
    return 0 if issues == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
