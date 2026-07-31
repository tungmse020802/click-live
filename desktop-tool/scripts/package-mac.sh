#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> npm install"
npm install

echo "==> Build macOS (dmg + zip) — chạy trên Mac"
npm run dist:mac

OUT="dist"
echo ""
echo "Xong. File trong ${OUT}/:"
ls -la "${OUT}/"*.dmg "${OUT}/"*.zip 2>/dev/null || ls -la "${OUT}/"

echo ""
echo "Copy .env cạnh file .app (cùng thư mục chứa Click Live Desktop Tool.app):"
echo "  cp .env.example /path/to/Click\\ Live\\ Desktop\\ Tool.app/../.env"
