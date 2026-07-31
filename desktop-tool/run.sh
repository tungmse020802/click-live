#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="$(cd "$(dirname "$0")" && pwd)"

echo "==> git pull ($ROOT)"
cd "$ROOT"
git pull --ff-only

echo "==> desktop-tool ($TOOL)"
cd "$TOOL"

if [[ ! -f .env ]] && [[ -f .env.example ]]; then
  cp .env.example .env
  echo "[info] Created .env — chỉ cần DESKTOP_TOOL_QUEUE_URL. Login user trong app."
fi

if [[ ! -d node_modules/electron ]] || [[ package-lock.json -nt node_modules/.package-lock.json ]]; then
  echo "==> npm install"
  npm install
fi

echo "==> npm start"
exec npm start
