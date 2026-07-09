# profile_playwright

Playwright persistent profile for [thanhtai.io](https://thanhtai.io) automation.

Device ID and referral link are configured in `config.py`.

## Setup

Requires **Python 3.11**.

```bash
cd profile_playwright
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Open referral link (GUI)

```bash
source .venv/bin/activate
python open_referral.py
```

Script se xoa cookie cu (`device_946466bc...`) va thay bang:

```
device_id=device_4a158d0a-1f61-447f-8697-61eb66db7814
```

Neu Network tab van thay cookie cu: dong het Chromium (Cmd+Q), chay:

```bash
python persist_device_cookie.py
python open_referral.py
```

## Check device / referral status (headless)

```bash
python run_automation.py
```

## Inspect device page

```bash
python setup_profile.py
```

## How device auth works

- thanhtai.io stores identity in cookie `device_id` on domain `thanhtai.io`
- Fingerprint data from `i.junb.io.vn` is kept in Chromium profile (`browser-data/`)
- Scripts inject the configured `device_id` before each session
- If referral page still shows "Thiết bị chưa được cấp quyền", contact BOT owner to whitelist this device ID for the referral link

Do not commit `browser-data/`.

## Live deeplink API

Chuyen link **junb.io.vn** hoac **thanhtai.io** thanh TikTok live deeplink (khong can browser).

Ho tro:
- `https://i.junb.io.vn/i/?b7YVmORSncRD4`
- `https://thanhtai.io/r/b7YVmORSncRD4`

```bash
source .venv/bin/activate
python api.py
```

Mac dinh chay tai `http://127.0.0.1:8792`.

**GET**

```bash
curl "http://127.0.0.1:8792/api/deeplink?url=https://i.junb.io.vn/i/?b7YVmORSncRD4"
curl "http://127.0.0.1:8792/api/deeplink?url=https://thanhtai.io/r/b7YVmORSncRD4"
```

**POST**

```bash
curl -X POST http://127.0.0.1:8792/api/deeplink \
  -H "Content-Type: application/json" \
  -d '{"url":"https://thanhtai.io/r/b7YVmORSncRD4"}'
```

**Response**

```json
{
  "ok": true,
  "url": "https://thanhtai.io/r/b7YVmORSncRD4",
  "code": "b7YVmORSncRD4",
  "deeplink": "snssdk1180://live?room_id=7660479963724434197"
}
```

CLI:

```bash
python decode_junb.py "https://thanhtai.io/r/b7YVmORSncRD4"
```
