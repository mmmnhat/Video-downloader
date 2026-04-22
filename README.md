# Flowgen - Video Downloader & TTS Studio

Flowgen l├á mß╗Öt c├┤ng cß╗Ñ local mß║ính mß║╜ chß║íy tr├¬n m├íy c├í nh├ón vß╗¢i giao diß╗çn Web UI hiß╗çn ─æß║íi (React/Vite/Tailwind) ─æ╞░ß╗úc t├¡ch hß╗úp sß║╡n l├ám mß║╖c ─æß╗ïnh. Tool gi├║p bß║ín tß╗▒ ─æß╗Öng h├│a viß╗çc tß║úi video tß╗½ nhiß╗üu nß╗ün tß║úng v├á tß║ío giß╗ìng ─æß╗ìc AI (Text-to-Speech) h├áng loß║ít.

## T├¡nh n─âng ch├¡nh

### 1. Tr├¼nh tß║úi Video tß╗▒ ─æß╗Öng (Video Downloader)
- **Tß╗▒ ─æß╗Öng h├│a qua Google Sheets:** Chß╗ë cß║ºn d├ín link sheet chß╗⌐a danh s├ích URL video.
- **Tß╗▒ nhß║¡n diß╗çn nß╗ün tß║úng:** Hß╗ù trß╗ú tß║úi tß╗½ YouTube, Facebook, Instagram, TikTok, Pinterest, X, Reddit, Dumpert, v.v.
- **Xß╗¡ l├╜ t├¬n & cß║»t video (Auto-cut):**
  - ─Éß║╖t t├¬n file ─æß║ºu ra theo cß╗Öt `STT` trong sheet.
  - Tß╗▒ ─æß╗Öng cß║»t video theo cß╗Öt `Time` / `Thß╗¥i l╞░ß╗úng` (v├¡ dß╗Ñ: `00:52-01:04`).
  - Hß╗ù trß╗ú cß║»t th├ánh nhiß╗üu ─æoß║ín trong c├╣ng 1 video (v├¡ dß╗Ñ: `0.3-0.5, 0.10-0.12`).
- **Quß║ún l├╜ Download chß║╖t chß║╜:** 
  - L╞░u tß║Ñt cß║ú video v├áo chung mß╗Öt th╞░ mß╗Ñc, file ─æ╞░ß╗úc chuß║⌐n h├│a vß╗ü ─æß╗ïnh dß║íng MP4 H.264 dß╗à d├áng ch├¿n v├áo c├íc phß║ºn mß╗üm edit.
  - Theo d├╡i tiß║┐n tr├¼nh tß║úi realtime (batch tracker), Stop nhanh ─æoß║ín ─æang tß║úi, Retry c├íc task lß╗ùi. 
  - L╞░u trß║íng th├íi (state) nß╗Öi bß╗Ö ngay cß║ú khi tß║»t nguß╗ôn hay tß║úi lß║íi trang web.
  - C├│ thß╗â nß║íp cookies hoß║╖c ─æß╗ìc trß╗▒c tiß║┐p tß╗½ tr├¼nh duyß╗çt (Cß╗æc Cß╗æc, Chrome...) ─æß╗â tß║úi c├íc video Private bß╗ï kho├í.

### 2. Studio lß╗ông tiß║┐ng (TTS Studio) - Mß╗ÜI
- **T├¡ch hß╗úp s├óu ElevenLabs qua Playwright:** Cho ph├⌐p tr├¼nh giß║ú lß║¡p tr├¼nh duyß╗çt ─æ─âng nhß║¡p v├áo t├ái khoß║ún ElevenLabs gi├║p c├í nh├ón ho├í giß╗ìng ─æß╗ìc cß╗▒c nhanh m├á kh├┤ng v╞░ß╗¢ng c├íc hß║ín mß╗⌐c API th├┤ng th╞░ß╗¥ng. 
- **Thiß║┐t lß║¡p theo cß║Ñu h├¼nh:**
  - Hß╗ù trß╗ú nß║íp kß╗ïch bß║ún (Text) th├┤ng qua Google Sheets.
  - Chß╗ìn Giß╗ìng ─æß╗ìc (Voice) hoß║╖c chß╗ënh c├íc th├┤ng sß╗æ giß╗ìng n├│i trß╗▒c tiß║┐p tß╗½ Studio.
- **Xß╗¡ l├╜ h├áng loß║ít ├óm thanh:** Hß╗ç thß╗æng chß║íy ─æa luß╗ông ─æß╗â gß╗ìi tß║ío file ├óm thanh (TTS) cho to├án bß╗Ö sheet mß╗Öt c├ích tß╗▒ ─æß╗Öng v├á ß╗òn ─æß╗ïnh, xuß║Ñt thß║│ng ra th╞░ mß╗Ñc cß╗ºa bß║ín.

---

## Y├¬u cß║ºu hß╗ç thß╗æng

