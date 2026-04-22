# Flowgen - Video Downloader & TTS Studio

Flowgen là một công cụ local mạnh mẽ chạy trên máy cá nhân với giao diện Web UI hiện đại (React/Vite/Tailwind) được tích hợp sẵn làm mặc định. Tool giúp bạn tự động hóa việc tải video từ nhiều nền tảng và tạo giọng đọc AI (Text-to-Speech) hàng loạt.

## Tính năng chính

### 1. Trình tải Video tự động (Video Downloader)
- **Tự động hóa qua Google Sheets:** Chỉ cần dán link sheet chứa danh sách URL video.
- **Tự nhận diện nền tảng:** Hỗ trợ tải từ YouTube, Facebook, Instagram, TikTok, Pinterest, X, Reddit, Dumpert, v.v.
- **Xử lý tên & cắt video (Auto-cut):**
  - Đặt tên file đầu ra theo cột `STT` trong sheet.
  - Tự động cắt video theo cột `Time` / `Thời lượng` (ví dụ: `00:52-01:04`).
  - Hỗ trợ cắt thành nhiều đoạn trong cùng 1 video (ví dụ: `0.3-0.5, 0.10-0.12`).
- **Quản lý Download chặt chẽ:** 
  - Lưu tất cả video vào chung một thư mục, file được chuẩn hóa về định dạng MP4 H.264 dễ dàng chèn vào các phần mềm edit.
  - Theo dõi tiến trình tải realtime (batch tracker), Stop nhanh đoạn đang tải, Retry các task lỗi. 
  - Lưu trạng thái (state) nội bộ ngay cả khi tắt nguồn hay tải lại trang web.
  - Có thể nạp cookies hoặc đọc trực tiếp từ trình duyệt (Cốc Cốc, Chrome...) để tải các video Private bị khoá.

### 2. Studio lồng tiếng (TTS Studio) - MỚI
- **Tích hợp sâu ElevenLabs qua Playwright:** Cho phép trình giả lập trình duyệt đăng nhập vào tài khoản ElevenLabs giúp cá nhân hoá giọng đọc cực nhanh mà không vướng các hạn mức API thông thường. 
- **Thiết lập theo cấu hình:**
  - Hỗ trợ nạp kịch bản (Text) thông qua Google Sheets.
  - Chọn Giọng đọc (Voice) hoặc chỉnh các thông số giọng nói trực tiếp từ Studio.
- **Xử lý hàng loạt âm thanh:** Hệ thống chạy đa luồng để gọi tạo file âm thanh (TTS) cho toàn bộ sheet một cách tự động và ổn định, xuất thẳng ra thư mục của bạn.

---

## Yêu cầu hệ thống

- Hệ điều hành: Windows, macOS hoặc Linux
- **Python 3.9+**
- `yt-dlp`
- `ffmpeg`, `ffprobe`
- (Tuỳ chọn) Node.js nếu muốn tự build lại giao diện Web UI.

Nếu máy chưa cài `yt-dlp`, hãy chạy:
```bash
python3 -m pip install --user yt-dlp
```

## Cài đặt chi tiết

Dưới đây là từng bước cài đặt cụ thể để khởi chạy ứng dụng từ mã nguồn gốc:

**Bước 1: Tải mã nguồn**
```bash
git clone https://github.com/mmmnhat/Video-downloader.git
cd Video-downloader
```

