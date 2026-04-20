Place these Windows binaries in this folder before running `packaging/windows/build.ps1`:

- `ffmpeg.exe`
- `ffprobe.exe`

The build script will copy them into `dist/VideoDownloader/bin/` so the packaged app can run on a clean Windows machine without requiring a separate FFmpeg install.
