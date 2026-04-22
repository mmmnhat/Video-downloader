from __future__ import annotations

import os
import sys
from pathlib import Path


def _project_python() -> Path | None:
    project_root = Path(__file__).resolve().parent.parent
    candidates = [
        project_root / ".venv" / "bin" / "python",
        project_root / ".venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _prefer_project_python(argv: list[str]) -> None:
    project_python = _project_python()
    if project_python is None:
        return
    current_executable = Path(sys.executable).resolve()
    target_executable = project_python.resolve()
    if current_executable == target_executable:
        return
    os.execv(str(target_executable), [str(target_executable), *argv])


def main(argv: list[str] | None = None) -> int:
    full_argv = list(sys.argv if argv is None else [sys.argv[0], *argv])
    _prefer_project_python(full_argv)
    args = full_argv[1:]

    if args and args[0] == "--run-yt-dlp":
        import yt_dlp

        yt_dlp.main(args[1:])
        return 0

    import threading
    from downloader_app.server import run

    host = "127.0.0.1"
    port = 8765
    app_url = f"http://{host}:{port}"

    # Start server in a background thread
    server_thread = threading.Thread(
        target=run,
        kwargs={"host": host, "port": port},
        daemon=True
    )
    
    # Disable automatic browser opening by the server
    os.environ["VIDEO_DOWNLOADER_NO_BROWSER"] = "1"
    server_thread.start()

    try:
        from downloader_app.desktop import run_desktop
        return run_desktop(app_url)
    except ImportError:
        # Fallback to browser if PyQt6 is not installed
        print("PyQt6 khong tim thay. Dang mo trong trinh duyet...")
        import webbrowser
        webbrowser.open(app_url)
        # In fallback mode, the main thread needs to stay alive
        server_thread.join()
        return 0
