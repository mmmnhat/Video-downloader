import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from downloader_app.runtime import APP_VERSION, GITHUB_REPO, app_root, is_frozen

class UpdateError(RuntimeError):
    pass

class UpdateManager:
    def __init__(self) -> None:
        pass

    def check_for_updates(self) -> dict:
        """Checks GitHub releases for an update."""
        if not GITHUB_REPO or GITHUB_REPO == "user/repo-placeholder":
            return {
                "updateAvailable": False,
                "currentVersion": APP_VERSION,
                "latestVersion": APP_VERSION,
                "releaseNotes": "",
                "downloadUrl": "",
                "isPlaceholder": True,
            }

        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Video-Downloader-Updater/1.0", "Accept": "application/vnd.github.v3+json"}
            )
            response = urllib.request.urlopen(req, timeout=10)
            data = json.loads(response.read().decode("utf-8"))
            
            latest_version = data.get("tag_name", "").lstrip("v")
            release_notes = data.get("body", "")
            
            # Find the correct asset for the platform
            download_url = ""
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                if sys.platform == "darwin" and "mac" in name and (name.endswith(".zip") or name.endswith(".dmg") or name.endswith(".tar.gz")):
                    download_url = asset.get("browser_download_url", "")
                    break
                elif sys.platform == "win32" and "win" in name and name.endswith(".zip"):
                    download_url = asset.get("browser_download_url", "")
                    break

            # Fallback if no platform specific name was found
            if not download_url:
                for asset in data.get("assets", []):
                    name = asset.get("name", "").lower()
                    if name.endswith(".zip"):
                        download_url = asset.get("browser_download_url", "")
                        break

            update_available = False
            # Very simple version split to check if latest > current
            try:
                curr_parts = [int(p) for p in APP_VERSION.split(".")]
                latest_parts = [int(p) for p in latest_version.split(".")]
                if latest_parts > curr_parts:
                    update_available = True
            except ValueError:
                # If versions aren't integers, just do string match fallback
                if latest_version != APP_VERSION:
                    update_available = True

            return {
                "updateAvailable": update_available and bool(download_url),
                "currentVersion": APP_VERSION,
                "latestVersion": f"v{latest_version}",
                "releaseNotes": release_notes,
                "downloadUrl": download_url,
                "isPlaceholder": False,
            }

        except urllib.error.HTTPError as e:
            if e.code == 404:
                # 404 usually means no releases have been created on this repository yet
                return {
                    "updateAvailable": False,
                    "currentVersion": APP_VERSION,
                    "latestVersion": APP_VERSION,
                    "releaseNotes": "No public releases found on GitHub yet.",
                    "downloadUrl": "",
                    "isPlaceholder": False,
                }
            if e.code == 403:
                return {
                    "updateAvailable": False,
                    "currentVersion": APP_VERSION,
                    "latestVersion": APP_VERSION,
                    "releaseNotes": "Cannot check for updates: GitHub API rate limit exceeded. Please try again later.",
                    "downloadUrl": "",
                    "isPlaceholder": False,
                }
            raise UpdateError(f"GitHub API returned error {e.code}: {e.reason}")
        except Exception as e:
            raise UpdateError(f"Failed to check for updates: {e}")

    def apply_update(self, download_url: str, progress_callback=None) -> bool:
        """Downloads the update zip, extracts it, and triggers the bat replacement."""
        if not is_frozen():
            raise UpdateError("Automatic applying updates is only supported when running the compiled App (.exe). You are running in Dev Mode, please download source directly.")

        if not download_url:
            raise UpdateError("No download URL provided.")

        if progress_callback:
            progress_callback(0, "Khởi tạo thư mục tạm...")

        temp_dir = Path(tempfile.gettempdir()) / "VD_Update"
        temp_dir.mkdir(parents=True, exist_ok=True)
        zip_path = temp_dir / "update.zip"
        extract_dir = temp_dir / "extracted"
        bat_path = temp_dir / "update_helper.bat"
        
        current_exe = Path(sys.executable).resolve()
        current_app_dir = current_exe.parent

        try:
            # Download the file with progress
            if progress_callback:
                progress_callback(5, "Đang tải bản cập nhật...")
            
            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "Video-Downloader-Updater/1.0"}
            )
            with urllib.request.urlopen(req, timeout=120) as response:
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                with open(zip_path, 'wb') as out_file:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            percent = 5 + int((downloaded / total_size) * 75) # 5% to 80%
                            progress_callback(percent, f"Đang tải: {downloaded/1024/1024:.1f}MB / {total_size/1024/1024:.1f}MB")
        except Exception as e:
            raise UpdateError(f"Failed to download update: {e}")

        try:
            if progress_callback:
                progress_callback(85, "Đang giải nén dữ liệu...")
            import zipfile
            if extract_dir.exists():
                shutil.rmtree(extract_dir, ignore_errors=True)
            extract_dir.mkdir(parents=True, exist_ok=True)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
                
            # Find the inner directory containing VideoDownloader.exe
            source_dir = extract_dir
            # Usually the zip contains a "VideoDownloader" folder at the root
            inner_dir = extract_dir / "VideoDownloader"
            if inner_dir.exists() and inner_dir.is_dir():
                source_dir = inner_dir
        except Exception as e:
            raise UpdateError(f"Failed to extract update zip: {e}")

        # Write bat script
        current_pid = os.getpid()
        bat_content = f"""@echo off
setlocal
set "SRC_DIR={str(source_dir)}"
set "DEST_DIR={str(current_app_dir)}"
set "EXE_PATH={str(current_exe)}"
set "PID={current_pid}"

echo Waiting for application to exit...
:wait_loop
tasklist /FI "PID eq %PID%" | find "%PID%" >nul
if not errorlevel 1 (
    timeout /t 1 >nul
    goto wait_loop
)

echo Copying updated files...
xcopy /Y /E /H /C /I "%SRC_DIR%\\*" "%DEST_DIR%\\"

echo Restarting...
start "" "%EXE_PATH%"

echo Cleaning up...
del "%~f0"
"""
        try:
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat_content)
        except Exception as e:
            raise UpdateError(f"Could not build update script: {e}")

        # Launch bat and exit immediately
        try:
            if progress_callback:
                progress_callback(100, "Đang khởi động lại ứng dụng...")
            
            # Use a simpler Popen for Windows to avoid WinError 87
            subprocess.Popen(
                ["cmd", "/c", str(bat_path)],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                shell=False
            )
            # Exit the current process so the .bat can replace the file
            os._exit(0)
        except Exception as e:
            raise UpdateError(f"Failed to launch update wrapper: {e}")

updater = UpdateManager()
