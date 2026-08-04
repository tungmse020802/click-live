# Desktop Tool

App Electron chạy nền — mở **countdown link trong Google Chrome** từ queue UI. Mỗi lần nhấn **Mở link** → **tab mới trong cùng một cửa sổ Chrome**. **Auto-click chỉ theo tab mở cuối cùng**; tab hết hạn đóng từng cái, **tab cuối được giữ lại**.

## Cài & chạy

### macOS / Linux

**Combo pull → run (macOS / Linux):**

```bash
cd desktop-tool
./run.sh
```

Hoặc thủ công:

```bash
cd desktop-tool
cp .env.example .env
# Chỉ cần DESKTOP_TOOL_QUEUE_URL — login user trong app
npm install
npm start
```

### Windows (cài từ đầu A-Z)

Double-click hoặc chạy trong **PowerShell / CMD**:

```bat
cd desktop-tool\scripts
install-windows.bat
```

Script tự làm:
1. Cài **Git**, **Node.js LTS**, **Google Chrome** (qua `winget` nếu thiếu)
2. Clone repo `https://github.com/tungmse020802/click-live.git` → `%USERPROFILE%\click-live`
3. Tạo `.env` (URL queue), login user trong app
4. `npm install` + `npm start`
5. Tạo shortcut **Click Live Desktop Tool** trên Desktop

**Chạy lại sau này:**

```bat
desktop-tool\scripts\run-windows.bat
```

**Tuỳ chọn — cài không clone (đã có repo):**

```powershell
powershell -ExecutionPolicy Bypass -File desktop-tool\scripts\install-windows.ps1 -SkipClone
```

**Yêu cầu Windows:** Windows 10+, PowerShell 5.1+, quyền cài app (winget). Desktop click dùng PowerShell (không cần cài thêm).

## Đóng gói — chạy không cần Node.js (portable)

Build trên **Mac** (ra `.dmg` / `.zip`) hoặc **Windows** (ra `.exe` portable + installer). Máy dùng chỉ cần **Google Chrome** + file **`.env`**.

### macOS (build trên Mac)

```bash
cd desktop-tool
chmod +x scripts/package-mac.sh
./scripts/package-mac.sh
```

Hoặc: `npm install && npm run dist:mac`

File: `dist/ClickLiveDesktopTool-0.1.0-mac.dmg` (hoặc `.zip`).

**Cấu hình:** đặt `.env` **cùng thư mục** với `Click Live Desktop Tool.app` (không bên trong `.app`):

```text
Applications/
  Click Live Desktop Tool.app
  .env                    ← DESKTOP_TOOL_QUEUE_URL; login user trong app
```

### Windows (build trên Windows)

```bat
cd desktop-tool\scripts
package-windows.bat
```

Hoặc: `npm install && npm run dist:win`

| File | Mô tả |
|------|--------|
| `ClickLiveDesktopTool-*-portable.exe` | **Portable** — copy sang USB/máy khác, không cần cài |
| `ClickLiveDesktopTool-*-setup.exe` | Cài qua installer |

**Cấu hình portable:** đặt `.env` **cùng folder** với file `.exe` khi chạy:

```text
D:\ClickLive\
  ClickLiveDesktopTool-0.1.0-portable.exe
  .env
```

Nội dung `.env` (copy từ `.env.example` trong repo):

```env
DESKTOP_TOOL_QUEUE_URL=http://160.30.19.215:8787
```

Sau khi mở app: **Tài khoản queue** → chọn user (admin1…admin10) → mật khẩu `Admin123@`.

### Test bản build (chưa đóng gói installer)

```bash
npm run pack
# chạy thử: dist/mac-arm64/Click Live Desktop Tool.app
```

**Lưu ý:** Build Windows trên Mac cần Wine (phức tạp) — nên build Win trên máy Windows. Mac build trên Mac.

API local: `http://127.0.0.1:8795` (fallback). Luồng chính: poll queue server.

## Cài đặt đếm giờ & click desktop

Mở cửa sổ **Cài đặt** từ tray (click icon) hoặc menu:

| Mục | Mô tả |
|-----|--------|
| **TIME + offset ±** | Lấy TIME từ tin Telegram (vd. `00:57s`) + offset ±0.01s / ±0.05s |
| **Chờ mặc định** | Dùng khi tin không có TIME |
| **Chọn điểm trên màn hình** | Overlay toàn màn hình — click chọn tọa độ desktop (không phải trong app) |
| **Test click** | Thử click ngay tại X,Y |
| **Tự click sau khi hết giờ** | Bật/tắt auto click |

