# FRP tunnel — VPS ↔ Phone (VPN-safe)

> **Điện thoại nước ngoài không vào được IP VPS?** Dùng **Cloudflare Tunnel** (`server/tunnel/`) — không phải FRP.  
> FRP chỉ để VPS **gọi ngược** về phone ở nhà (LAN + VPN).

Phone bật VPN → VPS **không gọi thẳng** được phone. PC nhà chạy **frpc** (outbound → VPS), VPS forward về phone qua WiFi LAN.

## Truy cập từ nước ngoài (port 80)

Nhiều mạng nước ngoài **chặn port lẻ** (`8787`, `8792`). Dùng **nginx :80** (đã cài trên VPS):

| Dịch vụ | URL (khuyên dùng) |
|---------|-------------------|
| **Queue UI** | http://160-30-19-215.sslip.io/login |
| **Deeplink** | http://160-30-19-215.sslip.io/open/live?room_id=... |
| **Health** | http://160-30-19-215.sslip.io/health |

**DNS không resolve (sslip.io)?** Dùng IP trực tiếp (vẫn port 80):

- http://160.30.19.215/login
- Hoặc DNS dự phòng: http://160.30.19.215.nip.io/login

Cài/cập nhật proxy: `bash server/nginx/setup-click-live-proxy.sh`

## Domain free (không đăng ký)

| Dịch vụ | URL |
|---------|-----|
| **sslip.io** | `http://160-30-19-215.sslip.io/login` |
| **nip.io** | `http://160.30.19.215.nip.io/login` |
| IP gốc | `http://160.30.19.215/login` |

`:8787` / `:8792` vẫn chạy nhưng **có thể bị chặn** ở một số quốc gia — ưu tiên **không ghi port** (mặc định 80).

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
