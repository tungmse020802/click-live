#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$ROOT_DIR/DerivedData/WDA/Build/Products/Debug-iphoneos/WebDriverAgentRunner-Runner.app"
OUTPUT_DIR="$ROOT_DIR/dist"
UDID="${DEVICE_UDID:-unknown}"
IPA="$OUTPUT_DIR/WebDriverAgentRunner-${UDID}.ipa"

if [[ ! -d "$APP" ]]; then
  echo "Signed WDA app not found. Run: npm run wda:build" >&2
  exit 1
fi

"$ROOT_DIR/wda-profile-info.sh"
codesign --verify --deep --strict "$APP"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
mkdir -p "$STAGING/Payload" "$OUTPUT_DIR"
cp -R "$APP" "$STAGING/Payload/WebDriverAgentRunner-Runner.app"
rm -f "$IPA"
(
  cd "$STAGING"
  zip -qry "$IPA" Payload
)

echo "IPA created: $IPA"
echo "Bundle ID: $(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP/Info.plist")"
du -h "$IPA"
