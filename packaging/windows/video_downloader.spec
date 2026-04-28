# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for VideoDownloader (Windows onedir build)
# Run from repo root:  pyinstaller packaging/windows/video_downloader.spec --noconfirm --clean

import sys
from pathlib import Path

REPO_ROOT = Path(SPECPATH).resolve().parent.parent

block_cipher = None

# ---------------------------------------------------------------------------
# Collect hidden imports required by our modules
# ---------------------------------------------------------------------------
hidden_imports = [
    # Standard library extras
    "http.cookiejar",
    "xml.etree.ElementTree",
    "email.mime.multipart",
    "email.mime.text",
    # Google auth
    "google.auth",
    "google.auth.transport.requests",
    "google.oauth2",
    "google.oauth2.credentials",
    "google_auth_oauthlib",
    "google_auth_oauthlib.flow",
    # Browser cookie3 backends
    "browser_cookie3",
    # yt-dlp
    "yt_dlp",
    "yt_dlp.extractor",
    # curl_cffi
    "curl_cffi",
    "curl_cffi.requests",
    # Playwright
    "playwright",
    "playwright.sync_api",
    "playwright.async_api",
    # Websockets
    "websockets",
    "websockets.legacy",
    "websockets.legacy.server",
    # Requests
    "requests",
    "certifi",
    "brotli",
    # PyQt6
    "PyQt6",
    "PyQt6.QtWidgets",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    # App modules
    "downloader_app",
    "downloader_app.server",
    "downloader_app.jobs",
    "downloader_app.sheets",
    "downloader_app.platforms",
    "downloader_app.runtime",
    "downloader_app.desktop",
    "downloader_app.browser_session",
    "downloader_app.updater",
    "downloader_app.google_auth",
    "downloader_app.tts_manager",
    "downloader_app.tts_sheet",
    "downloader_app.elevenlabs_login",
    "downloader_app.launcher",
]

# ---------------------------------------------------------------------------
# Data files to bundle (src, dest relative to bundle root)
# ---------------------------------------------------------------------------
datas = [
    # Web frontend build output
    (str(REPO_ROOT / "web" / "dist"),           "web/dist"),
    # App icon
    (str(REPO_ROOT / "static"),                 "static"),
    # FFmpeg / FFprobe Windows binaries
    (str(REPO_ROOT / "vendor" / "windows" / "bin" / "ffmpeg.exe"),  "vendor/windows/bin"),
    (str(REPO_ROOT / "vendor" / "windows" / "bin" / "ffprobe.exe"), "vendor/windows/bin"),
]

for exiftool_name in ("exiftool.exe", "exiftool(-k).exe", "exiftool_k.exe"):
    exiftool_path = REPO_ROOT / "vendor" / "windows" / "bin" / exiftool_name
    if exiftool_path.exists():
        datas.append((str(exiftool_path), "vendor/windows/bin"))

a = Analysis(
    [str(REPO_ROOT / "main.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "test",
        "unittest",
        "pydoc",
        "doctest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # No console window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(REPO_ROOT / "static" / "app_icon.png"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VideoDownloader",
)
