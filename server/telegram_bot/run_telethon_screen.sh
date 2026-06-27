#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p data/logs

session_name="${1:-telethon_debug}"
log_path="data/logs/${session_name}.log"

if pgrep -f "python3 telethon_reader.py" >/dev/null; then
  echo "Telethon reader already running:"
  pgrep -fl "python3 telethon_reader.py" || true
  echo "Log: $log_path"
  exit 0
fi

if screen -list | grep -q "[.]${session_name}[[:space:]]"; then
  echo "screen session already running: $session_name"
  echo "Attach: screen -r $session_name"
  echo "Log: $log_path"
  exit 0
fi

screen -dmS "$session_name" /bin/zsh -lc "
  cd '$PWD'
  source .venv/bin/activate
  export BOT_LOG_LEVEL=INFO
  export PYTHONUNBUFFERED=1
  python3 telethon_reader.py 2>&1 | tee -a '$log_path'
"

echo "Started screen session: $session_name"
echo "Attach: screen -r $session_name"
echo "Detach after attach: Ctrl-A then D"
echo "Log: $log_path"
