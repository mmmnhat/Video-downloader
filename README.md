# Flowgen - Video Downloader, Story Pipeline & TTS Studio

Flowgen là ứng dụng desktop/web local để tự động hóa quy trình sản xuất content:

- Tải video hàng loạt từ Google Sheets.
- Chạy pipeline tạo ảnh theo marker (Gemini Web qua Playwright, không cần API key Gemini).
- Tạo voiceover hàng loạt với TTS Studio.

Ứng dụng chạy backend Python tại local (`127.0.0.1:8765`), frontend React và có shell desktop PyQt6.

## Tính năng chính

### 1) Video Downloader
- Nhập nguồn từ Google Sheets.
- Theo dõi batch realtime qua SSE.
- Hỗ trợ nhiều nền tảng phổ biến (YouTube, TikTok, Facebook, Instagram, X, Reddit...).
- Có retry/cancel, quản lý cookies trình duyệt và mở thư mục output nhanh.

### 2) Story Pipeline (Gemini Web Adapter)
- Kiến trúc 3 cấp: `Video -> Marker -> Step/Attempt`.
- Scheduler chuẩn:
  - Video chạy song song theo worker pool.
  - Marker/Step chạy tuần tự trong từng video.
- Prompt merge 4 tầng:
  - `Global + Video + Seed + Step`.
- Hỗ trợ `accept`, `regenerate`, `refine`, `skip`.
- Có 2 mode chạy step:
  - `chain`: step sau ăn output step trước.
  - `from_source`: luôn bám frame nguồn.
- Realtime UI qua SSE `/api/story/events`.
- Có filter nhanh queue theo `RUN / REVIEW / QUEUE`.
- Có nút mở nhanh output folder trong cột trái.

### 3) GeminiWebAdapter (Playwright) - chống sai ảnh
- Tự động điều khiển Gemini web session đã login.
- Preview-first: lấy preview trên UI trước.
- Normalize output: chuẩn hóa ảnh local trước khi dùng tiếp.
- Giải quyết lỗi tải nhầm ảnh do DOM/cache/blob URL không đổi.
- Có debug selector mode để tune nhanh trên Windows:
  - Tự lưu screenshot.
  - Dump HTML snapshot.
  - Dump JSON heuristic/snippet khi fail.

### 4) TTS Studio
- Quản lý TTS batch từ Google Sheets.
- Theo dõi tiến độ, preview và xuất audio theo lô.

## Cấu trúc repo

```text
.
├── downloader_app/
│   ├── server.py                  # HTTP API + SSE
│   ├── launcher.py                # Entry chính (desktop + local server)
│   ├── story_pipeline.py          # State machine + scheduler Story
│   ├── gemini_web_adapter.py      # Playwright adapter cho Gemini Web
│   └── tts_manager.py
├── web/
│   ├── src/App.tsx
│   ├── src/components/StoryStudio.tsx
│   └── src/lib/api.ts
├── docs/story-pipeline-spec.md
├── tests/
└── main.py
```

## Yêu cầu hệ thống

- Python `3.9+`
- Node.js `18+` (khuyến nghị 20+)
- FFmpeg + FFprobe (để xử lý media)
- Chromium cho Playwright

## Cài đặt cho developer

```bash
git clone https://github.com/mmmnhat/Video-downloader.git
cd Video-downloader

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium

npm --prefix web install
npm --prefix web run build
```

## Chạy ứng dụng

### Cách 1: chạy app desktop (khuyến nghị)

```bash
python main.py
```

- App sẽ tự chạy local server và mở shell desktop PyQt6.
- Nếu thiếu PyQt6, launcher fallback sang mở trình duyệt.

### Cách 2: chạy server web local thuần

```bash
python -c "from downloader_app.server import run; run()"
```

Mở: `http://127.0.0.1:8765`

## Story Pipeline quickstart

### Bước 1: chuẩn bị manifest

Có thể import bằng `manifest` object hoặc `manifest_path` JSON.

Ví dụ tối giản:

