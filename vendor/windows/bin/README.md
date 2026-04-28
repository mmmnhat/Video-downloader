Place these Windows binaries in this folder before running `packaging/windows/build.ps1`:

- `ffmpeg.exe`
- `ffprobe.exe`
- `exiftool.exe` (optional but recommended for Premiere XMP marker import)

If you download ExifTool from the official Windows package and it is still named
`exiftool(-k).exe`, you can leave that filename as-is. The app now detects both
`exiftool.exe` and `exiftool(-k).exe`, and the Windows build will bundle either one.

The build script will copy them into `dist/VideoDownloader/bin/` so the packaged app can run on a clean Windows machine without requiring a separate FFmpeg install.
