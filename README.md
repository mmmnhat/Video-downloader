# Video Downloader & StoryStudio AI v1.2.3

Ứng dụng hỗ trợ tải video đa nền tảng và sáng tạo nội dung AI (StoryStudio) tích hợp Gemini.

## 🚀 Có gì mới trong bản v1.2.3?

### 🎨 StoryStudio - Nâng cấp Bộ sưu tập & Gallery
- **Tab Bộ sưu tập hoàn toàn mới**: Chuyển đổi từ danh sách Video sang **Gallery ảnh**. Tất cả những tấm ảnh bạn đã bấm "Duyệt" sẽ xuất hiện tại đây như một kho lưu trữ thành phẩm.
- **Quy tắc đặt tên Export mới**: Ảnh xuất ra sẽ tự động được đặt tên theo định dạng `[TênVideo].m[Cảnh]s[Bước]v[BiếnThể]`. Ví dụ: `KB1.m2s3v1.png`.
- **Hỗ trợ Xuất hàng loạt**: Bạn có thể chọn nhiều ảnh trong Gallery và xuất tất cả vào thư mục đầu ra chỉ với một cú click.

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
