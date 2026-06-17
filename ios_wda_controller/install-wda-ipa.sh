#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$ROOT_DIR/config.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/config.env"
  set +a
fi

: "${DEVICE_UDID:=00008030-000805902E3B802E}"
IPA="${1:-$ROOT_DIR/dist/WebDriverAgentRunner.ipa}"

if [[ ! -f "$IPA" ]]; then
  echo "IPA not found: $IPA" >&2
  echo "Create it first with: npm run wda:ipa" >&2
  exit 1
fi

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
ditto -x -k "$IPA" "$STAGING"

APP="$STAGING/Payload/WebDriverAgentRunner-Runner.app"
if [[ ! -d "$APP" ]]; then
  echo "Invalid IPA: Payload/WebDriverAgentRunner-Runner.app is missing" >&2
  exit 1
fi

codesign --verify --deep --strict "$APP"
echo "Installing $(basename "$IPA") on $DEVICE_UDID..."
xcrun devicectl device install app --device "$DEVICE_UDID" "$APP"
echo "WDA installed. Launch it with Appium/XCTest; it is not a standalone iPhone app."
