# ImageCraft Studio — Video Downloader & StoryStudio AI v1.3.0

Ứng dụng hỗ trợ tải video đa nền tảng, làm việc với TTS và xây dựng workflow tạo ảnh AI bằng Gemini với giao diện **ImageCraft** cao cấp.

## ✨ Điểm mới trong v1.3.0 "ImageCraft"

### 🎨 Siêu phẩm Giao diện (Aesthetics)
- **Thiết kế ImageCraft**: Giao diện hoàn toàn mới theo phong cách Dark Pro, sử dụng font chữ **Syne** và **JetBrains Mono** mang lại cảm giác premium.
- **Canvas Hi-End**: Trình xem ảnh với lưới (grid) chuyên nghiệp, hiệu ứng đổ bóng và lớp phủ (overlay) Gemini đang xử lý ảnh chân thực.
- **Micro-animations**: Các hiệu ứng hover, chuyển tab và thanh tiến trình được thiết kế mượt mà, sống động.
- **Titlebar Mac-style**: Thanh tiêu đề với hệ thống dot màu và tab chuyển đổi tối giản.

### 🛠 Thumbnail Studio (v1.3.0)
- **Action Builder (Field động)**: Tự tạo nút chức năng mới với các tham số tùy biến (Slider, Select, Input). Tự động sinh Prompt dựa trên template.
- **Workflow Profiles**: Giao diện chuỗi bước thực thi (Pipeline) cho phép hình dung các bước chỉnh sửa ảnh liên tiếp (Expand -> Boost -> Text).
- **History Strip**: Thanh lịch sử phiên bản hiển thị thumbnail trực quan, hỗ trợ nhận diện các nhánh (branch) sinh ảnh A/B/C.
- **Export Studio**: Xuất ảnh chất lượng cao với tùy chọn định dạng (PNG/JPG), độ phân giải (HD/FHD) và thư mục lưu trữ linh hoạt.

### 🧹 Tối ưu hóa hệ thống
- **Storage Cleanup**: Dọn dẹp các file rác, file backup cũ. Toàn bộ dữ liệu Story Pipeline đã được chuyển vào thư mục `cache/story_pipeline` để giữ cho thư mục gốc luôn sạch sẽ.
- **Unified API**: Đồng bộ hóa toàn bộ state giữa Frontend và Backend thông qua hệ thống API chuẩn.

## 🚀 Trạng thái hiện tại

### Đã hoàn thiện
- Dán ảnh trực tiếp từ Clipboard để bắt đầu, loại bỏ flow tạo project rườm rà.
- Thư viện Quick Actions phân loại thông minh (Face, BG, General).
- Hệ thống tham số động (Dynamic Parameters) cho từng Action.
- Lưu trữ lịch sử phiên bản (Version History) không giới hạn.
- Export ảnh cuối cùng kèm theo mở thư mục tự động.

### Kế hoạch v1.3.x
- **Real-time SSE**: Cập nhật tiến độ Gemini xử lý từng giây về giao diện.
- **Mask Painting**: Công cụ vẽ Brush/Eraser trực tiếp trên Canvas để khoanh vùng chỉnh sửa.
- **Profile Runner**: Kích hoạt chạy tự động toàn bộ chuỗi Action trong Profile chỉ với 1 click.

## 🛠 Hướng dẫn chạy

1. **Chạy ứng dụng chính**:
   ```bash
   python main.py
   ```
2. **Phát triển Frontend (Dev mode)**:
   ```bash
   cd web
   npm install
   npm run dev
   ```
3. **Đóng gói sản phẩm**:
   ```bash
   python auto_build.py
   ```

---
Phát triển bởi **mmmnhat** · 2026 · **ImageCraft Premium Edition**
