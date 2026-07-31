---
name: deploy-click-live
description: >-
  Deploy click-live (profile_playwright deeplink API + telegram_bot) to the VPS.
  Use when the user asks to deploy, đẩy lên server, migrate server, update
  DEEPLINK_OPEN_BASE_URL, or restart click-live services.
---

# Deploy Click Live

## Current server

| | |
|---|---|
| Host | `160.30.19.215` |
| User | `root` |
| Pass | ask user / `SERVER_PASS` env (do not commit) |

## Remote paths

| Component | Path |
|---|---|
| Deeplink API | `/root/click-live/profile_playwright` |
| Telegram bot | `/root/click-live/server/telegram_bot` |
| Bot data (preserve) | `/root/click-live/server/telegram_bot/data/` |
| Browser profile (preserve) | `/root/click-live/profile_playwright/browser-data/` |

## Ports & public URLs

| Service | Port | Public URL |
|---|---|---|
| Queue panel | `8787` | `http://160.30.19.215:8787/login` |
| Deeplink API | `8792` | `http://160.30.19.215:8792` |

Panel default: `admin` / `Admin123@`

## Critical base URLs

Deploy **must** set these in `server/telegram_bot/.env` on the server:

```bash
DEEPLINK_OPEN_BASE_URL=http://<SERVER_IP>:8792   # link mở TikTok trong tin broadcast (public IP)
DEEPLINK_API_BASE_URL=http://127.0.0.1:8792       # resolve nội bộ trên cùng máy
```

Open link format: `http://<SERVER_IP>:8792/open/live?room_id=...`

Never leave an old IP in `DEEPLINK_OPEN_BASE_URL`.

## Deploy order (code update)

From Mac repo root:

```bash
# 1) Deeplink API first
cd profile_playwright
SERVER_PASS='...' bash deploy_to_server.sh

# 2) Telegram bot (auto-upserts OPEN_BASE_URL from SERVER_HOST)
cd ../server/telegram_bot
SERVER_PASS='...' bash deploy_to_server.sh
```

Defaults in both scripts: `SERVER_HOST=160.30.19.215`, remote dirs as above.

Scripts **exclude** `data/` and `.env` from destructive sync of bot data; bot deploy uploads a patched `.env`.

## Systemd units

```bash
click-live-deeplink-api.service
click-live-queue.service
click-live-telegram-reader.service
click-live-broadcast.service
```

Verify:

```bash
systemctl is-active click-live-deeplink-api click-live-queue click-live-telegram-reader click-live-broadcast
curl -s http://127.0.0.1:8792/health
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/login
```

Open UFW if needed: `8787/tcp`, `8792/tcp`.

## New server / migrate checklist

1. Bootstrap: Python3, venv, `sshpass` on local, UFW allow 8787/8792.
2. Deploy `profile_playwright` (installs Chromium via Playwright).
3. Deploy `telegram_bot`.
4. Copy **data** carefully:
   - Prefer stop services on source → `sqlite3 .backup` of `data/chatbot.sqlite3` → copy backup.
   - Do **not** rsync a live SQLite + WAL (causes `database disk image is malformed`).
   - Also copy: `telegram_client.session*`, `message_filters.json`, `queue_ui_auth.secret`, `browser-data/`.
5. Confirm `.env` has `DEEPLINK_OPEN_BASE_URL=http://<NEW_IP>:8792`.
6. Restart all 4 units; seed bots if needed.
7. If Telethon session dies on new IP: `bash login_telethon_remote.sh`.

## SSH tip

Prefer password auth flags when key auth fails:

```bash
-o PreferredAuthentications=password -o PubkeyAuthentication=no
```

## Do not

- Commit `.env` or passwords into git.
- Point `DEEPLINK_OPEN_BASE_URL` at `127.0.0.1` (phones cannot open it).
- Wipe `data/` or `browser-data/` during routine deploys.

## Message reject filter

`data/message_filters.json` supports `reject` (checked before allow filters):

```json
{
  "filters": [],
  "reject": [
    {
      "name": "block_sun_comment",
      "enabled": true,
      "comment_contains": ["҉"]
    }
  ]
}
```

Requires `TELEGRAM_CLIENT_FILTER_ENABLED=true`. Panel `/filters` field **Chặn nếu dòng 💬 chứa**.
