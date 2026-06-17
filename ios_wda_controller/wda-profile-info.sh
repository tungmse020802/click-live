#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="$ROOT_DIR/DerivedData/WDA/Build/Products/Debug-iphoneos/WebDriverAgentRunner-Runner.app/embedded.mobileprovision"

if [[ ! -f "$PROFILE" ]]; then
  echo "WDA provisioning profile not found. Run: npm run wda:build" >&2
  exit 1
fi

PLIST="$(mktemp)"
trap 'rm -f "$PLIST"' EXIT
security cms -D -i "$PROFILE" >"$PLIST"

read_value() {
  /usr/libexec/PlistBuddy -c "Print :$1" "$PLIST"
}

EXPIRATION="$(read_value ExpirationDate)"
EXPIRATION_NORMALIZED="$(printf '%s\n' "$EXPIRATION" | sed -E 's/ ([+-][0-9]{2}) / \100 /')"
EXPIRATION_EPOCH="$(date -j -f '%a %b %d %T %z %Y' "$EXPIRATION_NORMALIZED" '+%s')"
NOW_EPOCH="$(date '+%s')"
DAYS_LEFT="$(( (EXPIRATION_EPOCH - NOW_EPOCH + 86399) / 86400 ))"

echo "Profile: $(read_value Name)"
echo "Team: $(read_value TeamIdentifier:0)"
echo "Bundle: $(read_value Entitlements:application-identifier)"
echo "Created: $(read_value CreationDate)"
echo "Expires: $EXPIRATION"

if (( EXPIRATION_EPOCH <= NOW_EPOCH )); then
  echo "Status: EXPIRED - run npm run wda:build" >&2
  exit 2
fi

echo "Status: valid for about $DAYS_LEFT day(s)"
