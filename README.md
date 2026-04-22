# Multi-Platform Video Downloader

Tool local chạy trên máy bạn để:

- Dán link Google Sheets chứa URL video
- Quét toàn bộ cell trong sheet
- Tự nhận diện nền tảng
- Đặt tên file theo `STT` trong bảng
- Auto-cut theo cột `Time` / `Thời lượng` nếu có range hợp lệ, hoặc fallback sheet cũ
- Tải tất cả video về một thư mục mẹ duy nhất
- Theo dõi batch, stop, retry failed, và giữ state sau khi reload app

## Platform đang hỗ trợ

- YouTube
- Facebook
- Instagram
- TikTok
- Pinterest
- Dumpert
- X
- Reddit

## Yêu cầu

- Python 3.9+
- `yt-dlp`
- `ffmpeg`
- `browser-cookie3`
- `curl-cffi`

Nếu máy chưa có `yt-dlp`, bạn có thể cài:

```bash
python3 -m pip install --user yt-dlp
```

## Cài dependency

```bash
pip3 install -r requirements.txt
```

## Chạy app

```bash
python3 main.py
```

App sẽ tự mở browser ở:

```text
http://127.0.0.1:8765
```

Nếu muốn tắt auto-open browser:

```bash
VIDEO_DOWNLOADER_NO_BROWSER=1 python3 main.py
```

## Đóng gói Windows

Có thể đóng gói theo kiểu gửi nguyên thư mục cho máy Windows khác, máy nhận chỉ cần mở
`VideoDownloader.exe`, không cần cài Python.

### Kết quả build

- Build ra thư mục `dist/VideoDownloader`
- Gửi nguyên thư mục này cho máy Windows
- Máy nhận chỉ cần double-click `VideoDownloader.exe`

### Chuẩn bị trên máy build Windows

1. Cài Python 3.9+.
2. Nếu muốn frontend mới nhất, cài thêm Node.js để chạy `npm run build` trong `web/`.
3. Chép `ffmpeg.exe` và `ffprobe.exe` vào `vendor/windows/bin/`.

### Build

Chạy PowerShell trên Windows:

```powershell
.\packaging\windows\build.ps1
```

Script sẽ:

- cài Python dependencies
- cài `pyinstaller`
- build `web/dist` nếu có `npm`
- tạo app bundle tại `dist/VideoDownloader`

### Lưu ý runtime của bản Windows

- App bundle tự mang theo Python runtime, nên máy nhận không cần cài dependency.
- `yt-dlp` được gọi nội bộ từ chính file app bundle.
- `ffmpeg` và `ffprobe` sẽ được lấy từ `dist/VideoDownloader/bin/`.
- `app_state.json`, `.google_token.json`, `google_oauth_client.json` sẽ nằm cạnh file `.exe` để dễ copy cả folder sang máy khác.

## Flow hiện tại

1. Đăng nhập Google trong browser local nếu sheet private.
2. Chọn hoặc nhập `Output Folder`.
3. Chọn `Quality`, `Threads Download`, `Retry`.
4. Nếu cần, dán `Cookies` theo format Netscape hoặc path tới file cookies.
5. Dán link Google Sheets và bấm `Scan & Download`.
6. Theo dõi batch trên dashboard, dùng `Stop`, `Retry Failed`, `Open Folder`.

## Ghi chú

- App ưu tiên lấy tên file từ cột `STT`. Nếu không tìm thấy cột này, app fallback theo thứ tự URL trong sheet.
- Nếu sheet có cột `Time`, `Thời lượng`, `Duration`... chứa range như `00:52-01:04`, `00:52-1:04`, hoặc `0.52-1.04`, app sẽ auto-cut video thành `00:51-01:05`.
- Với sheet cũ không có cột time riêng, app vẫn fallback đọc range ở ô đầu tiên hoặc ô chứa time range trong cùng dòng.
- Nếu một dòng có nhiều range phân tách bằng dấu phẩy, app sẽ tách thành nhiều clip từ cùng link. Ví dụ `STT = 2` với `0.3-0.5, 0.10-0.12` sẽ ra `2.1`, `2.2`.
- Video được gom trực tiếp vào thư mục mẹ bạn chọn, không tự tạo thư mục con theo platform/uploader.
- Video đầu ra mặc định sẽ được chuẩn hóa về MP4 H.264 để dễ dựng/cắt và tương thích hơn.
- Settings và lịch sử batch được lưu vào `app_state.json` để app nhớ sau khi reload.
- Nút `Choose Folder` dùng picker native trên macOS và fallback dialog trên Windows/Linux.
- Browser session hiện ưu tiên đọc cookie từ Cốc Cốc nếu có, sau đó mới fallback sang các Chromium browser khác.
- App sẽ cố gắng gộp browser cookies với cookies bạn nhập tay trước khi gọi `yt-dlp`.
- App tự bật `--impersonate chrome` khi `curl-cffi` có sẵn, giúp một số site như Dumpert ổn định hơn.
- Link Threads (`threads.net`, `threads.com`) sẽ thử extractor mặc định trước, rồi fallback sang HTML scraper để lấy direct MP4 khi có thể. Với post private hoặc trang bắt đăng nhập, hãy bật browser cookies và dùng account có quyền xem.
- Link Dailymotion sẽ thử extractor mặc định trước, rồi fallback sang request không impersonation hoặc direct metadata stream nếu cần.
- Một số YouTube Shorts hiện vẫn có thể fail do `PO token / GVS access` từ phía YouTube, ngay cả khi đã có cookies.
- Một số TikTok có thể fail do `yt-dlp` không còn tách được dữ liệu trang; app đã thử thêm mobile API fallback nhưng vẫn phụ thuộc extractor upstream.
- Tool này không xử lý nội dung DRM hoặc nội dung bạn không có quyền tải xuống.
