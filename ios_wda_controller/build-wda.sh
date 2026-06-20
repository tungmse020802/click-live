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

: "${DEVICE_UDID:=00008030-000805902E3B802E}"
: "${DEVELOPMENT_TEAM:=827H4SVZSB}"
: "${WDA_BUNDLE_ID:=com.tungld.clicklive.WebDriverAgentRunner}"

WDA_PROJECT="$ROOT_DIR/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj"

if [[ ! -d "$WDA_PROJECT" ]]; then
  echo "WDA project not found. Run npm install first." >&2
  exit 1
fi

echo "Building WDA for $DEVICE_UDID"
echo "Team: $DEVELOPMENT_TEAM"
echo "Bundle ID: $WDA_BUNDLE_ID.xctrunner"

xcodebuild \
  -project "$WDA_PROJECT" \
  -scheme WebDriverAgentRunner \
  -destination "id=$DEVICE_UDID" \
  -derivedDataPath "$ROOT_DIR/DerivedData/WDA" \
  -allowProvisioningUpdates \
  CODE_SIGN_STYLE=Automatic \
  DEVELOPMENT_TEAM="$DEVELOPMENT_TEAM" \
  PRODUCT_BUNDLE_IDENTIFIER="$WDA_BUNDLE_ID" \
  build-for-testing
