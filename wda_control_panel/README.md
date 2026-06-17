# WDA Control Panel

All-in-one Windows desktop app (Electron) để PC kéo dàn 20-40 iPhone qua
**WebDriverAgent**. Mac chỉ dùng để build/ký `WebDriverAgentRunner.ipa` mỗi
năm một lần; runtime chính nằm hoàn toàn trên PC Windows.

## Kiến trúc

```
Mac (1 lần / năm)                         PC Windows (hằng ngày)
+--------------------+                    +--------------------------------+
| Xcode + Apple cert |                    | WDA Control Panel Setup.exe     |
| build-ipa.sh       | --signed IPA-----> |  - bundled go-ios.exe           |
+--------------------+                    |  - bundled WDA IPA              |
                                            |  - Setup wizard                 |
                                            |  - Fleet UI 20 iPhone           |
                                            +---------------+----------------+
                                                            |
                                                            v
                                                   Powered USB hub
                                                            |
                                                            v
                                                       20 × iPhone
```

Không cần client cài 3uTools, không cần tự tải go-ios, không cần copy IPA tay.
Bạn build IPA trên Mac, đặt vào `resources/ipa/WebDriverAgentRunner.ipa`, rồi
build `WDA Control Panel Setup.exe`. File `.exe` đó đã chứa go-ios + IPA.

## Flow cho bạn

### 1. Build IPA trên Mac

```bash
cd wda_control_panel
TEAM_ID=ABCDE12345 ./scripts/build-ipa.sh
cp dist/wda-ipa/WebDriverAgentRunner.ipa resources/ipa/WebDriverAgentRunner.ipa
```

### 2. Build app Windows

```bash
cd wda_control_panel
npm install
npm run build:win
```

`npm run build:win` sẽ tự chạy `npm run fetch:go-ios`, tải `go-ios.exe` vào
`resources/bin/windows/`, rồi đóng gói tất cả vào installer.

Output nằm trong:

```text
wda_control_panel/dist/
```

Gửi client file `WDA Control Panel Setup*.exe`.

## Flow cho client PC Windows

1. Cài `WDA Control Panel Setup.exe`.
2. Mở app → tab **Setup**.
3. Nếu driver Apple thiếu, bấm **Tải Apple driver** để tải iTunes driver từ
   apple.com. Đây là thành phần duy nhất không nên redistribute trực tiếp vì
   EULA của Apple.
4. Cắm 20 iPhone qua powered USB hub.
5. Bấm **Scan USB** → **Auto assign tất cả**.
6. Bấm **Install IPA tất cả** để app tự cài WDA lên từng iPhone.
7. Trên iPhone: Trust certificate + bật Developer Mode.
8. Qua tab **Fleet** → **Start all**.

## Source layout

```
wda_control_panel/
├── package.json
├── electron-builder.json
├── scripts/
│   ├── build-ipa.sh              # Mac: build/ký WDA IPA
│   └── fetch-go-ios.js           # Build: tải go-ios binaries
├── resources/
│   ├── bin/                      # go-ios.exe được fetch vào đây
│   └── ipa/WebDriverAgentRunner.ipa
├── docs/
│   ├── BUILD_IPA.md
│   └── SETUP_WINDOWS.md
└── src/
    ├── main.js                   # Electron main + IPC
    ├── preload.js                # contextBridge
    ├── setup-helper.js           # driver check, go-ios check, IPA install
    ├── paths.js                  # resolve bundled resources
    ├── fleet-agent.js            # scan/assign/install/start/stop/open/health
    ├── wda-launcher.js           # per-device runwda + forward
    ├── device-store.js           # 20 slot iphone-01..iphone-20
    ├── index.html
    ├── styles.css
    └── renderer.js
```

## Capabilities hiện có

- Queue:
  - đọc message trực tiếp từ `QUEUE_SERVER_URL/api/queue`,
  - lọc theo status và limit,
  - tự refresh mỗi 2 giây,
  - hiển thị BOX, TIME, message, nguồn và link,
  - chọn iPhone đang gán để mở link,
  - mark job done thủ công.
- Automation worker:
  - nút Start khởi động WDA rồi tự bật worker cho từng iPhone,
  - worker long-poll message queue, mở deeplink TikTok và xử lý job liên tục,
  - chỉ nhận live có mốc `TIME` còn cách hiện tại trong khoảng cấu hình
    **Live Time window**; mặc định từ 10 đến 25 giây,
  - dùng lại cấu hình nhận diện, template và Python/OpenCV từ
    `ios_wda_controller/config.env`,
  - nhận diện rương, tap rương, hẹn giờ tap nút Mở và upload screenshot như
    worker đã triển khai,
  - nút Stop dừng cả worker lẫn WDA.
- Setup wizard:
  - check Apple Mobile Device Service,
  - check bundled go-ios,
  - check bundled WDA IPA,
  - scan USB,
  - auto-assign UDID vào slot,
  - install IPA all / per-device,
  - check WDA installed.
- Fleet runtime:
  - start/stop per-device,
  - start all / stop all,
  - mỗi iPhone map ra `http://127.0.0.1:8100..8119`,
  - health check WDA `/status`,
  - open deeplink trên selected devices.

## Giới hạn

- WDA vẫn phải được build/ký bằng Mac/Xcode một lần mỗi năm hoặc khi đổi cert.
- Apple driver vẫn phải cài từ Apple. App chỉ detect và mở link tải chính thức.
- Worker tap/screenshot job chính vẫn đang ở [ios_wda_controller/](../ios_wda_controller). Panel hiện đảm nhiệm phần bootstrap WDA fleet; bước tiếp theo là nhúng worker pool vào panel.
