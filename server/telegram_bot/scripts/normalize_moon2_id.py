#!/usr/bin/env python3
"""Normalize moon_2 watch chat_id to Telegram channel peer id."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

CANONICAL = "-1003431776950"
ALIASES = ("-3431776950", "-1003431776950")


def main() -> None:
    db = Path("data/chatbot.sqlite3")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "UPDATE watch_groups SET chat_id=?, enabled=1 WHERE reader_id=? AND name=?",
        (CANONICAL, "app1", "moon_2"),
    )
    print("watch_groups", cur.rowcount)
    cur = conn.execute(
        "UPDATE reader_group_filters SET chat_id=? WHERE reader_id=? AND chat_id IN (?,?)",
        (CANONICAL, "app1", *ALIASES),
    )
    print("filters", cur.rowcount)
    for r in conn.execute(
        "SELECT name, chat_id, enabled FROM watch_groups WHERE name=? OR chat_id IN (?,?)",
        ("moon_2", *ALIASES),
    ):
        print("row", tuple(r))
    conn.commit()
    conn.close()

    env = Path(".env")
    text = env.read_text(encoding="utf-8")
    updated = re.sub(
        r"^TELEGRAM_CLIENT_TARGETS=.*$",
        'TELEGRAM_CLIENT_TARGETS="#-1003431776950;#-1003792359700"',
        text,
        flags=re.M,
    )
    # also replace bare alias if present elsewhere in targets line
    updated = updated.replace("#-3431776950", "#-1003431776950")
    env.write_text(updated, encoding="utf-8")
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("TELEGRAM_CLIENT_TARGETS"):
            print(line)


if __name__ == "__main__":
    main()
