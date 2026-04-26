# Flowgen

Flowgen la ung dung local de xu ly 3 nhom viec trong cung mot giao dien:

- Tai video hang loat tu Google Sheets
- Chay Story Pipeline de tao anh theo marker
- Tao batch TTS tu Google Sheets

Ung dung gom backend Python, frontend React build san trong `web/dist`, va shell desktop PyQt6. Khi can, app co the fallback sang mo bang trinh duyet tai `http://127.0.0.1:8765`.

## Tinh nang chinh

### 1. Video Downloader

- Doc danh sach video tu Google Sheets
- Preview truoc khi chay batch
- Loc theo khoang STT
- Theo doi tien do qua SSE
- Mo nhanh thu muc output
- Co retry va kiem tra tinh toan ven file tai ve

### 2. Story Pipeline

- Quan ly theo cau truc `Video -> Marker -> Step -> Attempt`
- Chay worker pool theo video, giu thu tu tung marker/step
- Ho tro `accept`, `regenerate`, `refine`, `skip`
- Ho tro `chain` va `from_source`
- Dong bo realtime qua `/api/story/events`

### 3. TTS Studio

- Tao batch voiceover tu Google Sheets
- Preview truoc khi chay
- Loc theo khoang STT
- Doc danh sach `My Voice` cua phien hien tai
- Theo doi batch, nghe lai audio, mo output

## Kien truc tong quan

```text
.
├── downloader_app/
│   ├── launcher.py
│   ├── server.py
│   ├── jobs.py
│   ├── story_pipeline.py
│   ├── tts_manager.py
│   └── gemini_web_adapter.py
├── web/
│   ├── src/
│   └── dist/
├── docs/
├── static/
├── main.py
└── requirements.txt
```

## Yeu cau

- Python 3.9+
- Node.js 18+ (khuyen nghi 20+)
- Chromium cho Playwright
- FFmpeg / FFprobe

## Cai dat

```bash
git clone https://github.com/mmmnhat/Video-downloader.git
cd Video-downloader

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium

npm --prefix web install
npm --prefix web run build
```

Tren Windows:

```powershell
.venv\Scripts\activate
```

## Chay ung dung

### Chay desktop app

```bash
python main.py
```

Flowgen se:

- uu tien su dung Python trong `.venv` neu co
- khoi dong local server tai `127.0.0.1:8765`
- mo shell desktop PyQt6
- fallback sang trinh duyet neu thieu PyQt6

### Chay server web local

```bash
python -c "from downloader_app.server import run; run()"
```

Sau do mo:

- [http://127.0.0.1:8765](http://127.0.0.1:8765)

## Luong su dung nhanh

### Video Downloader

1. Dang nhap Google neu can
2. Dan URL Google Sheets
3. Chon `Ten kenh`, `Pham vi STT`, thu muc output
4. Bam `Xem truoc` hoac `Bat dau`

### Story Pipeline

1. Import manifest trong tab Story Pipeline
2. Chon video trong queue
3. Run video
4. Review tung step voi `Accept / Regenerate / Refine / Skip`

### TTS Studio

1. Mo session ElevenLabs
2. Dan URL Google Sheets
3. Chon `My Voice`
4. Dat `Ten kenh`, `Pham vi STT`
5. Preview hoac bat dau batch

## API noi bo

### Core

- `GET /api/bootstrap`
- `GET /api/events`
- `GET /api/settings`
- `POST /api/settings`

### Story Pipeline

- `GET /api/story/bootstrap`
- `GET /api/story/videos`
- `GET /api/story/videos/{videoId}`
- `POST /api/story/videos/import`
- `POST /api/story/videos/{videoId}/run`
- `POST /api/story/videos/{videoId}/pause`
- `POST /api/story/actions`
- `GET /api/story/events`

### TTS

- `GET /api/tts/bootstrap`
- `GET /api/tts/session/status`
- `GET /api/tts/voices`
- `GET /api/tts/batches`
- `GET /api/tts/batches/{batchId}`

## Thu muc runtime

Mot so thu muc se duoc tao va cap nhat trong qua trinh chay:

- `story_pipeline/`
- `tts_batches/`
- `tts_profiles/`

Khong nen dua du lieu runtime lon vao commit neu khong that su can thiet.

## Troubleshooting

- Neu giao dien khong cap nhat: chay lai `npm --prefix web run build`
- Neu Story Pipeline khong nhan session: mo lai login va refresh session
- Neu TTS khong thay `My Voice`: kiem tra phien ElevenLabs va refresh session
- Neu app desktop khong len cua so: kiem tra `PyQt6` va `PyQt6-WebEngine`
- Neu tai video loi: kiem tra `ffmpeg`, `ffprobe` va dung luong o dia

## Tai lieu lien quan

- [Story pipeline spec](docs/story-pipeline-spec.md)

## Luu y

Cong cu nay danh cho workflow ca nhan/noi bo. Nguoi dung tu chiu trach nhiem voi noi dung, quyen su dung, va dieu khoan cua cac nen tang duoc thao tac.
