# ImageCraft Studio — Video Downloader & StoryStudio AI v1.3.0 "Titanium"

Ứng dụng tối thượng hỗ trợ tải video đa nền tảng, quản lý TTS và hệ thống **Thumbnail Studio AI** thế hệ mới. Trải nghiệm quy trình sáng tạo chuyên nghiệp với giao diện ImageCraft cao cấp.

## ✨ Điểm mới trong v1.3.0 "Titanium Edition"

### 🎨 Trải nghiệm Canvas Đỉnh cao (Pro Canvas Experience)
- **Interactive Masking**: Hỗ trợ bộ công cụ vẽ (Brush/Eraser) trực tiếp trên Canvas với khả năng thay đổi kích thước cọ vẽ linh hoạt.
- **Dynamic Resizing**: Hệ thống điểm neo (Anchor Points) thông minh cho phép kéo giãn, thu phóng Artboard, Crop và các Shape (Rect/Ellipse) một cách trực quan.
- **Keyboard Power User**: Hệ thống phím tắt toàn diện dành cho Pro:
  - `V` (Pointer), `B` (Brush), `E` (Eraser), `C` (Crop), `A` (Artboard).
  - `R` (Rect), `O` (Ellipse), `T` (Transform).
  - `[` / `]` để chỉnh size cọ.
  - `Ctrl/Cmd + Z / Y` cho Undo/Redo vô hạn.

### 🛠 Thumbnail Studio Workflow
- **Action Builder 2.0**: Tự định nghĩa các nút chức năng với tham số động (Slider, Select, Input). Prompt tự động sinh ra dựa trên logic template thông minh.
- **Pipeline Visualization**: Hình dung toàn bộ chuỗi hiệu ứng (Expand -> Face Swap -> Color Grade) qua giao diện Profile Runner.
- **Version Branching**: Lưu trữ và so sánh các phiên bản ảnh (A/B testing) trực quan qua dải History Strip.
- **High-Speed Export**: Xuất ảnh HD/FHD siêu tốc, tự động phân loại theo dự án.

### 🎨 Ngôn ngữ thiết kế ImageCraft
- **Titanium Dark UI**: Giao diện tối chuyên nghiệp sử dụng font **Syne** (Heading) và **JetBrains Mono** (Data).
- **Glassmorphism Controls**: Các thanh công cụ và Dock điều khiển nổi (Floating Dock) với hiệu ứng làm mờ kính cao cấp.

---

## 📜 Lịch sử phiên bản (Changelog)

### v1.3.0 — Titanium Edition (Hiện tại)
- **Pro Canvas**: Tích hợp công cụ vẽ Mask (Brush/Eraser) và điều chỉnh kích thước Artboard/Crop/Shape bằng tay.
- **Keyboard Shortcuts**: Hệ thống phím tắt chuyên nghiệp tối ưu hóa tốc độ làm việc.
- **Undo/Redo System**: Hỗ trợ hoàn tác mọi thao tác trên Canvas và Mask.
- **UI Refinement**: Cập nhật font chữ Syne, JetBrains Mono và hiệu ứng Glassmorphism toàn diện.

### v1.2.0 — Thumbnail & Gemini Integration
- **Thumbnail Studio**: Ra mắt module chỉnh sửa ảnh thu nhỏ tích hợp AI.
- **Gemini AI Integration**: Tự động sinh Prompt thông minh dựa trên ngữ cảnh ảnh và Action.
- **Action Library**: Hệ thống thư viện Action phân loại (Face, Background, General).
- **Version History**: Lưu trữ các phiên bản ảnh được tạo ra trong một phiên làm việc.

### v1.1.0 — StoryStudio AI & TTS
- **StoryStudio AI**: Quy trình tạo video story tự động từ kịch bản.
- **TTS Manager**: Tích hợp các công cụ chuyển đổi văn bản thành giọng nói (Text-to-Speech).
- **Pipeline Management**: Hệ thống quản lý luồng xử lý video đa luồng.
- **Folder Sync**: Tự động đồng bộ hóa thư mục video và tài nguyên.

### v1.0.0 — The Foundation
- **Video Downloader**: Hỗ trợ tải video chất lượng cao từ nhiều nền tảng (YouTube, TikTok, Facebook).
- **Core UI**: Giao diện người dùng cơ bản với Python Backend và React Frontend.
- **Basic Auth**: Hệ thống đăng nhập và cài đặt cấu hình ban đầu.

---

## 🚀 Trạng thái hiện tại

### ✅ Đã hoàn thiện
- Quy trình tạo Thumbnail từ Clipboard (Zero-click start).
- Vẽ Mask và định vị khung ảnh (Artboard/Crop) linh hoạt.
- Hệ thống phím tắt Pro và Undo/Redo toàn diện.
- Xuất ảnh HD/FHD và quản lý lịch sử phiên bản.

### 🛠 Lộ trình v1.4.0
- **Real-time SSE Monitoring**: Theo dõi tiến độ Gemini xử lý từng layer.
- **Layer Manager**: Quản lý các lớp đối tượng như Photoshop.
- **Bulk Profile Runner**: Áp dụng Profile hàng loạt cho nhiều ảnh.

## 🛠 Hướng dẫn chạy

1. **Chạy ứng dụng chính**:
   ```bash
   python main.py
   ```
2. **Phát triển Frontend (Dev mode)**:
   ```bash
   cd web
   npm run dev
   ```

---
Phát triển bởi **mmmnhat** · 2026 · **ImageCraft Premium Edition**
