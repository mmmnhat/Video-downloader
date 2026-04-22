from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR_ENV = "VIDEO_DOWNLOADER_BIN_DIR"

APP_VERSION = "1.0.1"
GITHUB_REPO = "mmmnhat/Video-downloader"

def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    if is_frozen():
        bundle_dir = getattr(sys, "_MEIPASS", None)
        if bundle_dir:
            return Path(bundle_dir)
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT


def app_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT


def bundled_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)


def app_path(*parts: str) -> Path:
    return app_root().joinpath(*parts)


def resolve_binary(name: str, env_var: str | None = None) -> str | None:
    suffix = ".exe" if sys.platform == "win32" else ""
    binary_name = name if suffix and name.lower().endswith(suffix) else f"{name}{suffix}"

    candidates: list[Path] = []

    if env_var:
        forced = os.environ.get(env_var)
        if forced:
            candidates.append(Path(forced).expanduser())

    extra_bin_dir = os.environ.get(BIN_DIR_ENV)
    if extra_bin_dir:
        candidates.append(Path(extra_bin_dir).expanduser() / binary_name)

    # Platform-specific vendor bin directory (e.g. vendor/windows/bin/).
    if sys.platform == "win32":
        platform_vendor = "windows"
    elif sys.platform == "darwin":
        platform_vendor = "mac"
    else:
        platform_vendor = "linux"

    for root in (app_root(), bundle_root()):
        candidates.append(root / "vendor" / platform_vendor / "bin" / binary_name)
        candidates.append(root / "bin" / binary_name)
        candidates.append(root / binary_name)


    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            return str(resolved)

    path_binary = shutil.which(binary_name) or shutil.which(name)
    if path_binary:
        return path_binary

    return None


# Global UI Bridge for thread-safe GUI interaction (e.g. from server to desktop)
_ui_bridge: object | None = None

def set_ui_bridge(bridge: object) -> None:
    global _ui_bridge
    _ui_bridge = bridge

def get_ui_bridge() -> object | None:
    return _ui_bridge
