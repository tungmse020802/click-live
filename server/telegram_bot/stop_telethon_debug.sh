#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
pid_path="data/telethon_reader_debug.pid"

if [ ! -f "$pid_path" ]; then
  echo "Telethon debug reader is not running"
  exit 0
fi

pid="$(cat "$pid_path" || true)"
if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  echo "Stopped Telethon debug reader pid=$pid"
else
  echo "Telethon debug reader process not found"
fi

rm -f "$pid_path"
