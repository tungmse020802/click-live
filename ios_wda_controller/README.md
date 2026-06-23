# iOS WDA Controller

Controller chạy trên MacBook để điều khiển một iPhone thật:

1. Giữ WebDriverAgent chạy bằng `xcodebuild`.
2. Kết nối Appium vào WDA đang chạy.
3. Poll job từ queue server.
4. Mở deeplink trên iPhone.
5. Đợi TikTok load, chụp màn hình và upload về server.
6. Chỉ nhận diện và tap vào rương màu vàng/đỏ.
7. Giữ popup mở và chờ deadline lấy từ `TIME` trong message.
8. Gửi lịch tap cho WDA để iPhone tự đợi và nhấn nút `Mở` đúng deadline.
9. Đợi 2.5 giây rồi chụp ảnh kết quả và upload về server.

## Chuẩn bị iPhone

- Cắm cáp USB và chọn Trust.
- Bật Developer Mode.
- Giữ iPhone mở khóa.
- Đặt `Settings > Display & Brightness > Auto-Lock > Never`.

WDA đã được ký cho thiết bị hiện tại. Khi đổi iPhone hoặc certificate, cần build
và ký WDA lại trong Xcode.

## Build và cài WDA lần đầu

Lỗi `Failed Registering Bundle Identifier` xảy ra khi Xcode dùng bundle ID mặc
định của Facebook. Cấu hình team và bundle ID riêng trong `config.env`:

```env
DEVICE_UDID=00008030-000805902E3B802E
DEVELOPMENT_TEAM=827H4SVZSB
WDA_BUNDLE_ID=com.tungld.clicklive.WebDriverAgentRunner
```

Sau đó cắm và mở khóa iPhone, chọn Trust, rồi chạy:

```bash
cd ios_wda_controller
npm install
npm run wda:build
```

Xcode tự tạo app identifier thực tế là:

```text
com.tungld.clicklive.WebDriverAgentRunner.xctrunner
```

Kiểm tra profile đang ký và ngày hết hạn:

```bash
npm run wda:info
```

Nếu iPhone hỏi xác nhận developer, vào `Settings > General > VPN & Device
Management`, trust tài khoản developer rồi chạy lại.

### Tài khoản miễn phí và tài khoản trả phí

- Personal Team miễn phí chỉ cấp provisioning profile 7 ngày. Hết hạn phải chạy
  lại `npm run wda:build`.
- Sau khi mua Apple Developer Program, đăng nhập lại Xcode, lấy Team ID của paid
  team và cập nhật `DEVELOPMENT_TEAM` trong `config.env`.
- Chạy `npm run wda:build` một lần để tạo profile mới, sau đó dùng `npm start`
  hằng ngày. Không cần build lại khi profile vẫn còn hạn.
- WDA là XCTest runner, không phải app iPhone độc lập. App có thể nằm sẵn trên
  máy nhưng mỗi phiên vẫn cần Mac chạy `npm start` để launch WDA và Appium.

## Xuất và cài IPA

Build và ký WDA, sau đó đóng gói thành IPA:

```bash
npm run wda:build
npm run wda:ipa
```

File được tạo tại:

```text
ios_wda_controller/dist/WebDriverAgentRunner.ipa
```

Cài IPA lên iPhone đang cấu hình trong `DEVICE_UDID`:

```bash
npm run wda:install
```

Hoặc cài một file IPA cụ thể:

```bash
./install-wda-ipa.sh /path/to/WebDriverAgentRunner.ipa
```

IPA development chỉ cài được lên iPhone có UDID nằm trong provisioning profile.
Khi dùng tài khoản Developer trả phí, đăng ký các iPhone trong Apple Developer,
build lại IPA với profile chứa các thiết bị đó, rồi có thể dùng cùng IPA để cài
lên từng máy.

Khi cần đổi sang bundle id mới, không cần sửa tay `config.env` trước. Chạy:

```bash
cd ios_wda_controller
./build-wda-ipa-with-bundle.sh com.tungld.clicklive.WebDriverAgentRunner 827H4SVZSB
```

Script sẽ build lại app với bundle id mới, tạo IPA trong `ios_wda_controller/dist/`
và mặc định copy luôn sang:

```text
wda_control_panel/resources/ipa/WebDriverAgentRunner.ipa
```

