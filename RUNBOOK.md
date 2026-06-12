# Hướng dẫn chạy Click Live

Tài liệu nhanh để chạy Queue UI cùng Telegram Web browser reader và cài app monitor vào điện thoại Android.

## 0. Mục đích từng app và luồng gửi/pull link

Project này có 4 phần chính:

### 0.1. Telegram Web Reader

Folder/script:

```text
server/telegram_bot/telegram_web_reader.py
```

Mục đích:

- Mở Telegram Web bằng Playwright Chromium.
- Dùng profile đã đăng nhập ở `server/telegram_bot/data/telegram_web_profile/`.
- Đọc tin nhắn trong Telegram Web.
- Parse các tin nhắn dạng BOX/rương.
- Chạy filter nếu bật filter.
- Đẩy message đạt điều kiện vào queue.

Nói ngắn gọn: **Telegram Web Reader là app kéo tin từ Telegram vào queue**.

Luồng:

```text
Telegram Web
  -> telegram_web_reader.py đọc tin nhắn
  -> message_filter.py lọc BOX / rate / views / note / country / badge
  -> DB queue
```

### 0.2. Queue UI

Folder/script:

```text
server/telegram_bot/queue_ui.py
```

Mục đích:

- Hiển thị danh sách message/link đang nằm trong queue.
- Cho cấu hình filter ở `/filters`.
- Cho kết nối điện thoại ở `/phone-monitor`.
- Cho chọn link pending trong queue rồi gửi link đó sang điện thoại.

Nói ngắn gọn: **Queue UI là dashboard để xem queue, lọc queue và gửi link sang điện thoại**.

Các trang:

```text
/              xem queue
/filters       cấu hình filter
/phone-monitor gửi link/cài app/điều khiển điện thoại
```

### 0.3. Phone Monitor App Android

Folder:

```text
phone_monitor_app/
```

Mục đích:

- App cài trên điện thoại Android.
- Mở một HTTP server trong LAN trên port `8791`.
- Nhận lệnh từ Queue UI qua Wi-Fi/LAN.
- Thực hiện các hành động trên điện thoại:
  - mở deeplink
  - tap
  - swipe
  - ghi logs

Nói ngắn gọn: **Phone Monitor App là app nhận link từ Queue UI và mở link trên điện thoại**.

Khi mở app trên điện thoại, app sẽ hiện URL dạng:

```text
http://<phone-ip>:8791
```

Ví dụ:

```text
http://192.168.1.23:8791
```

URL này cần nhập vào trang Queue UI `/phone-monitor` ở ô **Phone base URL**.

Luồng gửi link qua app Android:

```text
Queue UI /phone-monitor
  -> POST http://<phone-ip>:8791/actions/deeplink
  -> Phone Monitor App nhận url
  -> Android ACTION_VIEW mở deeplink trên điện thoại
```

### 0.4. Phone Auto Clicker

Folder/script:

```text
phone_autoclicker/app.py
```

Mục đích:

- Web app local điều khiển điện thoại qua ADB/USB.
- Có thể mở deeplink, tap, swipe, back/home/recents.
- Có thể chụp màn hình bằng ADB.
- Sau khi mở deeplink có thể capture màn hình và lưu vào `phone_autoclicker/captures/` để lấy dữ liệu ML nhận diện hình ảnh.

Nói ngắn gọn: **Phone Auto Clicker là app điều khiển điện thoại qua USB/ADB và thu thập screenshot**.

### 0.5. Pull link và gửi link hoạt động như thế nào?

Có 2 hướng chính:

#### Hướng A: Telegram -> Queue -> Phone

Đây là luồng chính:

```text
1. telegram_web_reader.py đọc tin Telegram
2. message_filter.py lọc tin theo BOX/rate/views/note/country/badge
3. Tin đạt điều kiện được enqueue vào DB
4. Queue UI hiển thị tin pending ở /
5. Người dùng chọn/open pending link
6. Queue UI gửi link sang điện thoại qua:
   - Phone Monitor App HTTP server, hoặc
   - ADB trực tiếp
7. Điện thoại mở deeplink
```

#### Hướng B: Nhập link thủ công -> Phone

Dùng khi muốn test nhanh một deeplink:

```text
1. Mở Queue UI /phone-monitor
2. Nhập deeplink vào ô Deeplink
3. Chọn Open Deeplink hoặc Open deeplink via ADB
4. Điện thoại mở link
```

#### Gửi qua Phone Monitor App hay ADB?

- Dùng **Phone Monitor App** khi điện thoại và Mac cùng Wi-Fi/LAN, không muốn phụ thuộc USB sau khi đã cài app.
- Dùng **ADB trực tiếp** khi điện thoại đang cắm Type-C, cần cài APK hoặc mở deeplink nhanh qua USB.


## 1. Chuẩn bị môi trường

Yêu cầu:

- Python 3.8+
- ADB / Android platform tools
- Playwright Chromium
- Điện thoại Android bật **Developer options** và **USB debugging**

Cài dependency lần đầu:

```bash
cd server/telegram_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium
```

Tạo file cấu hình nếu chưa có:

```bash
cp .env.example .env
```

Các biến quan trọng trong `.env`:

```env
TELEGRAM_WEB_URL=https://web.telegram.org/k/
TELEGRAM_WEB_PROFILE_DIR=data/telegram_web_profile
TELEGRAM_WEB_HEADLESS=false
TELEGRAM_WEB_ENQUEUE=true
QUEUE_UI_HOST=127.0.0.1
QUEUE_UI_PORT=8787
```

