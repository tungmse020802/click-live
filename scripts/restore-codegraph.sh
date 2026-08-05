#!/usr/bin/env bash
# Khôi phục index CodeGraph từ file snapshot click-live.codegraph
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:-$ROOT/click-live.codegraph}"
DEST_DIR="$ROOT/.codegraph"
DEST_DB="$DEST_DIR/codegraph.db"

if [[ ! -f "$SRC" ]]; then
  echo "Không tìm thấy: $SRC" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
rm -f "$DEST_DB" "$DEST_DB-wal" "$DEST_DB-shm"
cp "$SRC" "$DEST_DB"
echo "OK — restored $DEST_DB from $SRC"
npx --yes @colbymchenry/codegraph status "$ROOT" 2>/dev/null || true
