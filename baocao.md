# Video Downloader & StoryStudio AI v1.2.5

Ứng dụng hỗ trợ tải video đa nền tảng và sáng tạo nội dung AI (StoryStudio) tích hợp Gemini.

## 🚀 Có gì mới trong bản v1.2.5?
- **Khắc phục lỗi đẻ nhánh giao diện**: Chặn các process con Chromium vô tình gọi lại giao diện, chấm dứt tình trạng mở chồng chất cửa sổ vô hạn.
- **Tối ưu hóa ThumbnailStudio**: Viết lại hoàn toàn giao diện tạo Thumbnail theo chuẩn shadcn/ui để đồng bộ thiết kế với toàn ứng dụng (sử dụng Card, Tabs thống nhất).
- **Phân luồng FFmpeg**: Ép tất cả các tác vụ FFmpeg ngầm chỉ được dùng tối đa 2 threads, giải quyết dứt điểm hiện tượng treo máy 100% CPU khi chạy song song.
- **Sửa lỗi Race Condition tiến trình**: Phân biệt định danh chính xác các tiến trình con khi đang cắt nhiều segment của cùng 1 video.

## 🚀 Có gì mới trong bản v1.2.4?

### 🔄 Nâng cấp Trình cập nhật hệ thống (Auto-Updater)
- **Thông báo chủ động**: App sẽ tự động kiểm tra bản cập nhật mới ngay khi khởi động và gửi thông báo nếu có bản vá mới.
- **Thanh tiến trình trực quan**: Bổ sung thanh % tiến độ khi đang tải bản cập nhật, giúp bạn biết chính xác tình trạng xử lý.
- **Thông tin chi tiết**: Hiển thị các dòng trạng thái thời gian thực (Đang tải, Giải nén, Khởi động lại...) thay vì chỉ hiển thị biểu tượng chờ.
- **Xử lý nền**: Quá trình cập nhật giờ đây không còn làm treo giao diện người dùng.

### 🎨 StoryStudio - Nâng cấp Bộ sưu tập & Gallery (v1.2.3)
- **Tab Bộ sưu tập hoàn toàn mới**: Chuyển đổi từ danh sách Video sang **Gallery ảnh**.
- **Quy tắc đặt tên Export mới**: `[TênVideo].m[Cảnh]s[Bước]v[BiếnThể]`.
- **Hỗ trợ Xuất hàng loạt**: Chọn nhiều ảnh và xuất cùng lúc.

### ⚡ Tự động hóa & Hiệu năng
- **Chế độ Tự động chạy (Auto-run)**: 
  - Khi bấm **Tinh chỉnh (Refine)** hoặc **Tạo lại (Regenerate)**, trình duyệt sẽ tự động mở và xử lý ngay lập tức.
  - Khi bấm **Duyệt (Accept)**, hệ thống sẽ tự động chuyển sang bước tiếp theo nếu có.
- **Refine thông minh**: Chức năng Tinh chỉnh giờ đây sẽ luôn mở một phiên chat mới và tự động Upload ảnh từ bước trước đó lên Gemini để làm input.

### 🛠️ Sửa lỗi & Ổn định
- **Sửa lỗi hiển thị**: Khắc phục triệt để lỗi font chữ/mã hóa trong Popup cập nhật hệ thống.
- **Ổn định UI**: Sửa lỗi crash sidebar khi thao tác với các bước mới chưa có kết quả.
- **Tương thích Windows**: Cải thiện tính năng "Mở thư mục" (Open Output Folder) trên Windows.

---

## 🛠 Hướng dẫn cài đặt & Sử dụng

1. **Chạy từ Source (Dev)**:
   ```bash
   python main.py
   ```
2. **Xây dựng bản App (.exe)**:
   ```bash
   python build.py
   ```

## 📝 Yêu cầu hệ thống
- Python 3.10+
- Google Chrome / Microsoft Edge (để chạy Automation)
- Tài khoản Gemini (đã đăng nhập trên trình duyệt)

---
*Phát triển bởi mmmnhat - 2026*
