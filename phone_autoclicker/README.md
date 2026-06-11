# Phone Auto Clicker

Local macOS web app for controlling an Android phone over USB with ADB.

## Setup

```bash
brew install android-platform-tools
adb devices -l
python3 phone_autoclicker/app.py
```

On the phone:

- Enable Developer options.
- Enable USB debugging.
- Plug the phone in with USB-C.
- Accept the RSA debugging prompt.

Open:

```text
http://127.0.0.1:8790
```

## Actions

- `tap`: tap at `x`, `y`.
- `swipe`: drag from `x1`, `y1` to `x2`, `y2`.
- `wait`: pause for `ms`.
- `key`: send an Android keyevent, for example `BACK`, `HOME`, `ENTER`.
- `text`: type text through `adb shell input text`.
- `deeplink`: open a URL/deep link through Android intent, for example `tiktok://...` or `https://...`.

Use Android Developer options `Pointer location` to read screen coordinates.

## Live Control

- `Snapshot`: pulls one screenshot with `adb exec-out screencap -p`.
- `Stream`: refreshes screenshots on an interval.
- Click the screenshot to tap the corresponding phone coordinate.
- `Back`, `Home`, and `Recents` send direct Android keyevents.
- `Open Deeplink` opens a URL/deep link immediately.
- `Download Logs` downloads `phone_autoclicker/events.log`.

## Config

The app stores config at:

```text
phone_autoclicker/config.json
```

Example:

```json
{
  "adb_path": "adb",
  "device_id": "",
  "dry_run": false,
  "startup_delay_ms": 500,
  "repeat": {
    "count": 1,
    "forever": false,
    "interval_ms": 800
  },
  "actions": [
    { "type": "tap", "x": 500, "y": 1200, "delay_ms": 250 },
    {
      "type": "swipe",
      "x1": 500,
      "y1": 1600,
      "x2": 500,
      "y2": 700,
      "duration_ms": 450,
      "delay_ms": 600
    },
    {
      "type": "deeplink",
      "url": "https://example.com",
      "delay_ms": 800
    }
  ]
}
```