Luồng: **Mở link** → Chrome countdown → chờ TIME + offset → **click desktop** tại (X,Y).

### Quyền macOS

Cần bật **Accessibility** cho Electron / Terminal (System Settings → Privacy & Security → Accessibility) để click desktop hoạt động.

Tuỳ chọn cài `cliclick` (ổn định hơn AppleScript):

```bash
brew install cliclick
```

### Log click (debug timing)

Mỗi job ghi file JSON theo ngày:

| Môi trường | Thư mục |
|------------|---------|
| `npm start` (dev) | `desktop-tool/logs/click-YYYY-MM-DD.log` |
| App cài (.exe / .dmg) | `%APPDATA%\click-live-desktop-tool\logs\` (Win) hoặc `~/Library/Application Support/click-live-desktop-tool/logs/` (Mac) |

Tuỳ chọn trong `.env`: `DESKTOP_TOOL_LOG_DIR=C:\ClickLive\logs`

Mỗi dòng JSON gồm event: `startup`, `poll`, `schedule`, `wait`, `click`, `helper`, `skip`, `error`. Field quan trọng khi debug:

- `driftMs` — timer chờ lệch bao nhiêu so `executeAtMs`
- `driftFromDisplayMs` — click thực tế lệch bao nhiêu so mốc overlay 0.0s (âm = sớm, dương = muộn)
- `clickDurationMs` — PowerShell/cliclick mất bao lâu
- `method` — `powershell-helper` (nhanh) vs `powershell` (fallback chậm)

Settings lưu tại `~/Library/Application Support/click-live-desktop-tool/settings.json`.

## Luồng

```text
queue_ui (web / điện thoại — mọi thiết bị)
  → POST /api/desktop/open  (dedup URL trên server)
desktop-tool (Mac)
  → GET /api/desktop/pull?token=...  (mỗi 2s)
  → mở 1 tab **Google Chrome (incognito)** / URL (dedup local)
  → tự đóng tab Chrome sau 30s

## Vì sao đôi khi nhảy sang TikTok `@junb2483`?

Đã kiểm tra bằng Playwright (load thật trang junb):

| URL mở | Kết quả sau ~3 giây |
|--------|---------------------|
| `...&amp;m=...&amp;t=...` (tool gửi nguyên `&amp;`) | **Tự redirect** → `https://www.tiktok.com/@junb2483` |
| `...&m=...&t=...` (click link trong tin — browser decode `href`) | **Ở lại countdown** — hiển thị đúng user/coin |

**Không phải do desktop-tool “bấm COPY”** — trang junb tự chuyển hướng khi query string hỏng (thiếu `m`, `t`, `bt` vì `&amp;` không được parse thành `&`).

Nguyên nhân từ phía click-live (đã fix local, **cần deploy server**):

1. Telegram lưu href dạng HTML: `&amp;m=` `&amp;t=`
2. Click tay trong queue → trình duyệt **tự decode** `href` → URL đúng
3. **Mở link** (server cũ) → gửi `countdown_url` có `&amp;` nguyên xi → Chrome mở URL hỏng → junb redirect TikTok

Trang junb còn có nút **COPY** — nếu Chrome đã lưu `localStorage.app_link` (nút **+**), bấm COPY cũng mở TikTok. Desktop-tool mặc định **incognito** để tránh `app_link` cũ.

Sau deploy, kiểm tra source queue có `<meta name="click-live-queue-version" content="countdown-href-v2">`.
```

Nhiều thiết bị bấm **Mở link** cùng URL → **chỉ 1 tab** trên desktop.

Chấm **Desktop** xanh khi desktop-tool poll server trong ~20s gần nhất.

## API

| Endpoint | Mô tả |
|---|---|
| `GET /health` | Kiểm tra app đang chạy |
| `POST /open` | Mở tab Chrome countdown (`url`, `ttl_seconds`, `job_id`) |

Đổi trình duyệt (macOS): `DESKTOP_CHROME_APP="Google Chrome"` trong `.env`

## Queue UI

- Giao diện chat kiểu Telegram (tin đã giải mã `display_html`)
- Nút **Mở link** → server relay → desktop-tool poll
- Chấm xanh **Desktop** khi app poll server (không còn gọi localhost từ trình duyệt)

## Yêu cầu

- Queue UI (`click-live-queue`)
- `profile_playwright` API cho link chưa có `countdown_url` sẵn