**Bước 2: Tạo và kích hoạt môi trường ảo (Virtual Environment)**
Việc này giúp các thư viện của app không xung đột với máy tính của bạn.
- **Trên Mac/Linux:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```
- **Trên Windows:**
  ```cmd
  python -m venv .venv
  .venv\Scripts\activate
  ```

**Bước 3: Cài đặt các thư viện lõi (Python Dependencies)**
```bash
pip install -r requirements.txt
```
*(Nếu hệ thống chưa cài được `yt-dlp`, có thể chạy thêm lệnh độc lập: `pip install yt-dlp`)*

**Bước 4: Cài đặt trình duyệt tự động (Playwright Browsers)**
Vì trình **TTS Studio** cần trình duyệt ảo để lấy giọng nói từ ElevenLabs, bạn bắt buộc phải cấp phép cài Chromium giả lập:
```bash
playwright install chromium
```

*(Giao diện web hiện đại đã được build tĩnh sẵn trong mục `web/dist`. Bạn hoàn toàn bỏ qua phần cài đặt NPM/NodeJS trừ phi có nhu cầu thay đổi, lập trình lại UI lúc đó hãy vào thư mục `web` để `npm install` và `npm run build`.)*

## Sử dụng

Khởi động ứng dụng bằng terminal:
```bash
python3 main.py
```

Ứng dụng sẽ chạy máy chủ FastAPI mượt mà và tự động mở giao diện Web UI hiện đại hiển thị trên trình duyệt mặc định ở địa chỉ:
```text
http://127.0.0.1:8765
```

Nếu bạn đang chạy tool trên thiết bị cắm máy/server và **không muốn** tool cố mở trình duyệt:
```bash
VIDEO_DOWNLOADER_NO_BROWSER=1 python3 main.py
```

---

## Đóng gói chạy trực tiếp không cần cài đặt (Windows Portable .exe)

Nếu bạn muốn tạo một bản `.exe` di động mang chép sang bất kỳ máy tính Windows nào để dùng mà không cần cài mã nguồn hay Python:

1. Phải chuẩn bị một máy build chạy hệ điều hành Windows và đã cài Python 3.9+.
2. (Tuỳ chọn) Có Node.js để build frontend mới nhất.
3. Tải và chép file `ffmpeg.exe` / `ffprobe.exe` vào thư mục `vendor/windows/bin/` trong source code này.
4. Mở PowerShell trong thư mục của Project và chạy:
```powershell
.\packaging\windows\build.ps1
```

Hoàn tất, Script sẽ gộp nguyên bộ source thành một khối trong thư mục `dist/VideoDownloader`. File gửi đi sẽ đủ mọi chức năng và máy người nhận chỉ việc click khởi chạy file `VideoDownloader.exe`.

---

## Khắc phục lỗi thường gặp / Tháo gỡ khó khăn

- **Web từ chối/bắt Captcha chặn tải:** Tính năng Auto-fallback qua lớp HTTP scraper được bật giúp tải từ những luồng như Threads/Dailymotion. Với video cần xem được mới tải được (Private Mode), bạn buộc phải thêm Cookies vào mục cài đặt trên màn hình UI. App tự bật cơ chế mạo danh `--impersonate chrome` để qua mặt Cloudflare chặn web.
- **Trạng thái lịch sử Download và TTS:** Các thông số đã tải, cấu hình giọng đều được ứng dụng tự lưu đệm ở những tệp `app_state.json` và `tts_state.json`. Hãy để nguyên các tệp này, chúng là nơi lưu bộ nhớ hệ thống.
- **Tải TikTok bị thất bại:** Máy chủ TikTok thỉnh thoảng update bộ máy chặn thuật toán. Tool sẽ thay đổi qua Mobile API nội bộ, nhưng đối với những nội dung khó, vui lòng ấn nút Retry từ giao diện tracker hoặc chèn Cookies.
- **Youtube Shorts không thể tải được:** Trường hợp thường liên quan bị lỗi bảo mật phân quyền do Youtube triển khai gọi là `PO Token / GVS access`. Đây là giới hạn từ `yt-dlp` đang được tiếp tục phân tích, bạn có thể thử cấp Cookie cho phần mềm xử lý.

## Tuyên bố từ chối trách nhiệm
Công cụ được xây dựng nhằm hỗ trợ công việc tự động hoá theo kịch bản (automation-flow), không dùng để mở khoá nội dung mã hoá khoá luồng (DRM DRM-protected media). Người sử dụng hoàn toàn tự mình chịu các trách nhiệm liên đới với việc tuân thủ Điều khoản sử dụng & Bản quyền gốc ở mọi trang cung cấp video âm thanh cá nhân liên quan.
