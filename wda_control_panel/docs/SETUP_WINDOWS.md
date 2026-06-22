# Setup PC Windows kéo 20 iPhone bằng 1 app

Mục tiêu: client chỉ cài **WDA Control Panel Setup.exe**, cắm iPhone, làm
wizard trong app. Không cần tự cài 3uTools, không cần tự tải go-ios, không cần
copy IPA tay.

## Bạn chuẩn bị trước khi build installer

Trên Mac:

```bash
cd wda_control_panel
TEAM_ID=ABCDE12345 ./scripts/build-ipa.sh
cp dist/wda-ipa/WebDriverAgentRunner.ipa resources/ipa/WebDriverAgentRunner.ipa
```

Sau đó build Windows installer:

```bash
npm install
npm run build:win
```

Lệnh build sẽ:

1. Chạy `scripts/fetch-go-ios.js` để tải `go-ios.exe` và `wintun.dll` vào `resources/bin/windows/`.
2. Copy `resources/bin/**` và `resources/ipa/*.ipa` vào app bằng
   `electron-builder.extraResources`.
3. Xuất installer ở `dist/`.

## Client Windows làm gì

1. Cài `WDA Control Panel Setup.exe`.
2. Mở app → tab **Setup**.
3. App tự check:
   - Apple Mobile Device Service,
   - bundled go-ios,
   - bundled `WebDriverAgentRunner.ipa`.
4. Nếu thiếu Apple driver, bấm **Tải Apple driver**. App mở link tải iTunes
   chính thức từ apple.com. Cài xong restart app.
5. Cắm 20 iPhone vào powered USB hub.
6. Bấm **Scan USB**.
7. Bấm **Auto assign tất cả** để gán UDID vào `iphone-01..iphone-20`.
8. Bấm **Install IPA tất cả** để app dùng go-ios cài WDA IPA lên từng máy.
9. Trên từng iPhone:
   - Settings → General → VPN & Device Management → Trust developer cert.
   - Settings → Privacy & Security → Developer Mode → ON → restart.
10. Sang tab **Fleet** → **Start all**.

## Daily run

Sau setup lần đầu, mỗi sáng chỉ cần:

```text
Cắm hub USB → mở WDA Control Panel → Start all
```

Nếu một máy lỗi:

```text
Stop slot đó → Start lại
Nếu vẫn lỗi: rút/cắm lại cáp → Scan USB → Start lại
```

## Những thứ vẫn phải làm ngoài app

| Thứ | Lý do |
|---|---|
| Build/ký WDA IPA trên Mac mỗi năm | Apple bắt buộc Xcode/cert để build XCUITest bundle |
| Apple Mobile Device driver | Không nên redistribute trực tiếp do EULA; app chỉ detect và mở link tải chính thức |
| Trust cert + Developer Mode trên iPhone | iOS yêu cầu thao tác vật lý trên thiết bị |

## Khi nào rebuild installer

- Bạn build lại `WebDriverAgentRunner.ipa` vì cert/profile hết hạn.
- Bạn muốn update go-ios version (sửa `GO_IOS_VERSION` trong `scripts/fetch-go-ios.js`).
- Bạn thay code UI/launcher.

## Debug nhanh

| Triệu chứng | Cách xử lý |
|---|---|
| Setup báo thiếu driver | Cài iTunes từ apple.com, restart Windows nếu cần |
| Scan USB không thấy iPhone | Unlock iPhone, Trust This Computer, đổi cáp/hub, restart Apple Mobile Device Service |
| Install IPA lỗi profile | UDID chưa đăng ký trong Apple Developer Portal hoặc profile hết hạn |
| Start all timeout `/status` | Developer Mode chưa bật, iPhone khoá màn hình, WDA IPA chưa trust |
