from __future__ import annotations

import os
import socket
import sys
import io
from pathlib import Path


def _configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
                continue
            except Exception:
                pass
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            continue
        try:
            setattr(
                sys,
                stream_name,
                io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True),
            )
        except Exception:
            pass


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
    _configure_stdio()
    with open("launcher_debug.txt", "a", encoding="utf-8") as f:
        f.write(f"[LAUNCHER] sys.argv: {sys.argv}\n")
    full_argv = list(sys.argv if argv is None else [sys.argv[0], *argv])
    _prefer_project_python(full_argv)
    args = full_argv[1:]

    if args and args[0] == "--run-yt-dlp":
        import yt_dlp

        yt_dlp.main(args[1:])
        return 0

    if args and args[0] == "-c" and len(args) >= 2:
        # Handle python -c "script"
        script = args[1]
        # Modify sys.argv so the script sees the rest of the arguments
        sys.argv = ["-c"] + args[2:]
        exec(script, {"__name__": "__main__"})
        return 0

    if args and args[0] == "-m" and len(args) >= 2:
        module_name = args[1]
        sys.argv = args[1:]
        import runpy
        runpy.run_module(module_name, run_name="__main__", alter_sys=True)
        return 0

    # QtWebEngine spawns helper processes with --type=...
    # If we detect this, let QApplication handle it silently without creating a window.
    if any(a.startswith("--type=") for a in args):
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication(full_argv)
            app.setQuitOnLastWindowClosed(False)
            return app.exec()
        except ImportError:
            return 0

    import threading
    from downloader_app.server import run

    host = "127.0.0.1"
    port = 8765
    app_url = f"http://{host}:{port}"

    # --- Singleton guard ---
    # Probe the server port before starting. If it is already bound, another
    # instance of the app is already running.  In that case, attach a new
    # desktop window to the existing server instead of spawning a second
    # Python + HTTP-server process (which would raise an OSError anyway).
    _already_running = False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _probe:
        _probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            _probe.bind((host, port))
        except OSError:
            _already_running = True

    if _already_running:
        print(f"[launcher] Server already running at {app_url} - attaching new window.", flush=True)
        try:
            from downloader_app.desktop import run_desktop
            return run_desktop(app_url)
        except ImportError:
            import webbrowser
            webbrowser.open(app_url)
            return 0

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
