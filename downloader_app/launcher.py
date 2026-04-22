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

    from downloader_app.server import run

    run()
    return 0
