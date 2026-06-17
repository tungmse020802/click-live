# Build WDA IPA on Mac (1 lần / năm)

Mục tiêu: tạo file `WebDriverAgentRunner.ipa` đã ký với Apple Developer cert,
copy sang PC Windows, dùng **3uTools** cài hàng loạt cho 20-40 iPhone.

## Yêu cầu

- macOS có Xcode 16 trở lên.
- Apple Developer account ($99/năm Personal hoặc $299/năm Enterprise).
  - Personal: tối đa 100 device/năm — đủ cho 20-40 iPhone.
  - Enterprise: không giới hạn device, không cần đăng ký UDID — phù hợp shop nhiều client.
- Source `ios_wda_controller` đã chạy `npm install` (để có WebDriverAgent project).

## Quy trình

### Bước 1 — Đăng ký device UDID (chỉ Personal Account)

Lấy UDID từng iPhone:

```bash
idevice_id -l         # cài qua brew install libimobiledevice
# hoặc dùng Xcode → Window → Devices and Simulators
```

Vào https://developer.apple.com/account/resources/devices/list, thêm 20 UDID
vào account. Bước này **không cần** với Enterprise.

### Bước 2 — Lấy TEAM_ID

```bash
security find-identity -v -p codesigning | grep "iPhone Developer"
# hoặc xem trong https://developer.apple.com/account → Membership → Team ID
```

TEAM_ID là chuỗi 10 ký tự dạng `ABCD123XYZ`.

### Bước 3 — Build IPA

Trên Mac có signing identity:

```bash
cd wda_control_panel
TEAM_ID=ABCD123XYZ ./scripts/build-ipa.sh
```

Output: `dist/wda-ipa/WebDriverAgentRunner.ipa` đã ký, sẵn sàng cài.

Build mất 2-5 phút lần đầu, các lần sau cache nhanh hơn.

### Bước 4 — Copy IPA sang Windows

```
WebDriverAgentRunner.ipa  →  PC Windows  →  3uTools "Install IPA"
```

Có thể dùng OneDrive, USB, scp, hay bất kỳ cách nào.

### Bước 5 — Cài lên 20 iPhone bằng 3uTools

Trên PC Windows:

1. Cắm 1 hoặc nhiều iPhone vào hub USB.
2. Mở 3uTools → tab `Apps` → `Install Local IPA`.
3. Chọn `WebDriverAgentRunner.ipa`.
4. Tick toàn bộ device cần cài → `Install`.

Sau khi cài, vào `Settings → General → VPN & Device Management → Trust`
trên từng iPhone (chỉ lần đầu cho mỗi cert).

> Verify: trên iPhone, app **WebDriverAgentRunner** xuất hiện. Mở thử thấy
> màn hình trắng và iPhone "đứng im" là OK — đó là test bundle, không có UI.
> Đừng tap thoát, để app idle.

### Bước 6 — Chạy WDA từ PC Windows

Bước này không nằm trong `build-ipa.sh`. PC Windows cần `pymobiledevice3`:

```powershell
pip install pymobiledevice3

# Tạo tunnel cho iOS 17+ (cần admin)
pymobiledevice3 lockdown start-tunnel --udid 00008030-XXXX

# Launch WDA test bundle, expose HTTP :8100
pymobiledevice3 developer dvt runwda --udid 00008030-XXXX --port 8100
```

Sau lệnh trên, WDA sẵn sàng nhận tap qua `http://127.0.0.1:8100/...`.
**WDA Control Panel** sẽ orchestrate 20 process này song song và map mỗi
iPhone tới một port riêng.

## Khi nào phải build lại

| Tình huống | Build lại? |
| --- | --- |
| Provisioning profile hết hạn (1 năm với Personal) | ✅ |
| Thêm iPhone mới ngoài danh sách 100 UDID | ✅ (Personal) / ❌ (Enterprise) |
| iOS update major version (17 → 18) | ✅ build lại với Xcode mới |
| Đổi Apple Developer account | ✅ |
| Aple thu hồi cert | ✅ ngay |
| Thay logic worker.js | ❌ — IPA không liên quan logic, chỉ là engine tap |

## Lưu ý quan trọng

- **Không upload IPA này lên TestFlight**. App Review reject ngay vì link
  `XCTest.framework`. IPA này chỉ dùng để **sideload** qua 3uTools/Sideloadly.
- **Không submit qua App Store Connect**. WebDriverAgent không phải app người
  dùng cuối, mà là test runner.
- **Cert Personal $99 giới hạn 100 device/năm**. Khi reset hằng năm, cần
  đăng ký lại UDID.
- **Cert Enterprise $299 nguy hiểm**: dùng sai mục đích Apple thu hồi cert →
  toàn bộ 20 iPhone mất WDA. Chỉ dùng nếu thực sự cần.
- Mac sau khi build xong **không cần chạy 24/7** — chỉ cần khi build lại.
