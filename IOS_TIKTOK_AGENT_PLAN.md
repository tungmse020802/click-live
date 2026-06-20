# iPhone TikTok Agent

## Phạm vi khả thi trên iOS

Ứng dụng iOS thông thường có thể:

- Mở TikTok hoặc một deeplink TikTok.
- Phân tích ảnh người dùng chọn bằng Vision.
- Xác định ảnh đã load dựa trên OCR.
- So khớp object hộp quà với template.
- Bỏ vùng timer khỏi dữ liệu nhận dạng.

Ứng dụng iOS thông thường không thể:

- Chụp màn hình của TikTok khi TikTok đang foreground.
- Tự tap vào giao diện TikTok.
- Đọc accessibility tree của ứng dụng TikTok.

Các giới hạn này đến từ sandbox và quyền riêng tư của iOS. Vì vậy project giai
đoạn đầu là ứng dụng companion dùng ảnh screenshot được chọn từ Photos.

## Luồng triển khai

```text
READY
  -> OPENING_TIKTOK
  -> WAITING_FOR_SCREENSHOT
  -> CHECKING_LOAD
  -> LOADED
  -> DETECTING_OBJECT
  -> OBJECT_FOUND | OBJECT_NOT_FOUND | LOAD_TIMEOUT
```

## Xác định load thành công

Vision OCR tìm một trong các từ khóa:

```text
like, comment, share, follow, following, for you
```

Nếu không có từ khóa, app vẫn cho phép chạy object matching thủ công để hỗ trợ
giao diện TikTok theo ngôn ngữ khác.

## Nhận dạng object và bỏ timer

Template nằm tại:

```text
TikTokAgent/Resources/treasure_box_no_timer.png
```

Trước khi tạo Vision feature print, cả template và screenshot candidate đều bị
crop bỏ `35%` phía dưới. Vì vậy text dạng `00:38`, `01:05` hoặc badge timer khác
không tham gia phép so khớp.

Giai đoạn hiện tại dùng `VNGenerateImageFeaturePrintRequest`. Khi có bộ dữ liệu
đa dạng hơn, có thể thay bằng Core ML object detector mà không đổi state machine.

## Chạy

```bash
cd ios_tiktok_agent
xcodebuild \
  -project TikTokAgent.xcodeproj \
  -target TikTokAgent \
  -sdk iphoneos \
  -configuration Debug \
  CODE_SIGNING_ALLOWED=NO \
  build
```

Để cài lên iPhone thật, mở project bằng Xcode, chọn Development Team và thiết bị.
