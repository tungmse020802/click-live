#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$ROOT_DIR/DerivedData/WDA/Build/Products/Debug-iphoneos/WebDriverAgentRunner-Runner.app"
OUTPUT_DIR="$ROOT_DIR/dist"
IPA="$OUTPUT_DIR/WebDriverAgentRunner.ipa"

if [[ ! -d "$APP" ]]; then
  echo "Signed WDA app not found. Run: npm run wda:build" >&2
  exit 1
fi

"$ROOT_DIR/wda-profile-info.sh"
codesign --verify --deep --strict "$APP"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
mkdir -p "$STAGING/Payload" "$OUTPUT_DIR"
ditto "$APP" "$STAGING/Payload/WebDriverAgentRunner-Runner.app"
rm -f "$IPA"
(
  cd "$STAGING"
  ditto -c -k --sequesterRsrc --keepParent Payload "$IPA"
)

echo "IPA created: $IPA"
echo "Bundle ID: $(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP/Info.plist")"
du -h "$IPA"
