from pathlib import Path

ROOT = Path(__file__).resolve().parent

# De trong khi dang ky thiet bi moi; dien sau khi admin cap quyen
DEVICE_ID = ""

# Referral link
TARGET_URL = "https://thanhtai.io/r/525ddbd53026"

# Trang lay device id moi
DEVICE_URL = "https://thanhtai.io/device"

# Chromium persistent profile (fingerprint + cookies)
PROFILE_DIR = ROOT / "browser-data"

# Browser defaults - giu on dinh de fingerprint khong doi
VIEWPORT = {"width": 1440, "height": 960}
LOCALE = "vi-VN"
TIMEZONE_ID = "Asia/Bangkok"
