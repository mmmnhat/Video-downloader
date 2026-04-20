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
            
            # Find the Windows executable asset
            download_url = ""
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                if name.endswith(".exe"):
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

        except Exception as e:
            raise UpdateError(f"Failed to check for updates: {e}")

    def apply_update(self, download_url: str) -> bool:
        """Downloads the update and triggers the bat replacement."""
        if not is_frozen():
            raise UpdateError("Automatic applying updates is only supported when running the compiled App (.exe). You are running in Dev Mode, please download source directly.")

        if not download_url:
            raise UpdateError("No download URL provided.")

        temp_dir = Path(tempfile.gettempdir()) / "VD_Update"
        temp_dir.mkdir(parents=True, exist_ok=True)
        new_exe_path = temp_dir / "VideoDownloader_update.exe"
        bat_path = temp_dir / "update_helper.bat"
        current_exe = Path(sys.executable).resolve()

        try:
            # Download the file
            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "Video-Downloader-Updater/1.0"}
            )
            with urllib.request.urlopen(req, timeout=30) as response, open(new_exe_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
        except Exception as e:
            raise UpdateError(f"Failed to download update: {e}")

        # Write bat script
        current_pid = os.getpid()
        bat_content = f"""@echo off
setlocal
set "NEW_EXE={str(new_exe_path)}"
set "OLD_EXE={str(current_exe)}"
set "PID={current_pid}"

echo Waiting for application to exit...
:wait_loop
tasklist /FI "PID eq %PID%" | find "%PID%" >nul
if not errorlevel 1 (
    timeout /t 1 >nul
    goto wait_loop
)

echo Replacing executable...
move /Y "%NEW_EXE%" "%OLD_EXE%"

echo Restarting...
start "" "%OLD_EXE%"

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
            subprocess.Popen(
                ["cmd", "/c", str(bat_path)],
                creationflags=subprocess.CREATE_NEW_CONSOLE | getattr(subprocess, 'DETACHED_PROCESS', 0x00000008),
                cwd=str(temp_dir)
            )
            os._exit(0)
        except Exception as e:
            raise UpdateError(f"Failed to launch update wrapper: {e}")

updater = UpdateManager()
