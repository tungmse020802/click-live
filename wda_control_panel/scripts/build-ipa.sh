#!/usr/bin/env bash
# Build a signed WebDriverAgentRunner.ipa on macOS so it can be deployed to
# many iPhones from a Windows PC via 3uTools/Sideloadly + pymobiledevice3.
#
# Run this on the Mac that owns the Apple Developer signing identity. Output
# lands in dist/WebDriverAgentRunner.ipa and can be copied to the Windows host.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PANEL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$PANEL_ROOT/dist/wda-ipa"
mkdir -p "$DIST_DIR"

CONTROLLER_DIR="${WDA_CONTROLLER_DIR:-$PANEL_ROOT/../ios_wda_controller}"
WDA_PROJECT="${WDA_PROJECT:-$CONTROLLER_DIR/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj}"
SCHEME="${SCHEME:-WebDriverAgentRunner}"
CONFIGURATION="${CONFIGURATION:-Release}"
TEAM_ID="${TEAM_ID:?TEAM_ID is required (10-char Apple Developer team id)}"
PROVISIONING_PROFILE_NAME="${PROVISIONING_PROFILE_NAME:-}"
PROVISIONING_SPEC_PATH="${PROVISIONING_SPEC_PATH:-}"
ARCHIVE_PATH="${ARCHIVE_PATH:-$DIST_DIR/WebDriverAgent.xcarchive}"
EXPORT_DIR="${EXPORT_DIR:-$DIST_DIR/export}"

if [[ ! -d "$WDA_PROJECT" ]]; then
  echo "WDA project not found at $WDA_PROJECT" >&2
  echo "Run 'npm install' inside ios_wda_controller first, or set WDA_PROJECT." >&2
  exit 1
fi

if [[ -z "$PROVISIONING_SPEC_PATH" ]]; then
  PROVISIONING_SPEC_PATH="$DIST_DIR/exportOptions.plist"
  cat >"$PROVISIONING_SPEC_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key>
  <string>development</string>
  <key>teamID</key>
  <string>$TEAM_ID</string>
  <key>signingStyle</key>
  <string>automatic</string>
  <key>compileBitcode</key>
  <false/>
  <key>stripSwiftSymbols</key>
  <true/>
  <key>thinning</key>
  <string>&lt;none&gt;</string>
</dict>
</plist>
PLIST
fi

echo "==> Cleaning previous archive"
rm -rf "$ARCHIVE_PATH" "$EXPORT_DIR"

echo "==> Archiving WebDriverAgentRunner ($CONFIGURATION) for team $TEAM_ID"
xcodebuild \
  -project "$WDA_PROJECT" \
  -scheme "$SCHEME" \
  -configuration "$CONFIGURATION" \
  -destination "generic/platform=iOS" \
  -archivePath "$ARCHIVE_PATH" \
  CODE_SIGN_STYLE=Automatic \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  archive

echo "==> Exporting IPA"
xcodebuild \
  -exportArchive \
  -archivePath "$ARCHIVE_PATH" \
  -exportPath "$EXPORT_DIR" \
  -exportOptionsPlist "$PROVISIONING_SPEC_PATH"

IPA_SOURCE="$(find "$EXPORT_DIR" -name "*.ipa" -print -quit)"
if [[ -z "$IPA_SOURCE" ]]; then
  echo "Export finished but no .ipa was produced. Check exportOptions.plist." >&2
  exit 1
fi

FINAL_IPA="$DIST_DIR/WebDriverAgentRunner.ipa"
cp "$IPA_SOURCE" "$FINAL_IPA"
echo "==> Done"
echo "IPA ready at: $FINAL_IPA"
echo "Copy this file to the Windows PC and install it on every iPhone via 3uTools."
