#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -f config.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source config.env
  set +a
fi

usage() {
  cat <<'EOF'
Usage:
  ./build-wda-ipa-with-bundle.sh <bundle_id> [team_id]

Example:
  ./build-wda-ipa-with-bundle.sh com.tungld.clicklive.WebDriverAgentRunner 827H4SVZSB

Environment overrides:
  DEVELOPMENT_TEAM          Apple Team ID. Required if team_id arg is omitted.
  WDA_PROJECT               Path to WebDriverAgent.xcodeproj.
  DERIVED_DATA_PATH         Custom DerivedData output directory.
  OUTPUT_IPA                Custom output IPA path.
  COPY_TO_PANEL             1 to copy IPA into ../wda_control_panel/resources/ipa/WebDriverAgentRunner.ipa
                            0 to skip the copy step. Default: 1
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

BUNDLE_ID="${1:-${WDA_BUNDLE_ID:-}}"
TEAM_ID="${2:-${DEVELOPMENT_TEAM:-}}"

if [[ -z "$BUNDLE_ID" ]]; then
  echo "Missing bundle_id." >&2
  usage >&2
  exit 1
fi

if [[ -z "$TEAM_ID" ]]; then
  echo "Missing team_id / DEVELOPMENT_TEAM." >&2
  usage >&2
  exit 1
fi

WDA_PROJECT="${WDA_PROJECT:-$ROOT_DIR/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj}"
if [[ ! -d "$WDA_PROJECT" ]]; then
  echo "WDA project not found at $WDA_PROJECT" >&2
  echo "Run 'npm install' inside ios_wda_controller first, or set WDA_PROJECT." >&2
  exit 1
fi

BUNDLE_SLUG="$(printf '%s' "$BUNDLE_ID" | tr '.:' '__')"
DERIVED_DATA_PATH="${DERIVED_DATA_PATH:-$ROOT_DIR/DerivedData/WDA-$BUNDLE_SLUG}"
APP_PATH="$DERIVED_DATA_PATH/Build/Products/Debug-iphoneos/WebDriverAgentRunner-Runner.app"
OUTPUT_DIR="$(dirname "${OUTPUT_IPA:-$ROOT_DIR/dist/WebDriverAgentRunner-$BUNDLE_SLUG.ipa}")"
OUTPUT_IPA="${OUTPUT_IPA:-$ROOT_DIR/dist/WebDriverAgentRunner-$BUNDLE_SLUG.ipa}"
COPY_TO_PANEL="${COPY_TO_PANEL:-1}"
PANEL_IPA_TARGET="$ROOT_DIR/../wda_control_panel/resources/ipa/WebDriverAgentRunner.ipa"

echo "==> Building WDA IPA"
echo "Team ID:    $TEAM_ID"
echo "Bundle ID:  $BUNDLE_ID"
echo "Project:    $WDA_PROJECT"
echo "DerivedData:$DERIVED_DATA_PATH"
echo "Output IPA: $OUTPUT_IPA"

rm -rf "$DERIVED_DATA_PATH"
mkdir -p "$OUTPUT_DIR"

xcodebuild \
  -project "$WDA_PROJECT" \
  -scheme WebDriverAgentRunner \
  -destination "generic/platform=iOS" \
  -derivedDataPath "$DERIVED_DATA_PATH" \
  -allowProvisioningUpdates \
  CODE_SIGN_STYLE=Automatic \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID" \
  build-for-testing

if [[ ! -d "$APP_PATH" ]]; then
  echo "Signed WDA app not found at $APP_PATH" >&2
  exit 1
fi

codesign --verify --deep --strict "$APP_PATH"

STAGING_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGING_DIR"' EXIT
mkdir -p "$STAGING_DIR/Payload"
cp -R "$APP_PATH" "$STAGING_DIR/Payload/WebDriverAgentRunner-Runner.app"
rm -f "$OUTPUT_IPA"
(
  cd "$STAGING_DIR"
  zip -qry "$OUTPUT_IPA" Payload
)

ACTUAL_BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP_PATH/Info.plist")"
echo "==> IPA created"
echo "App bundle: $ACTUAL_BUNDLE_ID"
echo "IPA path:   $OUTPUT_IPA"

if [[ "$COPY_TO_PANEL" == "1" && -d "$(dirname "$PANEL_IPA_TARGET")" ]]; then
  cp "$OUTPUT_IPA" "$PANEL_IPA_TARGET"
  echo "Copied IPA to: $PANEL_IPA_TARGET"
fi

