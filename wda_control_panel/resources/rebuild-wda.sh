#!/usr/bin/env bash
# Rebuild WebDriverAgent IPA from source and install it on a connected iPhone.
#
# Usage:
#   ./rebuild-wda.sh [bundle_id] [team_id] [device_udid]
#
# All arguments are optional — they fall back to environment variables or
# auto-detected values (connected device, config.env in ios_wda_controller).
#
# Examples:
#   ./rebuild-wda.sh
#   ./rebuild-wda.sh com.mycompany.WebDriverAgentRunner ABCD1234EF
#   DEVICE_UDID=00008030-xxx ./rebuild-wda.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PANEL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTROLLER_DIR="$(cd "$PANEL_DIR/../ios_wda_controller" && pwd)"

# ── Load config.env from ios_wda_controller if present ──────────────────────
if [[ -f "$CONTROLLER_DIR/config.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$CONTROLLER_DIR/config.env"
  set +a
fi

# ── Resolve arguments (CLI > env > defaults) ─────────────────────────────────
BUNDLE_ID="${1:-${WDA_BUNDLE_ID:-com.clicklive.WebDriverAgentRunner}}"
TEAM_ID="${2:-${DEVELOPMENT_TEAM:-}}"
DEVICE_UDID="${3:-${DEVICE_UDID:-}}"

# ── Validate required values ─────────────────────────────────────────────────
if [[ -z "$TEAM_ID" ]]; then
  echo "ERROR: DEVELOPMENT_TEAM is not set." >&2
  echo "  Set it in ios_wda_controller/config.env or pass as 2nd argument." >&2
  exit 1
fi

# ── Auto-detect device if not specified ──────────────────────────────────────
if [[ -z "$DEVICE_UDID" ]]; then
  echo "==> No device UDID specified, searching for connected device..."
  DEVICE_UDID=$(xcrun xctrace list devices 2>/dev/null \
    | grep -v '^=\|Simulator\|^$\| -- ' \
    | grep '([0-9A-F-]*-[0-9A-F]*)' \
    | head -n 1 \
    | sed -E 's/.*\(([0-9A-F-]+)\)[^(]*$/\1/') || true

  if [[ -z "$DEVICE_UDID" ]]; then
    DEVICE_UDID=$(xcrun devicectl list devices --json 2>/dev/null \
      | python3 -c "
import sys, json
data = json.load(sys.stdin)
devices = data.get('result', {}).get('devices', [])
for d in devices:
    cp = d.get('connectionProperties', {})
    dp = d.get('deviceProperties', {})
    if cp.get('transportType') == 'usb' and dp.get('isPaired'):
        print(d.get('identifier', ''))
        break
" 2>/dev/null) || true
  fi

  if [[ -z "$DEVICE_UDID" || "$DEVICE_UDID" == "null" ]]; then
    echo "ERROR: No connected iOS device found. Plug in the device and try again." >&2
    exit 1
  fi
  echo "    Found device: $DEVICE_UDID"
fi

# ── Locate WDA Xcode project ─────────────────────────────────────────────────
WDA_PROJECT="${WDA_PROJECT:-$CONTROLLER_DIR/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj}"

if [[ ! -d "$WDA_PROJECT" ]]; then
  echo "ERROR: WDA project not found at:" >&2
  echo "  $WDA_PROJECT" >&2
  echo "" >&2
  echo "Run 'npm install' inside ios_wda_controller first:" >&2
  echo "  cd $CONTROLLER_DIR && npm install" >&2
  exit 1
fi

BUNDLE_SLUG="$(printf '%s' "$BUNDLE_ID" | tr '.:' '__')"
DERIVED_DATA="$CONTROLLER_DIR/DerivedData/WDA-$BUNDLE_SLUG"
APP_PATH="$DERIVED_DATA/Build/Products/Debug-iphoneos/WebDriverAgentRunner-Runner.app"
IPA_DIR="$SCRIPT_DIR/ipa"
IPA_PATH="$IPA_DIR/WebDriverAgentRunner.ipa"

mkdir -p "$IPA_DIR"

echo ""
echo "==> Rebuild WDA"
echo "    Bundle ID:  $BUNDLE_ID"
echo "    Team ID:    $TEAM_ID"
echo "    Device:     $DEVICE_UDID"
echo "    Project:    $WDA_PROJECT"
echo "    Output IPA: $IPA_PATH"
echo ""

# ── Step 1: Build ────────────────────────────────────────────────────────────
echo "==> [1/3] Building with xcodebuild..."
rm -rf "$DERIVED_DATA"

xcodebuild \
  -project "$WDA_PROJECT" \
  -scheme WebDriverAgentRunner \
  -destination "id=$DEVICE_UDID" \
  -derivedDataPath "$DERIVED_DATA" \
  -allowProvisioningUpdates \
  CODE_SIGN_STYLE=Automatic \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID" \
  build-for-testing 2>&1 || true

if [[ ! -d "$APP_PATH" ]]; then
  echo "" >&2
  echo "ERROR: Build failed — signed app not found at:" >&2
  echo "  $APP_PATH" >&2
  exit 1
fi

echo "    Build succeeded."

# ── Step 2: Package IPA ──────────────────────────────────────────────────────
echo "==> [2/3] Packaging IPA..."
codesign --verify --deep --strict "$APP_PATH"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
mkdir -p "$STAGING/Payload"
cp -R "$APP_PATH" "$STAGING/Payload/WebDriverAgentRunner-Runner.app"
rm -f "$IPA_PATH"
(cd "$STAGING" && zip -qry "$IPA_PATH" Payload)

ACTUAL_BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP_PATH/Info.plist")"
echo "    IPA ready: $IPA_PATH"
echo "    Bundle ID: $ACTUAL_BUNDLE_ID"

# ── Step 3: Install ──────────────────────────────────────────────────────────
echo "==> [3/3] Installing on device $DEVICE_UDID..."
echo "    (Make sure the device screen is unlocked)"
echo ""

xcrun devicectl device install app --device "$DEVICE_UDID" "$APP_PATH"

echo ""
echo "==> Done. WDA is installed and ready."
echo "    Run 'ios runwda' (go-ios) or start via wda_control_panel to launch it."
