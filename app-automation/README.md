# App Automation (standalone)

Phần mềm **độc lập** điều khiển iPhone bằng **go-ios + WebDriverAgent HTTP**.

Không dùng:
- Appium
- Xcode / xcodebuild runtime
- `wda_control_panel`
- `ios_wda_controller`

## Kiến trúc

```text
Windows/macOS PC
  └─ resources/bin/<os>/ios   (go-ios bundled)
       ├─ tunnel start --userspace
       ├─ install --path=resources/ipa/WebDriverAgentRunner.ipa
       ├─ runwda
       └─ forward 8100 8100
            └─ http://127.0.0.1:8100  (WDA)
                 └─ host/flows (ExpressVPN → TikTok signup)
```

## Cấu trúc

```text
app-automation/
├── main.py
├── config.yaml
├── host/                 # Python: device + WDA client + flows + API
├── panel/                # Web UI quản lý
├── resources/
│   ├── bin/darwin/ios    # go-ios
│   └── ipa/WebDriverAgentRunner.ipa
├── scripts/fetch_go_ios.py
├── captures/
└── data/
```

## Chuẩn bị

1. iPhone USB + Trust + **Developer Mode ON**
2. Sau khi cài IPA: trên iPhone **Trust developer**  
   `Cài đặt → Cài đặt chung → VPN & Quản lý thiết bị → Developer App → Trust`
3. File IPA đã ký đặt tại `resources/ipa/WebDriverAgentRunner.ipa`  
   (IPA chỉ cần ký 1 lần ở máy có Apple cert; app này không build Xcode)

```bash
cd app-automation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# nếu thiếu binary:
python scripts/fetch_go_ios.py
cp config.example.yaml config.yaml
./run.sh
```

Mở http://127.0.0.1:8788

## Flow dùng hàng ngày

1. Tab **Quản lý điện thoại** → Scan USB
2. **Install IPA** (lần đầu / khi đổi máy)
3. Trust developer trên iPhone nếu hỏi
4. **Bootstrap WDA** → pill **WDA online**
5. Start job `expressvpn` / `full`

## API

- `GET /api/devices`
- `POST /api/devices/select` `{ "udid": "..." }`
- `POST /api/device/install-wda`
- `POST /api/device/bootstrap`
- `POST /api/jobs` `{ "kind": "full", "account_index": 0 }`

## Lỗi thường gặp

| Log | Cách xử lý |
|-----|------------|
| `Developer App Certificate is not trusted` | Trust developer trên iPhone |
| `needs root privileges` | Giữ `tunnel_userspace: true` |
| `WDA IPA not found` | Copy IPA vào `resources/ipa/` |
| `go-ios not found` | `python scripts/fetch_go_ios.py` |

## Ghi chú IPA

Runtime **không** cần Mac Xcode. Chỉ khi **tạo IPA mới** (profile hết hạn ~7 ngày Personal Team) mới cần máy có Apple Developer để ký IPA, rồi copy vào `resources/ipa/`.
