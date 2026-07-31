# FRP tunnel — VPS ↔ Phone (VPN-safe)

Phone bật VPN → VPS **không gọi thẳng** được phone. PC nhà chạy **frpc** (outbound → VPS), VPS forward về phone qua WiFi LAN.

## Domain free (không đăng ký)

| Dịch vụ | URL |
|---------|-----|
| **sslip.io** | `http://160-30-19-215.sslip.io:8787/login` (queue UI) |
| IP gốc | `http://160.30.19.215:8787/login` |

`160-30-19-215.sslip.io` trỏ tự động tới `160.30.19.215` — không cần tạo tài khoản.

## VPS — cài frps (đã chạy script)

```bash
bash /root/click-live/server/frp/setup-frps.sh
cat /root/click-live/frp/frps.env   # FRP_TOKEN
```

telegram_bot `.env`:

```env
PHONE_MONITOR_BASE_URL=http://127.0.0.1:8791
```

## Windows PC nhà — frpc

1. Phone Monitor APK → IP phone `192.168.x.x:8791`
2. Copy `frpc-windows.example.ini` → `frpc.ini`, điền `auth.token` + `localIP`
3. Chạy `frpc.exe -c frpc.ini` (Task Scheduler để auto-start)

## Kiểm tra

Trên VPS (sau khi frpc chạy):

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8791/
```

Queue UI → **Mở link** → phone mở TikTok deeplink.
