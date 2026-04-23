# Flowgen - Video Downloader & TTS Studio

Flowgen là một công cụ mạnh mẽ, giao diện hiện đại (React/PyQt6) chạy trực tiếp trên máy tính. Công cụ giúp tự động hóa việc tải video từ hàng chục nền tảng và chuyển đổi văn bản thành giọng nói (TTS) hàng loạt với chất lượng cao.

## ✨ Tính năng chính

### 1. Trình tải Video tự động (Video Downloader)
- **Tự động hóa qua Google Sheets**: Chỉ cần dán link sheet, công cụ sẽ quét toàn bộ danh sách URL.
- **Hỗ trợ đa nền tảng**: Tối ưu cho YouTube, Facebook, Instagram, TikTok, Threads, X (Twitter), Reddit, Pinterest, Dumpert, Dailymotion, Yandex, v.v.
- **Xử lý tên file & Cắt video (Auto-cut)**:
  - Đặt tên file theo cột số thứ tự (STT) trong sheet.
  - Tự động cắt video theo mốc thời gian (ví dụ: `00:52-01:04`).
  - Hỗ trợ cắt nhiều đoạn từ một link duy nhất (ví dụ: `0:10-0:20, 1:30-1:40`).
- **Quản lý chuyên nghiệp**:
  - Chuyển đổi mặc định về MP4 H.264 để tương thích tốt nhất với các phần mềm chỉnh sửa (Premiere, CapCut).
  - Theo dõi tiến độ thời gian thực, hỗ trợ Stop/Retry linh hoạt.
  - Tự động nạp Cookies từ trình duyệt (Chrome, Cốc Cốc...) để tải video ở chế độ riêng tư.

### 2. Studio lồng tiếng (TTS Studio) - MỚI
- **Tích hợp ElevenLabs**: Sử dụng trình duyệt giả lập (Playwright) để đăng nhập và lấy giọng đọc cá nhân hóa một cách nhanh chóng.
- **Xử lý hàng loạt**: Đọc kịch bản từ Google Sheets, chọn giọng đọc và tạo file âm thanh hàng loạt.
- **Tiết kiệm chi phí**: Giúp quản lý và sử dụng hạn mức ElevenLabs tối ưu nhất cho công việc sản xuất nội dung.

### 3. Desktop App (PyQt6)
- Giao diện cửa sổ ứng dụng Windows hiện đại, không cần mở trình duyệt rời.
- Tích hợp tính năng **Tự động cập nhật (Auto-Update)**: Nhận thông báo và cập nhật phiên bản mới chỉ với một cú click.

### 4. Story Pipeline cho Gemini Web (MVP Backend)
- Đã có `state machine + scheduler` cho workflow:
  - Video chạy song song theo worker pool.
  - Marker/Step chạy tuần tự trong từng video.
  - Attempt hỗ trợ `regenerate` và `refine`.
- Đã có API backend cho import manifest, run/pause video, action review (`accept/regenerate/refine/skip`), và session Gemini (`status/open-login`).
- Hỗ trợ 2 backend gen:
  - `local_preview` (mock local)
  - `gemini_web` (Playwright: upload ảnh + gửi prompt + capture preview + normalize)
- Có `selector debug mode` cho Gemini: tự lưu screenshot + HTML + DOM/heuristic JSON khi fail để tune nhanh trên Windows.
- Tài liệu kỹ thuật: xem [`docs/story-pipeline-spec.md`](docs/story-pipeline-spec.md).

---

## 🚀 Tải về & Cài đặt nhanh (Windows)

Nếu bạn không muốn cài đặt mã nguồn, hãy sử dụng bản đóng gói sẵn:

1. Truy cập [Releases](https://github.com/mmmnhat/Video-downloader/releases).
2. Tải file `VideoDownloader_v1.0.1.zip`.
3. Giải nén và chạy `VideoDownloader.exe`.

---

## 🛠️ Cài đặt từ mã nguồn (Dành cho Developer)

### 1. Yêu cầu hệ thống
- **Python 3.9+**
- **FFmpeg & FFprobe**: Cần thiết để xử lý video/audio.
- **Playwright**: Dùng cho tính năng TTS.

### 2. Các bước thực hiện
```bash
# Clone repository
git clone https://github.com/mmmnhat/Video-downloader.git
cd Video-downloader

# Tạo và kích hoạt môi trường ảo
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Cài đặt thư viện
pip install -r requirements.txt

# Cài đặt trình duyệt cho Playwright (cho TTS)
playwright install chromium
```

### 3. Chạy ứng dụng
```bash
python main.py
```

---

## 📦 Đóng gói ứng dụng (.exe)

Sử dụng script tự động để build bản portable cho Windows:
```powershell
python auto_build.py
```
Kết quả sẽ nằm trong thư mục `dist/VideoDownloader`.

---

## 📝 Ghi chú & Khắc phục lỗi
- **Cookies**: Nếu gặp lỗi không tải được video riêng tư hoặc bị chặn bởi nền tảng, hãy vào phần Settings trên UI để dán Netscape Cookies hoặc trỏ tới file cookies.
- **YouTube Shorts**: Một số video có thể bị lỗi `PO Token`. Hãy thử cập nhật `yt-dlp` hoặc sử dụng Cookies để vượt qua.
- **TikTok**: Nếu tải thất bại, hãy ấn **Retry** để công cụ thử qua Mobile API dự phòng.

## ⚖️ Tuyên bố từ chối trách nhiệm
Công cụ được xây dựng nhằm mục đích hỗ trợ tự động hóa công việc cá nhân. Người dùng tự chịu trách nhiệm về việc tuân thủ điều khoản sử dụng và bản quyền của các nền tảng video/âm thanh liên quan. Không sử dụng công cụ để phá khóa các nội dung được bảo vệ bởi DRM.
