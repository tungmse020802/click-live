#!/usr/bin/env python3
"""CLI wrapper for live shortlink decoder."""

import sys

from junb_decoder import decode_live_url


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python decode_junb.py <junb_or_thanhtai_url>", file=sys.stderr)
        sys.exit(1)
    print(decode_live_url(sys.argv[1]))


if __name__ == "__main__":
    main()
