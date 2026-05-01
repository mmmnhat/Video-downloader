# Flowgen Studio — Video Downloader, TTS & AI Generative Studio v1.3.0

Ứng dụng hỗ trợ tải video đa nền tảng, tạo nội dung hàng loạt với TTS (Text-to-Speech) và chỉnh sửa/tạo ảnh tự động sử dụng AI (Gemini) với giao diện cao cấp.

## ✨ Điểm mới nổi bật trong phiên bản v1.3.0

### 🎨 Kiến trúc & Giao diện (Aesthetics)
- **Giao diện 2 cột thông minh (Story Studio)**: Tối ưu hóa không gian làm việc với giao diện chia 2 cột, hỗ trợ quản lý quy trình tạo video, kịch bản và ảnh một cách trực quan.
- **Dark Pro Design**: Thiết kế giao diện cao cấp sử dụng font chữ **Syne** và **JetBrains Mono**, tối giản các đường viền rườm rà.
- **Thanh trạng thái & Điều khiển**: Tích hợp các chấm trạng thái (green dots) và nút điều khiển luồng thế hệ mới (Pause/Resume/Stop) cho hệ thống tạo kịch bản/ảnh.

### 🖼️ Thumbnail Studio - Trải nghiệm Canvas tương tác
- **Công cụ Mask & Khung (Frame/Crop/Artboard)**: Vẽ khung, cắt ảnh và tạo Artboard ngay trên canvas bằng chuột.
- **Tương tác thông minh**: Thêm điểm neo (anchor points) ở các góc/cạnh cho phép thay đổi kích thước linh hoạt các thành phần vẽ (Shape/Crop/Artboard) với tọa độ chính xác tuyệt đối.
- **Phím tắt chuyên nghiệp (Keyboard Shortcuts)**: Tăng tốc độ chỉnh sửa với hệ thống phím tắt (V: Di chuyển, B: Brush, E: Tẩy, C: Crop, A: Artboard, T: Transform, [, ]: Chỉnh cỡ cọ vẽ, Delete: Xóa, Ctrl/Cmd + Z: Hoàn tác).
- **History Navigator & A/B Testing**: So sánh phiên bản Thumbnail (A/B testing) và xem lại thanh lịch sử làm việc mượt mà.

### 🛠️ Story Studio & Image Generation Pipeline
- **Quản lý phiên bản ảnh Gemini**: Chỉnh sửa (Refine) prompt trực tiếp với AI thay vì chỉ tạo mới. Quản lý thư mục chứa file, lọc các ảnh không ưng ý.
- **Giám sát trình duyệt & Headless Mode**: Thêm nút bật/tắt chế độ Headless cho việc gọi API ẩn danh, giúp hạn chế rác bộ nhớ và tối ưu tài nguyên máy tính.
- **Đồng bộ hóa luồng (Pipeline Orchestration)**: Tích hợp và khắc phục lỗi nghẽn luồng giữa giao diện Web UI (React) và bộ xử lý Playwright (Python).

### 🎙️ Quản lý TTS & Giọng đọc
- Tính năng làm mới danh sách giọng đọc (Rescan Voices).
- Đơn giản hóa cài đặt gốc và thống nhất các giao diện con thành một luồng (pipeline) liền mạch.

## 🚀 Trạng thái phát triển

### Tính năng cốt lõi (Đã hoàn thành)
- Tải video từ nhiều nền tảng (Video Downloader).
- Quản lý chiến dịch, tạo cấu trúc kịch bản và tự động hóa TTS.
- Studio tạo ảnh và chỉnh sửa (Thumbnail Studio) kết hợp vẽ Canvas + Prompt AI.
- Hệ thống Plugin & Script Action tùy chỉnh theo thư viện.

### Kế hoạch v1.4.x
- **Real-time SSE**: Cập nhật tiến trình AI tạo ảnh theo từng giây thay vì chờ đến khi xong.
- **Nâng cấp Mask Painting**: Hoàn thiện thuật toán làm mượt viền khi vẽ Brush.
- **Video Assembly**: Ghép nối tự động các phân đoạn ảnh, video và TTS thành sản phẩm cuối cùng.

## 💻 Hướng dẫn chạy ứng dụng

1. **Khởi động Môi trường & Backend (Python)**:
   ```bash
   # Cài đặt (lần đầu)
   pip install -r requirements.txt
   
   # Khởi chạy server và UI
   ./.venv/bin/python main.py
   ```

2. **Phát triển Frontend (Dev mode)**:
   ```bash
   cd web
   npm install
   npm run dev
   ```

3. **Build Frontend cho Production**:
   ```bash
   cd web
   npm run build
   ```

---
Phát triển bởi **mmmnhat** · 2026 · **Flowgen Studio Edition**
