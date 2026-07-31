# Tunnel quốc tế (Cloudflare) — điện thoại nước ngoài → VPS

## Vấn đề

- **FRP** = VPS gọi **về** phone ở nhà (phone bật VPN, nằm LAN).
- **Cloudflare Tunnel** = phone **ở nước ngoài** gọi **ra** VPS qua mạng Cloudflare (IP VPS bị chặn vẫn dùng được).

Điện thoại abroad thường **không mở được** `http://160.30.19.215` (IP/datacenter bị chặn). Tunnel cho URL dạng:

`https://xxxx.trycloudflare.com`

## Cài trên VPS

```bash
bash /root/click-live/server/tunnel/setup-cloudflared.sh
cat /root/click-live/tunnel/public.url
```

Service: `cloudflared-quick.service` → proxy tới nginx `:80` (queue UI + deeplink API).

Tự cập nhật `DEEPLINK_OPEN_BASE_URL` và `PUBLIC_QUEUE_BASE_URL` trong telegram_bot `.env`.

## Cấu hình phone (nước ngoài)

1. **Phone Monitor APK** → Queue URL = URL trong `public.url` (không có `/login`).
2. Link mở TikTok trong tin Telegram dùng `DEEPLINK_OPEN_BASE_URL` (HTTPS tunnel).
3. **Không cần VPN** để reach queue server (chỉ TikTok live vẫn VPN nếu cần).

## FRP vẫn cần khi nào?

Chỉ khi bạn bấm **Mở link** trên Queue UI và muốn **VPS push deeplink** tới phone qua `PHONE_MONITOR_BASE_URL` (phone ở nhà + PC chạy frpc).

Phone abroad chỉ cần **poll queue** qua tunnel URL — không cần FRP cho chiều đó.

## Lưu ý Quick Tunnel

- URL `*.trycloudflare.com` **đổi mỗi lần restart** service (free, không đăng ký).
- Muốn domain cố định: tạo Cloudflare account + Named Tunnel (Zero Trust free) — liên hệ để setup bước 2.

## Kiểm tra

```bash
systemctl status cloudflared-quick
curl -s "$(cat /root/click-live/tunnel/public.url)/health"
```
