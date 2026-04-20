from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] == "--run-yt-dlp":
        import yt_dlp

        yt_dlp.main(args[1:])
        return 0

    from downloader_app.server import run

    run()
    return 0
