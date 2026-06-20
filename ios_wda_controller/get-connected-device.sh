#!/usr/bin/env bash
# Gets the UDID of the first available physical iOS device
# Returns 0 and prints UDID if found, returns 1 if no device available

DEVICE_UDID=$(xcrun xctrace list devices 2>/dev/null | grep -E '^[^-]+ \([0-9]+\.[0-9.]+\) \([0-9A-F]{8}-[0-9A-F]{16}\)' | head -n 1 | sed -E 's/.*\(([0-9A-F]{8}-[0-9A-F]{16})\)/\1/')

if [[ -n "$DEVICE_UDID" ]]; then
  echo "$DEVICE_UDID"
  exit 0
else
  # Fallback to devicectl if xctrace fails to show status clearly
  DEVICE_UDID=$(xcrun devicectl list devices --json 2>/dev/null | jq -r '.result.devices[] | select(.connectionProperties.transportType == "usb" and .deviceProperties.isPaired == true) | .identifier' | head -n 1)
  if [[ -n "$DEVICE_UDID" && "$DEVICE_UDID" != "null" ]]; then
    echo "$DEVICE_UDID"
    exit 0
  fi
fi

exit 1
