#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT/resources/bin/win32"
OUT="$OUT_DIR/click-helper.exe"
SRC="$ROOT/click-helper"

mkdir -p "$OUT_DIR"

if ! command -v go >/dev/null 2>&1; then
  echo "Go chua cai. Cai Go 1.22+ roi chay lai, hoac build tren Windows:"
  echo "  cd click-helper && go build -o ..\\resources\\bin\\win32\\click-helper.exe ."
  exit 1
fi

echo "Building click-helper.exe (windows/amd64)..."
(
  cd "$SRC"
  GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o "$OUT" .
)

ls -lh "$OUT"
echo "Done: $OUT"
