#!/usr/bin/env bash
set -euo pipefail

session_name="${1:-telethon_debug}"

if screen -list | grep -q "[.]${session_name}[[:space:]]"; then
  screen -S "$session_name" -X quit
fi

pkill -f "python3 telethon_reader.py" 2>/dev/null || true
pkill -f "SCREEN -dmS ${session_name}" 2>/dev/null || true
echo "Stopped Telethon reader processes for session: $session_name"
