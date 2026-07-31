#!/usr/bin/env python3
"""CLI entrypoints for app-automation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from host.config import DEFAULT_CONFIG_PATH, EXAMPLE_CONFIG_PATH
from host.server import main as server_main
from host.service import AutomationService


def cmd_serve(args: argparse.Namespace) -> int:
    sys.argv = ["server", "--config", args.config]
    if args.host:
        sys.argv.extend(["--host", args.host])
    if args.port:
        sys.argv.extend(["--port", str(args.port)])
    server_main()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    service = AutomationService(config_path=Path(args.config))
    try:
        if args.bootstrap:
            print(json.dumps(service.bootstrap_device(), indent=2))
        job = service.create_job(kind=args.kind, account_index=args.account_index)
        # Run synchronously in this process by draining worker.
        service.ensure_worker()
        while True:
            current = service.get_job(job.id)
            if not current:
                return 1
            if current.status in {"succeeded", "failed", "cancelled"}:
                print(json.dumps(current.to_dict(), indent=2, ensure_ascii=False))
                return 0 if current.status == "succeeded" else 1
            if current.status == "waiting_otp":
                if args.otp:
                    service.submit_job_otp(job.id, args.otp)
                else:
                    print("Job waiting for OTP. Re-run with --otp CODE or use the panel.", file=sys.stderr)
                    print(json.dumps(current.to_dict(), indent=2, ensure_ascii=False))
                    return 2
            import time

            time.sleep(0.5)
    finally:
        service.shutdown()


def cmd_devices(args: argparse.Namespace) -> int:
    service = AutomationService(config_path=Path(args.config))
    try:
        devices = service.device.list_devices()
        print(json.dumps([device.__dict__ for device in devices], indent=2, default=str))
        return 0
    finally:
        service.shutdown()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app-automation", description="ExpressVPN + TikTok signup automation")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start management server + web panel")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.set_defaults(func=cmd_serve)

    run = sub.add_parser("run", help="Queue and wait for one automation job")
    run.add_argument("--kind", default="full", choices=["full", "expressvpn", "tiktok_signup"])
    run.add_argument("--account-index", type=int, default=0)
    run.add_argument("--otp", default="")
    run.add_argument("--bootstrap", action="store_true")
    run.set_defaults(func=cmd_run)

    devices = sub.add_parser("devices", help="List USB iPhones via go-ios")
    devices.set_defaults(func=cmd_devices)

    health = sub.add_parser("health", help="Print health JSON")
    def _health(args: argparse.Namespace) -> int:
        service = AutomationService(config_path=Path(args.config))
        try:
            print(json.dumps(service.health(), indent=2, ensure_ascii=False))
            return 0
        finally:
            service.shutdown()

    health.set_defaults(func=_health)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