```json
{
  "video_name": "dance_final",
  "video_path": "D:/projects/dance_final.mp4",
  "mode": "chain",
  "video_prompt": "stylized action sequence, keep character identity",
  "markers": [
    {
      "name": "M004",
      "timestamp_ms": 1250,
      "input_frame": "D:/projects/frames/M004.jpg",
      "seed_prompt": "character falls",
      "steps": [
        { "title": "Step 1", "modifier_prompt": "fall to hiphop move" },
        { "title": "Step 2", "modifier_prompt": "hiphop to spin" }
      ]
    }
  ]
}
```

### Bước 2: import và chạy

Trong tab **Story Pipeline**:

1. Import manifest.
2. Chọn video trong queue.
3. Run video.
4. Review theo từng step (`Accept / Regenerate / Refine / Skip`).

### Bước 3: dùng refine đúng cách

- `Regenerate`: thử lại cùng mục tiêu.
- `Refine`: dùng output chuẩn hóa của attempt trước làm input mới.

## Debug selector Gemini (Windows-friendly)

Khi DOM Gemini thay đổi hoặc selector fail, bật:

- `gemini_selector_debug = true`
- `gemini_selector_debug_dir = D:\\gemini-debug` (hoặc để trống để dùng mặc định)

Artifacts sẽ gồm:

- ảnh screenshot stage fail,
- snapshot HTML,
- JSON heuristic (candidate/composer/preview/snippet).

Mặc định nếu không set dir riêng: `<output_root>/_gemini_debug/`.

## API chính

### Story
- `GET /api/story/bootstrap`
- `GET /api/story/videos`
- `GET /api/story/videos/{videoId}`
- `POST /api/story/videos/import`
- `POST /api/story/videos/{videoId}/run`
- `POST /api/story/videos/{videoId}/pause`
- `POST /api/story/actions`
- `GET /api/story/session/status?refresh=1`
- `POST /api/story/session/open-login`
- `GET /api/story/events` (SSE)

### Downloader/TTS
- `GET /api/bootstrap`
- `GET /api/events` (SSE)
- `GET /api/tts/bootstrap`

## Test

```bash
# story pipeline tests
python -m pytest tests/test_story_pipeline.py

# tts related tests
python -m pytest tests/test_tts_sheet.py tests/test_tts_manager.py
```

## Troubleshooting nhanh

- Không thấy tab Story: build lại frontend `npm --prefix web run build`, sau đó hard refresh.
- SSE không cập nhật: kiểm tra endpoint `/api/story/events` có trả event `connected`.
- Lỗi login/session Gemini: dùng nút `Open Login`, login lại, rồi `refresh session status`.
- Lỗi tải nhầm ảnh: đảm bảo flow dùng `preview + normalized` thay vì tin nút download của Gemini.

## Tài liệu kỹ thuật

- Story pipeline spec: [`docs/story-pipeline-spec.md`](docs/story-pipeline-spec.md)

## Disclaimer

Công cụ phục vụ tự động hóa workflow nội bộ/cá nhân. Người dùng tự chịu trách nhiệm về bản quyền nội dung và điều khoản sử dụng của từng nền tảng.

## TTS updates (2026-04-25)

- Auto-scan danh sach `My Voice` khi tab TTS mo va phien ElevenLabs san sang.
- Auto-refresh `My Voice` theo chu ky va khi nguoi dung quay lai tab/cua so app.
- Chi cho phep tao batch bang voice thuoc `My Voice` cua phien hien tai.
- Co co che lam moi danh sach qua `GET /api/tts/voices?refresh=1`.
- Uu tien fetch full list qua ElevenLabs API/session; du lieu intercept chi dung fallback.
- Browser/profile cho TTS duoc chon theo profile co cookie ElevenLabs phu hop nhat.
- Runtime TTS profile now copies Chromium `Network/Cookies` to keep ElevenLabs login in Playwright session.
- Session status check now reads both `Network/Cookies` and legacy `Cookies`.

## Video download resilience updates (2026-04-25)

- Added post-download video integrity verification using `ffmpeg` decode check.
- If a file is corrupted, downloader now auto-attempts:
  1. MP4 remux (`-c copy`)
  2. Fallback re-encode (`libx264 + aac`)
- Re-encoded repair output is upscaled to 1080p with:
  `scale=-2:1080:flags=lanczos`
- Existing output files are also verified before skip; invalid files are re-downloaded.
