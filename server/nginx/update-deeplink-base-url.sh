#!/usr/bin/env bash
# Point DEEPLINK_OPEN_BASE_URL at nginx :80 (no custom port).
set -euo pipefail

ENV_FILE="${ENV_FILE:-/root/click-live/server/telegram_bot/.env}"
BASE="${DEEPLINK_OPEN_BASE_URL:-http://160-30-19-215.sslip.io}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

python3 - <<PY
from pathlib import Path
import re

path = Path("$ENV_FILE")
text = path.read_text(encoding="utf-8")
key = "DEEPLINK_OPEN_BASE_URL"
val = "$BASE"
if re.search(rf"^{key}=", text, re.M):
    text = re.sub(rf"^{key}=.*$", f"{key}={val}", text, flags=re.M)
else:
    text = text.rstrip() + f"\n{key}={val}\n"
path.write_text(text, encoding="utf-8")
print(f"Updated {key}={val}")
PY

systemctl restart click-live-queue click-live-broadcast 2>/dev/null || true
echo "Restarted queue + broadcast services"
