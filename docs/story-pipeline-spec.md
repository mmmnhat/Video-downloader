# Story Pipeline Spec (Gemini Web Orchestrator)

## 1. Scope
Mục tiêu của module `story_pipeline` là hiện thực kiến trúc:

- `Video` chạy song song theo worker pool
- `Marker`/`Step` chạy tuần tự trong từng video
- `Attempt` phục vụ `regenerate` và `refine`
- `Preview + Normalize` là output chuẩn để chống sai ảnh do UI cache

Module này **không khóa chặt vào Gemini API**. Nó dùng adapter interface:
- `local_preview` (mock để dev scheduler/UI)
- `gemini_web` (Playwright + preview capture + normalize)

## 2. State Model

### 2.1 Video status
- `queued`: chờ worker
- `running`: worker đang xử lý
- `review`: đã sinh ảnh, chờ user quyết định
- `paused`: tạm dừng
- `completed`: hoàn tất
- `failed`: lỗi

### 2.2 Step status
- `queued`
- `running`
- `review`
- `completed`
- `skipped`
- `failed`

### 2.3 Attempt mode
- `auto`: lần gen đầu theo flow
- `regenerate`: thử lại cùng mục tiêu
- `refine`: dùng output attempt trước làm input mới

## 3. Prompt Merge
Prompt cuối được ghép đúng 4 tầng:

```text
Global Prompt
+ Video Prompt
+ Marker Seed Prompt
+ Step Modifier Prompt
```

Hàm thực thi: `_merge_prompt(video, marker, step)` trong `downloader_app/story_pipeline.py`.

## 4. Input Strategy

- `from_source`: mọi step dùng `marker.input_frame_path`
- `chain`: step > 1 ưu tiên output normalized của step trước (attempt đã accept)

Quy tắc resolve input nằm trong `_resolve_step_input_locked(...)`.

## 5. Output Strategy (Preview-first + Normalize)
Mỗi attempt ghi vào:

```text
<output_root>/<video_name>/marker_<idx>/step_<idx>/attempt_<idx>/
  preview.jpg
  normalized.jpg
```

- `preview.jpg`: ảnh hiển thị ngay cho user review
- `normalized.jpg`: bản chuẩn hóa để dùng cho refine/chain

Adapter mặc định (`LocalPreviewAdapter`) copy input -> preview -> normalized để mock behavior.

## 6. Queue & Scheduler

- Pool size: `settings.max_parallel_videos` (default 2)
- Mỗi worker nhận 1 `video_id` từ queue
- Khi gặp step ở `review`, worker dừng để chờ action người dùng
- Sau `accept/skip/regenerate/refine`, video được enqueue lại nếu còn việc

## 7. API Contract

### 7.1 Bootstrap
`GET /api/story/bootstrap`

Response:
- `settings`
- `globalPrompt`
- `videoSummaries`
- `activeVideoId`

### 7.2 Video list/detail
- `GET /api/story/videos`
- `GET /api/story/videos/{videoId}`

### 7.3 Settings & prompts
- `POST /api/story/settings`
- `POST /api/story/global-prompt`

Các key settings quan trọng:
- `generation_backend`: `local_preview | gemini_web`
- `gemini_headless`: `true/false`
- `gemini_base_url`
- `gemini_response_timeout_ms`
- `gemini_selector_debug`: bật chế độ dump debug selector khi lỗi
- `gemini_selector_debug_dir`: thư mục lưu artifacts (Windows path hỗ trợ, ví dụ `D:\\gemini-debug`)
  - nếu dùng path tương đối, app sẽ resolve theo `output_root`

### 7.3.1 Gemini session
- `GET /api/story/session/status?refresh=1`
- `POST /api/story/session/open-login`

### 7.4 Import manifest
`POST /api/story/videos/import`

Body:
- `manifest` (object) hoặc `manifest_path` (string)

Hỗ trợ cả:
- single video object
- object chứa `videos: []`

### 7.5 Controls
- `POST /api/story/videos/{videoId}/run`
- `POST /api/story/videos/{videoId}/pause`
- `POST /api/story/videos/{videoId}/resume`

### 7.6 Step actions
`POST /api/story/actions`

Body:
- `action`: `accept | regenerate | refine | skip | run | pause`
- `video_id`
- `marker_id` + `step_id` (bắt buộc cho action theo step)
- `attempt_id` (optional)

### 7.7 Live events
`GET /api/story/events` (SSE)

- heartbeat 15s
- event payload có `id`, `type`, `timestamp`

## 8. Manifest Schema (practical)

```json
{
  "video_name": "video_A",
  "video_path": "/path/video_A.mp4",
  "mode": "chain",
  "video_prompt": "same style as source",
  "markers": [
    {
      "name": "marker 001",
      "timestamp_ms": 12340,
      "input_frame": "/path/frames/marker_001.jpg",
      "seed_prompt": "character falls down",
      "steps": [
        {"title": "Step 1", "modifier_prompt": "fall then hiphop"},
        {"title": "Step 2", "modifier_prompt": "hiphop then spin"}
      ]
    }
  ]
}
```

## 9. Frontend-ready Types
Đã thêm typing/API wrappers vào:
- `web/src/lib/api.ts`

Nhóm type chính:
- `StorySettings`
- `StoryVideoSummary`
- `StoryVideoDetail`
- `StoryMarker`
- `StoryStep`
- `StoryAttempt`

## 10. Current Limitations
- Adapter Gemini dùng selector heuristic động (composer proximity + new preview scoring), vẫn cần tune theo biến động UI Gemini thực tế.
- Chưa có parser Adobe marker export trực tiếp (đang ở mức ingest manifest JSON chuẩn).
- UI 3 cột chưa dựng (backend/API đã sẵn).

## 11. Selector Debug Mode
Khi `gemini_selector_debug=true`, adapter sẽ tự động dump artifacts cho từng run khi fail:
- `*.jpg`: screenshot toàn trang tại stage lỗi
- `*.html`: source HTML snapshot
- `*.json`: heuristic report gồm prompt target, attachment candidates, preview candidates, DOM snippet

Mặc định artifacts lưu ở:
- `<output_root>/_gemini_debug/`

Nếu cần path riêng (đặc biệt trên Windows), set:
- `gemini_selector_debug_dir`

## 12. Next Implementation Order
1. Add frame extraction service (FFmpeg theo marker timestamp)
2. Build Story UI (3 columns + review actions + session controls)
3. Add import wizard (Premiere marker JSON/XMP -> manifest)
4. Tune Gemini selectors + add retry policy theo từng lỗi UI/network
