# Phone Monitor App

Native Android monitor for logging and executing phone actions without relying on ADB after install.

## What it does

- Logs Accessibility events to local JSONL (`phone-monitor.jsonl`).
- Logs manual/actions: `tap`, `swipe`, `deeplink`, overlay marks.
- Performs gestures through `AccessibilityService.dispatchGesture`:
  - tap by coordinate
  - swipe/scroll by coordinate
  - open deeplink with Android `ACTION_VIEW`
- Shows a small movable overlay panel with quick actions.
- Runs a small LAN HTTP server on port `8791`:
  - `GET /logs`
  - `POST /actions/tap` with form fields `x`, `y`
  - `POST /actions/swipe` with `x1`, `y1`, `x2`, `y2`, `duration_ms`
  - `POST /actions/deeplink` with `url`

The queue UI also has a `Phone` page at `/phone-monitor` to call these endpoints by phone IP.

## Build

From this folder:

```bash
gradle assembleDebug
```

If you prefer Android Studio: open `phone_monitor_app/` and run `app`.

APK output:

```text
app/build/outputs/apk/debug/app-debug.apk
```

## Install and enable

1. Install the debug APK on the phone.
2. Open **Phone Monitor**.
3. Tap **Open Accessibility Settings** and enable **Phone Monitor**.
4. Tap **Allow Overlay Permission** and allow drawing over other apps.
5. Re-open the app. It should show:

```text
Accessibility: ON
Overlay: ON
HTTP: http://<phone-ip>:8791
```

## Use from Queue UI

1. Start the queue UI as before: `http://127.0.0.1:8787`.
2. Click **Phone**.
3. Enter the phone URL shown in the app, for example:

```text
http://192.168.1.23:8791
```

4. Use Tap / Swipe / Open Deeplink / Load Logs.

Mac and phone must be on the same LAN/Wi-Fi. Android may block requests if VPN/firewall/private DNS interferes.

## Notes

- Accessibility can see UI events and perform gestures, but Android does not expose raw touch coordinates for every human tap in all apps. Coordinates are logged for actions performed through this app/HTTP/overlay.
- For exact coordinate discovery, enable Android Developer Options → **Pointer location**.
- This is intended for your own devices/workflows. Some target apps may restrict automation in their terms.
