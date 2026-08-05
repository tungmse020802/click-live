#!/usr/bin/env bash
# Import TELEGRAM_CLIENT_TARGETS từ .env.app2 vào watch_groups (reader_id=app2) trong DB.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
if [[ -x ".venv/bin/python3" ]]; then
  PYTHON=".venv/bin/python3"
fi

"$PYTHON" - <<'PY'
import os
from pathlib import Path

from dotenv import load_dotenv

from config import _parse_client_targets
from db import ChatDatabase

load_dotenv(Path(".env.app2"))
load_dotenv(Path(".env"))

raw = os.environ.get("TELEGRAM_CLIENT_TARGETS", "").strip()
if not raw:
    raise SystemExit("TELEGRAM_CLIENT_TARGETS trống trong .env.app2")

targets = _parse_client_targets(raw, "")
if not targets:
    raise SystemExit("Không parse được target từ .env.app2")

db_path = os.environ.get("BOT_DB_PATH", "data/chatbot.sqlite3")
db = ChatDatabase(db_path)
db.init_schema()

existing = {g["chat_id"] for g in db.list_watch_groups(reader_id="app2")}
merged = list(db.list_watch_groups(reader_id="app2"))
imported = 0
for target in targets:
    chat_id = target.chat_ref or target.entity_ref
    if chat_id in existing:
        continue
    merged.append(
        {
            "reader_id": "app2",
            "name": target.label,
            "chat_id": chat_id,
            "enabled": True,
        }
    )
    existing.add(chat_id)
    imported += 1

if imported:
    db.replace_watch_groups_for_reader("app2", merged)

print(f"app2 watch_groups: {len(merged)} total, imported {imported} new")
PY