> Lưu ý: `TELEGRAM_WEB_PROFILE_DIR` là profile đăng nhập Telegram Web. Không nên commit/push thư mục này lên git vì có thể chứa session/cookie.

## 2. Chạy Queue UI

Mở terminal 1:

```bash
cd server/telegram_bot
source .venv/bin/activate
python3 queue_ui.py
```

Mặc định mở tại:

```text
http://127.0.0.1:8787
```

Các trang chính:

- Queue: `http://127.0.0.1:8787/`
- Filters: `http://127.0.0.1:8787/filters`
- Phone Monitor: `http://127.0.0.1:8787/phone-monitor`

Nếu port `8787` bị trùng, chạy port khác:

```bash
cd server/telegram_bot
source .venv/bin/activate
QUEUE_UI_PORT=8788 python3 queue_ui.py
```

Mở:

```text
http://127.0.0.1:8788
```

## 3. Chạy Telegram Web browser reader

Mở terminal 2:

```bash
cd server/telegram_bot
source .venv/bin/activate
python3 telegram_web_reader.py
```

Lần đầu chạy:

1. Chromium sẽ mở Telegram Web.
2. Đăng nhập Telegram.
3. Profile đăng nhập được lưu ở `server/telegram_bot/data/telegram_web_profile/`.
4. Các lần sau reader dùng lại profile này, không cần đăng nhập lại nếu session còn sống.

Reader sẽ đọc Telegram Web và enqueue message vào queue nếu cấu hình `TELEGRAM_WEB_ENQUEUE=true`.

## 4. Chạy Queue UI + browser reader cùng lúc

Cách chạy khuyến nghị là mở 2 terminal:

Terminal 1 - Queue UI:

```bash
cd server/telegram_bot
source .venv/bin/activate
python3 queue_ui.py
```

Terminal 2 - Telegram Web reader:

```bash
cd server/telegram_bot
source .venv/bin/activate
python3 telegram_web_reader.py
```

Kiểm tra process đang chạy:

```bash
ps aux | grep -E 'queue_ui.py|telegram_web_reader.py' | grep -v grep
```

## 5. Build app monitor Android

App Android nằm ở:

```text
phone_monitor_app/
```

Build APK debug:

```bash
cd phone_monitor_app
./gradlew assembleDebug
```

APK sau khi build:

```text
phone_monitor_app/app/build/outputs/apk/debug/app-debug.apk
```

Nếu máy chưa có `gradlew`, có thể dùng Gradle đã cài sẵn:

```bash
cd phone_monitor_app
gradle assembleDebug
```

## 6. Cài app vào điện thoại bằng ADB

Cắm điện thoại bằng USB Type-C, bật USB debugging, rồi kiểm tra:

```bash
adb devices -l
```

Cài APK:

```bash
adb install -r phone_monitor_app/app/build/outputs/apk/debug/app-debug.apk
```

Nếu có nhiều thiết bị, chỉ định serial:

```bash
adb -s <DEVICE_SERIAL> install -r phone_monitor_app/app/build/outputs/apk/debug/app-debug.apk
```

## 7. Cài app bằng Queue UI

Có thể cài trực tiếp từ web Queue UI:

1. Chạy Queue UI.
2. Mở `http://127.0.0.1:8787/phone-monitor`.
3. Cắm điện thoại bằng USB Type-C.
4. Bấm **Refresh devices**.
5. Kiểm tra APK path là:

```text
phone_monitor_app/app/build/outputs/apk/debug/app-debug.apk
```

6. Bấm **Install APK via Type-C**.

## 8. Mở deeplink từ Queue UI sang điện thoại

Tại trang Phone Monitor:

```text
http://127.0.0.1:8787/phone-monitor
```

Có 2 cách:

### Qua app monitor trên điện thoại

1. Mở app monitor trên điện thoại.
2. Bật quyền Accessibility/Overlay nếu app yêu cầu.
3. Nhập Phone base URL trong Queue UI, ví dụ:

```text
http://192.168.1.23:8791
```

4. Bấm **Save URL**.
5. Bấm **Open pending queue link** hoặc nhập deeplink rồi bấm **Open Deeplink**.

### Qua ADB trực tiếp

1. Cắm USB Type-C.
2. Bấm **Refresh devices**.
3. Nhập deeplink.
4. Bấm **Open deeplink via ADB**.

Có thể cấu hình điểm click sau khi mở link bằng:

- `click x`
- `click y`
- `manual delay ms`

Sau đó bấm **Save click point**.

## 9. Filter queue

Mở:

```text
http://127.0.0.1:8787/filters
```

Ý nghĩa một số field:

- **BOX Min** nhập `100/25`: match BOX có value 1 `>= 100` và value 2 `>= 25`.
- **Min Rate**: match rate `>=` số nhập.
- **Min Views**: match views `>=` số nhập.
- **Note Contains**: nhập nhiều keyword, ví dụ `"Rương treo", "ABC", "CDE"`; so sánh không phân biệt hoa/thường.
- **Countries**: không chọn gì nghĩa là tất cả quốc gia.
- **Badges**: nhập badge cần có, ví dụ `💎,🏅`.

Mẫu tin nhắn:

```text
🎁 BOX: 100/25 💎 🏅 🇰🇷
📈 Rate : 5.5
👀 12
📝 Rương treo ít view
```

## 10. Dừng app

Dừng từng terminal bằng:

```text
Ctrl + C
```

Hoặc tìm process:

```bash
ps aux | grep -E 'queue_ui.py|telegram_web_reader.py' | grep -v grep
```

Rồi kill PID cần dừng:

```bash
kill <PID>
```
