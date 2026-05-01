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
- **Micro-interactions**: Phản hồi xúc giác qua các hiệu ứng chuyển cảnh, hover và trạng thái xử lý ảnh thời gian thực.

## 🚀 Trạng thái hiện tại

### ✅ Đã hoàn thiện
- Quy trình tạo Thumbnail từ Clipboard (Zero-click start).
- Vẽ Mask và định vị khung ảnh (Artboard/Crop) linh hoạt vượt ngoài biên.
- Hệ thống phím tắt Pro và Undo/Redo toàn diện.
- Thư viện Quick Actions (Face, BG, General, Magic).
- Quản lý lịch sử và nhánh phiên bản ảnh.

### 🛠 Lộ trình v1.4.0
- **Real-time SSE Monitoring**: Theo dõi Gemini xử lý từng layer theo thời gian thực.
- **Layer Manager**: Quản lý các lớp đối tượng chuyên sâu như Photoshop.
- **Bulk Profile Runner**: Áp dụng cùng lúc một Profile cho hàng loạt ảnh.

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
3. **Đóng gói sản phẩm**:
   ```bash
   npm run build
   ```

---
Phát triển bởi **mmmnhat** · 2026 · **ImageCraft Premium Edition**