WDA cài từ IPA vẫn là XCTest runner. Nó không hoạt động bằng cách bấm icon như
app thường; Mac/Appium phải launch runner khi bắt đầu phiên điều khiển.

## Chạy

```bash
cd ios_wda_controller
cp config.env.example config.env
npm install
npm start
```

Nhấn `Ctrl+C` để dừng worker, Appium và WDA.

Log được ghi tại:

```text
ios_wda_controller/wda.log
ios_wda_controller/appium.log
```

Screenshot cục bộ nằm trong `ios_wda_controller/captures/`; bản upload nằm ở
`http://103.38.237.7:8787/api/phone/screenshots/<filename>`.

## Tap hộp quà

Worker dùng OpenCV trên Mac để tìm rương vàng/đỏ trong screenshot. Túi quà tím
không phải mục tiêu và luôn bị bỏ qua. Candidate chỉ hợp lệ khi vừa khớp template
rương vàng, vừa có tối thiểu tỷ lệ màu đỏ/hồng đã cấu hình.

Cấu hình trong `config.env`:

```env
TREASURE_TAP_ENABLED=true
TREASURE_TEMPLATE_PATH=templates/treasure_yellow.png
TREASURE_THRESHOLD=0.54
TREASURE_MIN_RED_RATIO=0.06
TREASURE_ROI=0,280,360,240
TREASURE_STABILIZE_DELAY_MS=2000
TREASURE_SCAN_SECONDS=7
TREASURE_SCAN_INTERVAL_MS=500
TREASURE_TAP_DELAY_SECONDS=0
TREASURE_PRE_TAP_DELAY_SECONDS=0
```

Luồng mỗi job:

```text
queue job
-> mở deeplink TikTok LIVE
-> đợi 4 giây để TikTok/rương load
-> thử toàn bộ template và chọn candidate hợp lệ có điểm cao nhất
-> dùng viewport đã cache và tap tâm candidate ngay lập tức
-> lấy mốc HH:mm:ss sau dấu "-" trong TIME
-> fallback sang click_after_ms nếu message không có đồng hồ tuyệt đối
-> vào bộ hẹn giờ trước mọi upload/report
-> gửi lịch tap cho WDA trước deadline 2.5 giây
-> WDA tự đợi trên iPhone rồi tap, không polling screenshot
-> sau khi tap Mở mới upload chính ảnh scan đã dùng để nhận diện
-> đợi 2.5 giây, screenshot after_open_button_tap và upload
```

Luồng bình thường chỉ capture hai lần: một ảnh để nhận diện rương và một ảnh xác
nhận sau tap. WDA vẫn phải lấy ảnh full màn hình để giữ đúng hệ tọa độ, nhưng
worker chỉ upload 1/4 góc trên-trái của ảnh scan. Nếu lần scan đầu chưa thấy
rương, worker mới capture thêm mỗi 500ms theo `TREASURE_SCAN_INTERVAL_MS`
trong tối đa 7 giây.

Nếu tọa độ lệch trên máy khác, mở screenshot trước tap để đo lại vị trí hộp quà rồi sửa `TREASURE_TAP_X/Y`.

Nút `Mở` nằm gần cuối popup và được xác định theo tỷ lệ viewport, không dùng tọa
độ pixel cố định:

```env
OPEN_BUTTON_X_RATIO=0.50
OPEN_BUTTON_Y_RATIO=0.93
OPEN_TAP_REQUEST_LEAD_MS=2500
OPEN_TAP_TRANSPORT_COMPENSATION_MS=200
OPEN_RESULT_WAIT_SECONDS=2.5
```

Worker ưu tiên deadline tuyệt đối trong chuỗi như `01:05s - 01:40:04`. Cách này
không bị trễ do thời gian mở deeplink, load TikTok hoặc nhận diện ảnh. Log sau tap
ghi `request offset`, `completed offset` và `WDA duration`; dùng các số này để
chỉnh `OPEN_TAP_TRANSPORT_COMPENSATION_MS` riêng cho từng máy. TikTok không
expose nút `Mở` qua accessibility nên WDA nhận tọa độ và tự hẹn giờ tap ngay
trên iPhone, không cần streaming hoặc app phụ trên điện thoại.
