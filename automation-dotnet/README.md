# Click Live Desktop Tool (.NET Core Native WPF)

Ứng dụng Native Desktop WPF (.NET 8) tự động click và đếm giờ với độ chính xác và độ ổn định cao trên Windows.

## 🔥 Điểm cải tiến so với bản Electron cũ:
1. **Chạy Native Win32 P/Invoke**: Gọi trực tiếp `SetCursorPos` & `mouse_event` của Windows OS, tốc độ thực thi sub-millisecond (0.1ms - 0.5ms), không bị độ trễ hay lỗi văng native module của Node.js / `koffi`.
2. **Copy Y Hệt Giao Diện & Logic 100%**:
   - **Tài khoản Queue**: Nhập URL Queue Server, Username (`admin`), Password (`Admin123@`), nút Đăng nhập / Đăng xuất, hiển thị badge trạng thái.
   - **Đếm giờ & Delay Offset (±)**: Tùy chỉnh `DefaultWaitSec`, nút tăng/giảm nhanh `-0.05s`, `-0.01s`, `+0.01s`, `+0.05s`, hiển thị nhãn offset đổi màu trực quan và ô giải thích mốc timing.
   - **Click Desktop (ngoài app)**: Tùy chọn Tự click, nhập X, Y (pixel), nút **"Chọn điểm trên màn hình"** (Overlay trong suốt 1-click), nút **"Test click"**.
   - **Trạng thái & Thống kê Click**: Hiển thị bảng kết quả chi tiết (Vị trí click, Giờ click thực tế, Giờ chuẩn target, Lệch ms, Gợi ý offset tự động).
   - **Log Click / Timing**: Bảng log màu theo thời gian thực (Poll, Schedule, Wait, Click, Error) + Lưu file log ngày `click-YYYY-MM-DD.log`.

## 🛠 Hướng dẫn Build trên Windows:
1. Cài đặt **.NET 8.0 SDK** trên Windows.
2. Mở cửa sổ CMD / PowerShell tại thư mục `automation-dotnet/`.
3. Chạy file `build.bat` (hoặc lệnh `dotnet publish -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -o ./dist`).
4. Chạy file thực thi `./dist/AutomationDotNet.exe`.
