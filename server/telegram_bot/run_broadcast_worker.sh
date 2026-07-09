#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p data/logs

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export BOT_LOG_LEVEL="${BOT_LOG_LEVEL:-INFO}"
export PYTHONUNBUFFERED=1

log_path="data/logs/broadcast_worker.log"
pid_path="data/broadcast_worker.pid"

if [ -f "$pid_path" ]; then
  old_pid="$(cat "$pid_path" || true)"
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Broadcast worker already running pid=$old_pid"
    echo "Log: $log_path"
    exit 0
  fi
fi

nohup python3 broadcast_worker.py >> "$log_path" 2>&1 &
pid="$!"
echo "$pid" > "$pid_path"

sleep 2
if ! kill -0 "$pid" 2>/dev/null; then
  rm -f "$pid_path"
  echo "Broadcast worker exited during startup"
  echo "Log: $log_path"
  tail -40 "$log_path" || true
  exit 1
fi

echo "Started broadcast worker pid=$pid"
echo "Log: $log_path"
