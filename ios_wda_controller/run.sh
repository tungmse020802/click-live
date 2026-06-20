#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

USER_RUN_ONCE="${RUN_ONCE-}"
USER_TREASURE_DEBUG_MODE="${TREASURE_DEBUG_MODE-}"
USER_TREASURE_TAP_ENABLED="${TREASURE_TAP_ENABLED-}"
USER_DEEPLINK_OPEN_MODE="${DEEPLINK_OPEN_MODE-}"

if [[ -f config.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source config.env
  set +a
fi
[[ -n "${USER_RUN_ONCE}" ]] && RUN_ONCE="$USER_RUN_ONCE"
[[ -n "${USER_TREASURE_DEBUG_MODE}" ]] && TREASURE_DEBUG_MODE="$USER_TREASURE_DEBUG_MODE"
[[ -n "${USER_TREASURE_TAP_ENABLED}" ]] && TREASURE_TAP_ENABLED="$USER_TREASURE_TAP_ENABLED"
[[ -n "${USER_DEEPLINK_OPEN_MODE}" ]] && DEEPLINK_OPEN_MODE="$USER_DEEPLINK_OPEN_MODE"

: "${DEVICE_UDID:=00008030-000805902E3B802E}"

# Check if the device is available, if not, try to find any connected device
if ! xcrun xctrace list devices 2>/dev/null | grep -q "$DEVICE_UDID"; then
  echo "Device $DEVICE_UDID not found or offline. Searching for any connected device..."
  DETECTED_UDID=$("$ROOT_DIR/get-connected-device.sh")
  if [[ -n "$DETECTED_UDID" ]]; then
    echo "Found device: $DETECTED_UDID. Using it instead."
    DEVICE_UDID="$DETECTED_UDID"
  fi
fi

: "${APPIUM_URL:=http://127.0.0.1:4723}"

WDA_PROJECT="$ROOT_DIR/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj"
WDA_LOG="$ROOT_DIR/wda.log"
APPIUM_LOG="$ROOT_DIR/appium.log"
WDA_PID=""
APPIUM_PID=""

cleanup() {
  [[ -n "$APPIUM_PID" ]] && kill "$APPIUM_PID" 2>/dev/null || true
  [[ -n "$WDA_PID" ]] && kill "$WDA_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [[ ! -d "$WDA_PROJECT" ]]; then
  echo "WDA project not found. Run npm install first." >&2
  exit 1
fi

if ! "$ROOT_DIR/wda-profile-info.sh"; then
  echo "Build and sign WDA before starting: npm run wda:build" >&2
  exit 1
fi

: > "$WDA_LOG"
: > "$APPIUM_LOG"

echo "Starting WebDriverAgent on $DEVICE_UDID..."
xcodebuild \
  -project "$WDA_PROJECT" \
  -scheme WebDriverAgentRunner \
  -destination "id=$DEVICE_UDID" \
  -derivedDataPath "$ROOT_DIR/DerivedData/WDA" \
  test-without-building >"$WDA_LOG" 2>&1 &
WDA_PID=$!

WDA_URL=""
for _ in $(seq 1 60); do
  WDA_URL="$(sed -n 's/.*ServerURLHere->\(http[^<]*\)<-ServerURLHere.*/\1/p' "$WDA_LOG" | tail -1)"
  [[ -n "$WDA_URL" ]] && break
  if ! kill -0 "$WDA_PID" 2>/dev/null; then
    tail -40 "$WDA_LOG" >&2
    exit 1
  fi
  sleep 1
done

if [[ -z "$WDA_URL" ]]; then
  echo "Timed out waiting for WDA. Keep the iPhone unlocked and check $WDA_LOG." >&2
  exit 1
fi

if ! curl -fsS --max-time 5 "$WDA_URL/status" >/dev/null; then
  echo "WDA announced $WDA_URL but is not reachable." >&2
  exit 1
fi

echo "WDA ready at $WDA_URL"
echo "Starting Appium..."
npx appium \
  --address 127.0.0.1 \
  --port 4723 \
  --base-path / \
  --log-level info >"$APPIUM_LOG" 2>&1 &
APPIUM_PID=$!

for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 "$APPIUM_URL/status" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$APPIUM_PID" 2>/dev/null; then
    tail -40 "$APPIUM_LOG" >&2
    exit 1
  fi
  sleep 1
done

if ! curl -fsS --max-time 2 "$APPIUM_URL/status" >/dev/null; then
  echo "Timed out waiting for Appium. Check $APPIUM_LOG." >&2
  exit 1
fi

export WDA_URL
echo "Controller is running. Press Ctrl+C to stop."
node worker.js