- Hß╗ç ─æiß╗üu h├ánh: Windows, macOS hoß║╖c Linux
- **Python 3.9+**
- `yt-dlp`
- `ffmpeg`, `ffprobe`
- (Tuß╗│ chß╗ìn) Node.js nß║┐u muß╗æn tß╗▒ build lß║íi giao diß╗çn Web UI.

Nß║┐u m├íy ch╞░a c├ái `yt-dlp`, h├úy chß║íy:
```bash
python3 -m pip install --user yt-dlp
```

## C├ái ─æß║╖t chi tiß║┐t

D╞░ß╗¢i ─æ├óy l├á tß╗½ng b╞░ß╗¢c c├ái ─æß║╖t cß╗Ñ thß╗â ─æß╗â khß╗ƒi chß║íy ß╗⌐ng dß╗Ñng tß╗½ m├ú nguß╗ôn gß╗æc:

**B╞░ß╗¢c 1: Tß║úi m├ú nguß╗ôn**
```bash
git clone https://github.com/mmmnhat/Video-downloader.git
cd Video-downloader
```

**B╞░ß╗¢c 2: Tß║ío v├á k├¡ch hoß║ít m├┤i tr╞░ß╗¥ng ß║úo (Virtual Environment)**
Viß╗çc n├áy gi├║p c├íc th╞░ viß╗çn cß╗ºa app kh├┤ng xung ─æß╗Öt vß╗¢i m├íy t├¡nh cß╗ºa bß║ín.
- **Tr├¬n Mac/Linux:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```
- **Tr├¬n Windows:**
  ```cmd
  python -m venv .venv
  .venv\Scripts\activate
  ```

**B╞░ß╗¢c 3: C├ái ─æß║╖t c├íc th╞░ viß╗çn l├╡i (Python Dependencies)**
```bash
pip install -r requirements.txt
```
*(Nß║┐u hß╗ç thß╗æng ch╞░a c├ái ─æ╞░ß╗úc `yt-dlp`, c├│ thß╗â chß║íy th├¬m lß╗çnh ─æß╗Öc lß║¡p: `pip install yt-dlp`)*

**B╞░ß╗¢c 4: C├ái ─æß║╖t tr├¼nh duyß╗çt tß╗▒ ─æß╗Öng (Playwright Browsers)**
V├¼ tr├¼nh **TTS Studio** cß║ºn tr├¼nh duyß╗çt ß║úo ─æß╗â lß║Ñy giß╗ìng n├│i tß╗½ ElevenLabs, bß║ín bß║»t buß╗Öc phß║úi cß║Ñp ph├⌐p c├ái Chromium giß║ú lß║¡p:
```bash
playwright install chromium
```

*(Giao diß╗çn web hiß╗çn ─æß║íi ─æ├ú ─æ╞░ß╗úc build t─⌐nh sß║╡n trong mß╗Ñc `web/dist`. Bß║ín ho├án to├án bß╗Å qua phß║ºn c├ái ─æß║╖t NPM/NodeJS trß╗½ phi c├│ nhu cß║ºu thay ─æß╗òi, lß║¡p tr├¼nh lß║íi UI l├║c ─æ├│ h├úy v├áo th╞░ mß╗Ñc `web` ─æß╗â `npm install` v├á `npm run build`.)*

## Sß╗¡ dß╗Ñng

Khß╗ƒi ─æß╗Öng ß╗⌐ng dß╗Ñng bß║▒ng terminal:
```bash
python3 main.py
```

ß╗¿ng dß╗Ñng sß║╜ chß║íy m├íy chß╗º FastAPI m╞░ß╗út m├á v├á tß╗▒ ─æß╗Öng mß╗ƒ giao diß╗çn Web UI hiß╗çn ─æß║íi hiß╗ân thß╗ï tr├¬n tr├¼nh duyß╗çt mß║╖c ─æß╗ïnh ß╗ƒ ─æß╗ïa chß╗ë:
```text
http://127.0.0.1:8765
```

Nß║┐u bß║ín ─æang chß║íy tool tr├¬n thiß║┐t bß╗ï cß║»m m├íy/server v├á **kh├┤ng muß╗æn** tool cß╗æ mß╗ƒ tr├¼nh duyß╗çt:
```bash
VIDEO_DOWNLOADER_NO_BROWSER=1 python3 main.py
```

---

## ─É├│ng g├│i chß║íy trß╗▒c tiß║┐p kh├┤ng cß║ºn c├ái ─æß║╖t (Windows Portable .exe)

Nß║┐u bß║ín muß╗æn tß║ío mß╗Öt bß║ún `.exe` di ─æß╗Öng mang ch├⌐p sang bß║Ñt kß╗│ m├íy t├¡nh Windows n├áo ─æß╗â d├╣ng m├á kh├┤ng cß║ºn c├ái m├ú nguß╗ôn hay Python:

1. Phß║úi chuß║⌐n bß╗ï mß╗Öt m├íy build chß║íy hß╗ç ─æiß╗üu h├ánh Windows v├á ─æ├ú c├ái Python 3.9+.
2. (Tuß╗│ chß╗ìn) C├│ Node.js ─æß╗â build frontend mß╗¢i nhß║Ñt.
3. Tß║úi v├á ch├⌐p file `ffmpeg.exe` / `ffprobe.exe` v├áo th╞░ mß╗Ñc `vendor/windows/bin/` trong source code n├áy.
4. Mß╗ƒ PowerShell trong th╞░ mß╗Ñc cß╗ºa Project v├á chß║íy:
```powershell
.\packaging\windows\build.ps1
```

Ho├án tß║Ñt, Script sß║╜ gß╗Öp nguy├¬n bß╗Ö source th├ánh mß╗Öt khß╗æi trong th╞░ mß╗Ñc `dist/VideoDownloader`. File gß╗¡i ─æi sß║╜ ─æß╗º mß╗ìi chß╗⌐c n─âng v├á m├íy ng╞░ß╗¥i nhß║¡n chß╗ë viß╗çc click khß╗ƒi chß║íy file `VideoDownloader.exe`.

---

## Khß║»c phß╗Ñc lß╗ùi th╞░ß╗¥ng gß║╖p / Th├ío gß╗í kh├│ kh─ân

- **Web tß╗½ chß╗æi/bß║»t Captcha chß║╖n tß║úi:** T├¡nh n─âng Auto-fallback qua lß╗¢p HTTP scraper ─æ╞░ß╗úc bß║¡t gi├║p tß║úi tß╗½ nhß╗»ng luß╗ông nh╞░ Threads/Dailymotion. Vß╗¢i video cß║ºn xem ─æ╞░ß╗úc mß╗¢i tß║úi ─æ╞░ß╗úc (Private Mode), bß║ín buß╗Öc phß║úi th├¬m Cookies v├áo mß╗Ñc c├ái ─æß║╖t tr├¬n m├án h├¼nh UI. App tß╗▒ bß║¡t c╞í chß║┐ mß║ío danh `--impersonate chrome` ─æß╗â qua mß║╖t Cloudflare chß║╖n web.
- **Trß║íng th├íi lß╗ïch sß╗¡ Download v├á TTS:** C├íc th├┤ng sß╗æ ─æ├ú tß║úi, cß║Ñu h├¼nh giß╗ìng ─æß╗üu ─æ╞░ß╗úc ß╗⌐ng dß╗Ñng tß╗▒ l╞░u ─æß╗çm ß╗ƒ nhß╗»ng tß╗çp `app_state.json` v├á `tts_state.json`. H├úy ─æß╗â nguy├¬n c├íc tß╗çp n├áy, ch├║ng l├á n╞íi l╞░u bß╗Ö nhß╗¢ hß╗ç thß╗æng.
- **Tß║úi TikTok bß╗ï thß║Ñt bß║íi:** M├íy chß╗º TikTok thß╗ënh thoß║úng update bß╗Ö m├íy chß║╖n thuß║¡t to├ín. Tool sß║╜ thay ─æß╗òi qua Mobile API nß╗Öi bß╗Ö, nh╞░ng ─æß╗æi vß╗¢i nhß╗»ng nß╗Öi dung kh├│, vui l├▓ng ß║Ñn n├║t Retry tß╗½ giao diß╗çn tracker hoß║╖c ch├¿n Cookies.
- **Youtube Shorts kh├┤ng thß╗â tß║úi ─æ╞░ß╗úc:** Tr╞░ß╗¥ng hß╗úp th╞░ß╗¥ng li├¬n quan bß╗ï lß╗ùi bß║úo mß║¡t ph├ón quyß╗ün do Youtube triß╗ân khai gß╗ìi l├á `PO Token / GVS access`. ─É├óy l├á giß╗¢i hß║ín tß╗½ `yt-dlp` ─æang ─æ╞░ß╗úc tiß║┐p tß╗Ñc ph├ón t├¡ch, bß║ín c├│ thß╗â thß╗¡ cß║Ñp Cookie cho phß║ºn mß╗üm xß╗¡ l├╜.

## Tuy├¬n bß╗æ tß╗½ chß╗æi tr├ích nhiß╗çm
C├┤ng cß╗Ñ ─æ╞░ß╗úc x├óy dß╗▒ng nhß║▒m hß╗ù trß╗ú c├┤ng viß╗çc tß╗▒ ─æß╗Öng ho├í theo kß╗ïch bß║ún (automation-flow), kh├┤ng d├╣ng ─æß╗â mß╗ƒ kho├í nß╗Öi dung m├ú ho├í kho├í luß╗ông (DRM DRM-protected media). Ng╞░ß╗¥i sß╗¡ dß╗Ñng ho├án to├án tß╗▒ m├¼nh chß╗ïu c├íc tr├ích nhiß╗çm li├¬n ─æß╗¢i vß╗¢i viß╗çc tu├ón thß╗º ─Éiß╗üu khoß║ún sß╗¡ dß╗Ñng & Bß║ún quyß╗ün gß╗æc ß╗ƒ mß╗ìi trang cung cß║Ñp video ├óm thanh c├í nh├ón li├¬n quan.
