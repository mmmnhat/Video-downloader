from __future__ import annotations

import asyncio
import base64
import hashlib
import http.cookiejar
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from downloader_app.browser_config import browser_config_manager, resolve_feature_browser_profile
from downloader_app.runtime import app_path, resolve_binary


GEMINI_DEFAULT_URL = "https://gemini.google.com/app"
GEMINI_LOGIN_URL = "https://gemini.google.com/app"
GEMINI_GEMS_VIEW_URL = "https://gemini.google.com/gems/view"
GEMINI_AUTH_DOMAINS = ("gemini.google.com", "google.com", "accounts.google.com")
GEMINI_GEM_URL_MARKERS = ("/gem/", "/gems/", "/app/gems/")
GEMINI_GEM_URL_IGNORED_SUFFIXES = ("/view", "/list", "/manage", "/discover")
GEMINI_APP_GEM_RESERVED_IDS = {"download", "gems"}
GEMINI_MODEL_MODE_LABELS = {
    "gemini-1.5-flash": "Nhanh",
    "gemini-2.5-flash": "Nhanh",
    "gemini-2.5-flash-thinking": "Tư duy",
    "gemini-2.5-pro": "Pro",
    "gemini-1.5-pro": "Pro",
    "flash": "Nhanh",
    "fast": "Nhanh",
    "nhanh": "Nhanh",
    "thinking": "Tư duy",
    "tu-duy": "Tư duy",
    "tu duy": "Tư duy",
    "pro": "Pro",
}

PROFILE_ROOT_ITEMS = ("Local State",)
PROFILE_ITEMS = (
    "Cookies",
    "Network",
    "Local Storage",
    "Session Storage",
    "Preferences",
    "Secure Preferences",
    "Network Persistent State",
    "Web Data",
    "Account Web Data",
)
PROFILE_DIR_COOKIE_RELATIVE_PATHS = (
    Path("Cookies"),
    Path("Network") / "Cookies",
)
GEMINI_GEMS_ROOT_EXTRA_ITEMS = (
    "first_party_sets.db",
    "Variations",
    "Last Version",
)
GEMINI_GEMS_PROFILE_EXTRA_ITEMS = (
    "Account Web Data",
    "IndexedDB",
    "Sessions",
    "Service Worker",
    "SharedStorage",
    "Web Data",
    "WebStorage",
    "shared_proto_db",
)
GEMINI_GEMS_INDEXEDDB_KEYWORDS = (
    "gemini.google",
    "gemini_google",
    "opal.google",
    "gds.google",
    "accounts.google",
    "labs.google",
    "antigravity.google",
    "www.google.com",
)
GEMINI_STARTER_GEM_LABEL_MARKERS = (
    "bắt đầu cuộc trò chuyện mới với gem:",
    "start a new conversation with gem:",
)
VISIBLE_GEMINI_CLOSE_DELAY_MS = 0
GEMINI_SCAN_PROFILE_NAME = "Default"
GEMINI_DEDICATED_PROFILE_PATH = app_path("cache", "story_pipeline", "gem_scan_profile")

# Profile copy configuration
PROFILE_SKIP_DIRS = {
    "cache", "code cache", "gpucache", "media cache", "shadercache",
    "service worker/cachestorage", "service worker/scriptcache",
    "safe browsing", "grshadercache", "webstorage/quota_manager",
    "safe browsing network", "sessions",
    # Note: IndexedDB is NOT skipped here by default because Gemini depends on it for gems/history
}
PROFILE_SKIP_FILES = {
    "lock", "singleton-lock", "lockfile", "cookies-journal", "history-journal",
    "last session", "last tabs", "current session", "current tabs",
}


class SharedBrowserContext:
    """
    Quản lý MỘT cửa sổ trình duyệt (một persistent context) với N tabs song song.

    Khi max_tabs=8 và 8 worker threads cùng gọi acquire_page(), mỗi thread
    nhận một tab riêng trong cùng một cửa sổ browser — 8 tabs xử lý đồng thời.
    acquire_page() sẽ block nếu tất cả tabs đang bận, đến khi có tab rảnh.
    """

    def __init__(
        self,
        *,
        max_tabs: int,
        profile: "GeminiBrowserProfile",
        runtime_root: Path,
        headless: bool,
        base_url: str,
    ) -> None:
        self._max_tabs = max(1, int(max_tabs))
        self._profile = profile
        self._runtime_root = runtime_root
        self._headless = headless
        self._base_url = base_url

        self._lock = threading.Lock()
        # Semaphore giới hạn số tab đồng thời = max_tabs
        self._semaphore = threading.Semaphore(self._max_tabs)

        self._playwright = None
        self._context = None
        self._runtime_profile_path: Path | None = None
        self._pages: list[dict] = []  # [{id, page, in_use: bool}]
        self._started = False
        self._closed = False
        self._idle_timer: threading.Timer | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def acquire_page(self) -> tuple[str, object]:
        """
        Lấy một tab sẵn sàng. Block tối đa 10 phút nếu tất cả tabs đang bận.
        Luôn gọi release_page() hoặc close_page() sau khi dùng xong.
        Trả về (page_id, page).
        """
        current_thread_id = threading.get_ident()
        acquired = self._semaphore.acquire(timeout=600)
        if not acquired:
            raise GeminiWebError("Timeout 10 phút chờ tab trình duyệt rảnh.")

        self._ensure_started()

        with self._lock:
            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
            # Playwright sync objects bị ràng buộc với thread đã tạo ra chúng.
            # Chỉ tái sử dụng tab thuộc cùng worker thread để tránh lỗi greenlet.
            for item in self._pages:
                if (
                    not item["in_use"]
                    and item.get("owner_thread_id") == current_thread_id
                ):
                    item["in_use"] = True
                    return item["id"], item["page"]

            for item in self._pages:
                if not item["in_use"] and item.get("owner_thread_id") is None:
                    item["in_use"] = True
                    item["owner_thread_id"] = current_thread_id
                    return item["id"], item["page"]

            # Tạo tab mới
            if len(self._pages) >= self._max_tabs:
                self._semaphore.release()
                raise GeminiWebError(
                    "Khong co browser tab nao gan voi worker hien tai. "
                    "Hay giam so luong worker hoac khoi dong lai tien trinh Gemini."
                )
            if self._context is None:
                self._semaphore.release()
                raise GeminiWebError("Browser context đã bị đóng.")
            page = self._context.new_page()
            page.set_default_timeout(20_000)
            page_id = f"page-{uuid.uuid4().hex[:8]}"
            self._pages.append(
                {
                    "id": page_id,
                    "page": page,
                    "in_use": True,
                    "owner_thread_id": current_thread_id,
                }
            )
            return page_id, page

    def release_page(self, page_id: str) -> None:
        """Trả tab về pool, tab vẫn mở để user review."""
        with self._lock:
            for item in self._pages:
                if item["id"] == page_id:
                    item["in_use"] = False
                    break
        self._semaphore.release()

    def close_page(self, page_id: str) -> None:
        """Đóng và xóa một tab (dùng khi tab bị lỗi nặng)."""
        with self._lock:
            was_in_use = False
            for i, item in enumerate(self._pages):
                if item["id"] == page_id:
                    was_in_use = item["in_use"]
                    try:
                        item["page"].close()
                    except Exception:
                        pass
                    self._pages.pop(i)
                    break
            
            if was_in_use:
                self._semaphore.release()

            # Nếu không còn tab nào, đóng browser ngay lập tức (theo yêu cầu user: "tắt của sở")
            if not self._pages and not self._closed:
                self._shutdown_locked()

    def shutdown(self) -> None:
        """Đóng tất cả tabs, context và Playwright."""
        with self._lock:
            self._shutdown_locked()

    def _shutdown_locked(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None
        for item in self._pages:
            try:
                item["page"].close()
            except Exception:
                pass
        self._pages.clear()
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        if self._runtime_profile_path is not None:
            # Do NOT delete the selected dedicated profile to persist login
            if self._runtime_profile_path != self._profile.user_data_dir:
                shutil.rmtree(self._runtime_profile_path, ignore_errors=True)
            self._runtime_profile_path = None

    @property
    def is_closed(self) -> bool:
        return self._closed

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _ensure_started(self) -> None:
        with self._lock:
            if self._started:
                return
            if self._closed:
                raise GeminiWebError("SharedBrowserContext đã bị đóng.")
            self._start_locked()
            self._started = True

    def _start_locked(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise GeminiWebError(
                "Chưa cài Playwright. Hãy chạy `./.venv/bin/pip install playwright` "
                "và `./.venv/bin/python -m playwright install chromium`."
            ) from exc

        # Use the selected app-managed profile directly instead of copying from system browser
        self._runtime_profile_path = self._profile.user_data_dir
        self._runtime_profile_path.mkdir(parents=True, exist_ok=True)

        # Fix Playwright Asyncio conflict:
        # Playwright Sync API cannot run if an event loop is already active in the thread.
        try:
            import asyncio
            try:
                # Use a more robust check for a running loop
                try:
                    loop = asyncio.get_running_loop()
                    if loop.is_running():
                        # If we're here, there IS a running loop in this thread.
                        # We MUST use a different thread or use the Async API.
                        # Since we're in a Sync context, we try to set a new loop.
                        asyncio.set_event_loop(asyncio.new_event_loop())
                except RuntimeError:
                    # No running loop, but check if there's an initialized one
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.set_event_loop(asyncio.new_event_loop())
                        else:
                            # Not running, but exists. Some versions of Playwright still complain.
                            asyncio.set_event_loop(None)
                    except Exception:
                        pass
            except Exception:
                try:
                    asyncio.set_event_loop(asyncio.new_event_loop())
                except Exception:
                    pass
        except Exception:
            pass

        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            str(self._runtime_profile_path),
            headless=self._headless,
            accept_downloads=True,
            executable_path=str(self._profile.executable_path),
            args=[
                f"--profile-directory={self._profile.profile_name}",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-breakpad",
                "--disable-component-update",
                "--disable-domain-reliability",
                "--disable-features=IsolateOrigins,site-per-process,Translate,OptimizationHints,DialMediaRouteProvider",
                "--disable-ipc-flooding-protection",
                "--disable-renderer-backgrounding",
                "--force-color-profile=srgb",
                "--metrics-recording-only",
            ],
        )
        try:
            self._context.grant_permissions(
                ["clipboard-read", "clipboard-write"], origin=self._base_url
            )
        except Exception:
            pass
        # Cookies are persisted in dedicated profile
        # Dùng page mặc định làm tab đầu tiên
        first_page = self._context.pages[0] if self._context.pages else self._context.new_page()
        first_page.set_default_timeout(20_000)
        page_id = f"page-{uuid.uuid4().hex[:8]}"
        self._pages.append(
            {
                "id": page_id,
                "page": first_page,
                "in_use": False,
                "owner_thread_id": None,
            }
        )


class GeminiWebError(RuntimeError):
    pass


class GeminiWebAuthError(GeminiWebError):
    pass


@dataclass(frozen=True)
class GeminiBrowserCandidate:
    name: str
    app_path: Path
    executable_path: Path
    user_data_dir: Path


@dataclass(frozen=True)
class GeminiBrowserProfile:
    name: str
    app_path: Path
    executable_path: Path
    user_data_dir: Path
    profile_dir: Path

    @property
    def profile_name(self) -> str:
        return self.profile_dir.name


@dataclass
class GeminiSessionStatus:
    dependencies_ready: bool
    authenticated: bool
    browser: str | None
    profile_dir: str
    message: str


@dataclass
class GeminiGenerationResult:
    preview_path: str
    normalized_path: str
    thread_url: str | None = None
    response_text: str | None = None


@dataclass
class _PreviewCandidate:
    key: str
    locator: object
    score: float
    y_bottom: float
    src: str
    width: int
    height: int
    x: int
    y: int


def _resolve_macos_app_bundle(
    default_path: Path,
    *,
    bundle_ids: tuple[str, ...] = (),
    app_names: tuple[str, ...] = (),
) -> Path:
    if sys.platform != "darwin":
        return default_path

    direct_candidates = [
        default_path,
        Path("/Applications") / default_path.name,
        Path.home() / "Applications" / default_path.name,
    ]
    for candidate in direct_candidates:
        if candidate.exists():
            return candidate

    queries: list[str] = []
    for bundle_id in bundle_ids:
        queries.append(f"kMDItemCFBundleIdentifier == '{bundle_id}'")
    for app_name in (default_path.name, *app_names):
        queries.append(f'kMDItemFSName == "{app_name}"c')

    for query in queries:
        try:
            completed = subprocess.run(
                ["mdfind", query],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except Exception:
            continue

        for raw_line in completed.stdout.splitlines():
            candidate = Path(raw_line.strip())
            if candidate.suffix.lower() == ".app" and candidate.exists():
                return candidate

    return default_path


def _normalize_gem_url(raw_url: str) -> str | None:
    url = str(raw_url or "").strip()
    if not url:
        return None

    parsed = urlparse(url)
    if not parsed.scheme and not parsed.netloc:
        if not url.startswith("/"):
            url = f"/{url}"
        parsed = urlparse(f"https://gemini.google.com{url}")

    if (parsed.netloc or "gemini.google.com").lower() != "gemini.google.com":
        return None

    path = parsed.path.rstrip("/") or "/"
    lower_path = path.lower()
    if not any(marker in lower_path for marker in GEMINI_GEM_URL_MARKERS):
        return None

    if lower_path.startswith("/app/"):
        app_target = lower_path[len("/app/"):].strip("/")
        if not app_target or "/" in app_target or app_target in GEMINI_APP_GEM_RESERVED_IDS:
            return None
    if lower_path in {"/gems", "/app/gems"}:
        return None
    if any(lower_path.endswith(suffix) for suffix in GEMINI_GEM_URL_IGNORED_SUFFIXES):
        return None

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    normalized_query = urlencode(sorted(query_pairs))
    return urlunparse(("https", "gemini.google.com", path, "", normalized_query, ""))


def _fallback_gem_name(url: str) -> str:
    gem_id = url.rstrip("/").split("/")[-1].split("?")[0]
    short_id = gem_id[:10] if gem_id else "shared"
    return f"Gem {short_id}"


def _derive_custom_gem_name(raw_text: str, *, aria_label: str = "", title: str = "") -> str:
    for candidate in (str(aria_label or "").strip(), str(title or "").strip()):
        if candidate:
            return candidate

    lines = [part.strip() for part in str(raw_text or "").splitlines() if part.strip()]
    if not lines:
        return ""

    meaningful: list[str] = []
    for index, line in enumerate(lines):
        if index == 0 and len(line) <= 2 and len(lines) > 1:
            continue
        if re.fullmatch(r"(share|edit|more options)", line, flags=re.IGNORECASE):
            continue
        meaningful.append(line)

    return meaningful[0] if meaningful else lines[0]


def _normalize_gem_entries(raw_entries: list[dict] | None) -> list[dict]:
    deduped: dict[str, dict] = {}
    for entry in raw_entries or []:
        normalized_url = _normalize_gem_url(str(entry.get("url", "")))
        if not normalized_url:
            continue

        name = " ".join(str(entry.get("name", "")).split()).strip()
        if not name:
            name = _fallback_gem_name(normalized_url)

        candidate = {"name": name, "url": normalized_url}
        existing = deduped.get(normalized_url)
        if existing is None or len(candidate["name"]) > len(existing["name"]):
            deduped[normalized_url] = candidate

    return sorted(deduped.values(), key=lambda item: item["name"].lower())


def _build_candidates() -> list[GeminiBrowserCandidate]:
    candidates: list[GeminiBrowserCandidate] = []
    if sys.platform == "win32":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
        program_files = Path(os.environ.get("ProgramFiles", "C:\\Program Files"))
        program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"))

        for coc_path in (program_files, program_files_x86, local_app_data):
            candidates.append(
                GeminiBrowserCandidate(
                    name="CocCoc",
                    app_path=coc_path / "CocCoc/Browser/Application",
                    executable_path=coc_path / "CocCoc/Browser/Application/browser.exe",
                    user_data_dir=local_app_data / "CocCoc/Browser/User Data",
                )
            )

        chrome_paths = [
            (program_files / "Google/Chrome/Application", program_files / "Google/Chrome/Application/chrome.exe"),
            (program_files_x86 / "Google/Chrome/Application", program_files_x86 / "Google/Chrome/Application/chrome.exe"),
            (local_app_data / "Google/Chrome/Application", local_app_data / "Google/Chrome/Application/chrome.exe"),
        ]
        for app_path, exe_path in chrome_paths:
            candidates.append(
                GeminiBrowserCandidate(
                    name="Chrome",
                    app_path=app_path,
                    executable_path=exe_path,
                    user_data_dir=local_app_data / "Google/Chrome/User Data",
                )
            )

        edge_paths = [
            (program_files_x86 / "Microsoft/Edge/Application", program_files_x86 / "Microsoft/Edge/Application/msedge.exe"),
            (program_files / "Microsoft/Edge/Application", program_files / "Microsoft/Edge/Application/msedge.exe"),
        ]
        for app_path, exe_path in edge_paths:
            candidates.append(
                GeminiBrowserCandidate(
                    name="Edge",
                    app_path=app_path,
                    executable_path=exe_path,
                    user_data_dir=local_app_data / "Microsoft/Edge/User Data",
                )
            )
    else:
        mac_browser_specs = [
            {
                "name": "CocCoc",
                "default_app_path": Path("/Applications/CocCoc.app"),
                "executable_name": "CocCoc",
                "user_data_dir": Path.home() / "Library/Application Support/CocCoc/Browser",
                "bundle_ids": ("com.coccoc.Coccoc",),
                "app_names": ("Cốc Cốc.app",),
            },
            {
                "name": "Chrome",
                "default_app_path": Path("/Applications/Google Chrome.app"),
                "executable_name": "Google Chrome",
                "user_data_dir": Path.home() / "Library/Application Support/Google/Chrome",
                "bundle_ids": ("com.google.Chrome",),
                "app_names": (),
            },
            {
                "name": "Edge",
                "default_app_path": Path("/Applications/Microsoft Edge.app"),
                "executable_name": "Microsoft Edge",
                "user_data_dir": Path.home() / "Library/Application Support/Microsoft Edge",
                "bundle_ids": ("com.microsoft.edgemac",),
                "app_names": (),
            },
        ]
        for spec in mac_browser_specs:
            app_path = _resolve_macos_app_bundle(
                spec["default_app_path"],
                bundle_ids=spec["bundle_ids"],
                app_names=spec["app_names"],
            )
            candidates.append(
                GeminiBrowserCandidate(
                    name=spec["name"],
                    app_path=app_path,
                    executable_path=app_path / "Contents" / "MacOS" / spec["executable_name"],
                    user_data_dir=spec["user_data_dir"],
                )
            )

    return candidates


GEMINI_BROWSER_CANDIDATES = _build_candidates()


def _available_browser_candidates() -> list[GeminiBrowserCandidate]:
    return [
        candidate
        for candidate in GEMINI_BROWSER_CANDIDATES
        if candidate.app_path.exists() and candidate.executable_path.exists() and candidate.user_data_dir.exists()
    ]


def _installed_browser_candidates() -> list[GeminiBrowserCandidate]:
    return [
        candidate
        for candidate in GEMINI_BROWSER_CANDIDATES
        if candidate.app_path.exists() and candidate.executable_path.exists()
    ]


def _profile_only_browser_candidates() -> list[GeminiBrowserCandidate]:
    return [
        candidate
        for candidate in GEMINI_BROWSER_CANDIDATES
        if candidate.user_data_dir.exists()
        and (not candidate.app_path.exists() or not candidate.executable_path.exists())
    ]


def _resolve_browser_executable_path(browser_path: Path) -> Path:
    path = browser_path.expanduser()
    if not path.exists():
        raise GeminiWebError(f"Khong tim thay browser path: {path}")
    if path.is_file():
        return path

    candidate_names = (
        "chrome.exe",
        "msedge.exe",
        "browser.exe",
        "Google Chrome",
        "Microsoft Edge",
        "CocCoc",
    )
    for candidate_name in candidate_names:
        candidate = path / candidate_name
        if candidate.exists() and candidate.is_file():
            return candidate
    raise GeminiWebError(f"Browser path khong tro den file thuc thi hop le: {path}")


def _infer_browser_name(executable_path: Path) -> str:
    lowered = str(executable_path).lower()
    if "coccoc" in lowered:
        return "CocCoc"
    if "edge" in lowered or executable_path.stem.lower() == "msedge":
        return "Edge"
    if "chrome" in lowered:
        return "Chrome"
    stem = executable_path.stem.strip()
    return stem or "Chromium"


def _build_dedicated_profile(browser_name: str, executable_path: Path) -> GeminiBrowserProfile:
    user_data_dir = _gem_scan_user_data_dir()
    return GeminiBrowserProfile(
        name=browser_name,
        app_path=executable_path.parent,
        executable_path=executable_path,
        user_data_dir=user_data_dir,
        profile_dir=user_data_dir / GEMINI_SCAN_PROFILE_NAME,
    )


def _iter_profile_dirs(user_data_dir: Path) -> list[Path]:
    default_profile = user_data_dir / "Default"
    other_profiles = sorted(path for path in user_data_dir.glob("Profile *") if path.is_dir())
    guest_profile = user_data_dir / "Guest Profile"
    ordered = [default_profile, *other_profiles]
    if guest_profile.is_dir():
        ordered.append(guest_profile)
    return [path for path in ordered if path.is_dir()]


def _cookie_count_for_domains(cookie_path: Path, domains: tuple[str, ...]) -> int:
    if not cookie_path.exists():
        return 0

    temp_copy: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as handle:
            temp_copy = Path(handle.name)
        
        # Use our robust copy logic to handle locked files
        try:
            _robust_copy_file(cookie_path, temp_copy)
        except Exception as exc:
            if "Permission denied" in str(exc) or "[Errno 13]" in str(exc) or "[Errno 32]" in str(exc):
                print(f"[GeminiWebAdapter] KHÔNG THỂ lấy cookie vì trình duyệt đang mở. Vui lòng ĐÓNG CocCoc/Chrome rồi thử lại.", flush=True)
            raise

        clauses = []
        params: list[str] = []
        for domain in domains:
            clauses.append("host_key = ? OR host_key LIKE ?")
            params.append(domain)
            params.append(f"%.{domain}")
        where = " OR ".join(f"({clause})" for clause in clauses)

        connection = sqlite3.connect(temp_copy)
        try:
            row = connection.execute(
                f"SELECT COUNT(*) FROM cookies WHERE {where}",
                tuple(params),
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            connection.close()
    except Exception as exc:
        print(f"[GeminiWebAdapter] Failed to count cookies in {cookie_path}: {exc}", flush=True)
        return 0
    finally:
        if temp_copy is not None:
            try:
                temp_copy.unlink(missing_ok=True)
            except Exception:
                pass


def _cookie_paths_for_profile(profile_dir: Path) -> list[Path]:
    return [profile_dir / relative_path for relative_path in PROFILE_DIR_COOKIE_RELATIVE_PATHS]


def _choose_profile_dir(user_data_dir: Path, domains: tuple[str, ...]) -> Path | None:
    profile_dirs = _iter_profile_dirs(user_data_dir)
    if not profile_dirs:
        return None

    ranked: list[tuple[int, Path]] = []
    for profile_dir in profile_dirs:
        count = max(
            (_cookie_count_for_domains(cookie_path, domains) for cookie_path in _cookie_paths_for_profile(profile_dir)),
            default=0,
        )
        ranked.append((count, profile_dir))

    ranked.sort(key=lambda item: item[0], reverse=True)
    if ranked and ranked[0][0] > 0:
        return ranked[0][1]

    for profile_dir in profile_dirs:
        if profile_dir.name == "Default":
            return profile_dir
    return profile_dirs[0]


def detect_gemini_browser_profile(domains: tuple[str, ...] = GEMINI_AUTH_DOMAINS) -> GeminiBrowserProfile:
    _ = domains
    try:
        detected = resolve_feature_browser_profile("story")
    except Exception as exc:  # noqa: BLE001
        raise GeminiWebError(str(exc)) from exc
    return GeminiBrowserProfile(
        name=str(detected["browserName"]),
        app_path=Path(str(detected.get("appPath") or Path(str(detected["executablePath"])).parent)),
        executable_path=Path(str(detected["executablePath"])),
        user_data_dir=Path(str(detected["userDataDir"])),
        profile_dir=Path(str(detected["profileDir"])),
    )

def _robust_copy_file(source: Path, destination: Path) -> None:
    """Copies a file, retrying and using fallback streams, win32api, sqlite backup or cmd copy if locked on Windows."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    
    # 0. Skip known lock files that are guaranteed to be locked and useless
    if source.name.lower() in {"lock", "singleton-lock", "cookies-journal", "web data-journal"}:
        return

    # 1. Try standard copyfile first
    try:
        shutil.copyfile(source, destination)
        return
    except (PermissionError, OSError):
        pass

    # 2. For SQLite files (like Cookies), try sqlite3 backup API with nolock=1
    if source.name.lower() in {"cookies", "web data", "history", "login data"} or source.suffix.lower() == ".sqlite":
        try:
            # Use URI mode to bypass some locks
            src_path = str(source.absolute())
            if sys.platform == "win32":
                src_path = src_path.replace("\\", "/")
                if not src_path.startswith("/"):
                    src_path = "/" + src_path
            
            # nolock=1 and immutable=1 are key for reading locked SQLite files
            src_uri = f"file://{src_path}?mode=ro&nolock=1&immutable=1"
            
            src_conn = sqlite3.connect(src_uri, uri=True)
            try:
                dst_conn = sqlite3.connect(destination)
                try:
                    src_conn.backup(dst_conn)
                finally:
                    dst_conn.close()
            finally:
                src_conn.close()
            return
        except Exception:
            pass

    # 3. For Windows, try win32file with aggressive sharing flags
    if sys.platform == "win32":
        try:
            import win32file
            import win32con
            
            handle = win32file.CreateFile(
                str(source),
                win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
                None,
                win32con.OPEN_EXISTING,
                win32con.FILE_ATTRIBUTE_NORMAL,
                None
            )
            try:
                # We use open() for destination. If destination was created by NamedTemporaryFile, 
                # it might be locked on Windows, so we wrap this in try-except.
                with open(destination, "wb") as fdst:
                    while True:
                        res, data = win32file.ReadFile(handle, 1024 * 1024)
                        if not data:
                            break
                        fdst.write(data)
                return
            finally:
                handle.Close()
        except Exception:
            pass

    # 4. Try Windows shell copy
    if sys.platform == "win32":
        try:
            res = subprocess.run(
                ["cmd", "/c", "copy", "/y", str(source), str(destination)],
                capture_output=True,
                check=False,
                timeout=5
            )
            if res.returncode == 0 and destination.exists() and destination.stat().st_size > 0:
                return
        except Exception:
            pass

    # 5. Fallback to stream copy with retries
    for attempt in range(3):
        try:
            with open(source, "rb") as fsrc:
                with open(destination, "wb") as fdst:
                    shutil.copyfileobj(fsrc, fdst)
            return
        except (PermissionError, OSError) as exc:
            if attempt < 2:
                time.sleep(0.5)
                continue
            # If we've failed all robust methods AND all retries of simple stream copy,
            # then we finally log a warning for critical files.
            if source.name.lower() in {"cookies", "web data", "history"} or source.suffix.lower() == ".sqlite":
                if "Permission denied" in str(exc) or "[Errno 13]" in str(exc) or "[Errno 32]" in str(exc):
                    print(f"[GeminiWebAdapter] Warning: Can't read {source.name} (browser open). Trying to continue anyway.", flush=True)
            raise
        except Exception:
            if attempt < 2:
                time.sleep(0.5)
                continue
            raise


def _copy_profile_item(source: Path, destination: Path) -> None:
    if source.is_dir():
        # shutil.copytree with dirs_exist_ok=True is good, but we need to handle individual file errors
        if not destination.exists():
            destination.mkdir(parents=True, exist_ok=True)
        
        for child in source.iterdir():
            try:
                _copy_profile_item(child, destination / child.name)
            except Exception:
                # Non-critical profile files can be transiently locked.
                # Keep scan/runtime creation best-effort.
                pass
        return

    try:
        _robust_copy_file(source, destination)
    except FileNotFoundError:
        pass
    except Exception as exc:
        # Ignore errors for non-essential files
        if source.name.lower() in {"cookies-journal", "lock", "singleton-lock", "lockfile"} or source.suffix.lower() in {".tmp", ".temp"}:
            return

        # Re-raise only for critical items like Cookies/Local State.
        if source.name.lower() in {"cookies", "local state"}:
            raise


def _copy_filtered_directory(
    source: Path,
    destination: Path,
    *,
    include_predicate,
) -> None:
    if not source.exists() or not source.is_dir():
        return

    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        if include_predicate(child):
            _copy_profile_item(child, destination / child.name)


def _copy_gems_runtime_profile(profile: GeminiBrowserProfile, runtime_root: Path) -> None:
    for item in GEMINI_GEMS_ROOT_EXTRA_ITEMS:
        source = profile.user_data_dir / item
        if source.exists():
            _copy_profile_item(source, runtime_root / item)

    runtime_profile_dir = runtime_root / profile.profile_name
    for item in GEMINI_GEMS_PROFILE_EXTRA_ITEMS:
        source = profile.profile_dir / item
        destination = runtime_profile_dir / item
        if not source.exists():
            continue
        if item == "IndexedDB":
            _copy_filtered_directory(
                source,
                destination,
                include_predicate=lambda child: any(
                    keyword in child.name.lower() for keyword in GEMINI_GEMS_INDEXEDDB_KEYWORDS
                ),
            )
            continue
        if item == "Service Worker":
            _copy_filtered_directory(
                source,
                destination,
                include_predicate=lambda child: child.name in {"Database"},
            )
            continue
        _copy_profile_item(source, destination)


def _is_custom_gem_link(link: dict) -> bool:
    normalized_url = _normalize_gem_url(str(link.get("url", "")))
    if not normalized_url:
        return False

    combined = " ".join(
        [
            str(link.get("ariaLabel", "")).strip(),
            str(link.get("title", "")).strip(),
            str(link.get("text", "")).strip(),
        ]
    ).lower()
    return not any(marker in combined for marker in GEMINI_STARTER_GEM_LABEL_MARKERS)


def build_gemini_runtime_profile(
    profile: GeminiBrowserProfile,
    runtime_root: Path,
    runtime_id: str,
    *,
    copy_full_profile: bool = True, # Default to true as requested
) -> Path:
    path = runtime_root / runtime_id
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)

    # 1. Copy Local State (Root level)
    local_state = profile.user_data_dir / "Local State"
    if local_state.exists():
        _copy_profile_item(local_state, path / "Local State")

    # 2. Copy Profile directory (Recursive with exclusions)
    runtime_profile_dir = path / profile.profile_name
    
    if copy_full_profile:
        _copy_directory_recursive_filtered(
            profile.profile_dir,
            runtime_profile_dir,
            skip_dirs=PROFILE_SKIP_DIRS,
            skip_files=PROFILE_SKIP_FILES,
        )
    else:
        # Legacy/Selective mode
        runtime_profile_dir.mkdir(parents=True, exist_ok=True)
        for item in PROFILE_ITEMS:
            source = profile.profile_dir / item
            if source.exists():
                _copy_profile_item(source, runtime_profile_dir / item)

    return path


def _copy_directory_recursive_filtered(
    source: Path,
    destination: Path,
    *,
    skip_dirs: set[str],
    skip_files: set[str],
    current_rel_path: str = "",
) -> None:
    if not source.exists():
        return
    
    if not destination.exists():
        destination.mkdir(parents=True, exist_ok=True)

    for item in source.iterdir():
        rel_name = (f"{current_rel_path}/{item.name}" if current_rel_path else item.name).lower()
        
        if item.is_dir():
            if item.name.lower() in skip_dirs or rel_name in skip_dirs:
                continue
            _copy_directory_recursive_filtered(
                item,
                destination / item.name,
                skip_dirs=skip_dirs,
                skip_files=skip_files,
                current_rel_path=rel_name,
            )
        else:
            if item.name.lower() in skip_files or rel_name in skip_files:
                continue
            try:
                _copy_profile_item(item, destination / item.name)
            except Exception:
                pass


def _cookie_matches_domain(cookie_domain: str, domains: tuple[str, ...]) -> bool:
    normalized = cookie_domain.lstrip(".").lower()
    return any(normalized == domain or normalized.endswith(f".{domain}") for domain in domains)


def _load_browser_cookiejar(profile: GeminiBrowserProfile):
    try:
        import browser_cookie3
    except Exception as exc:  # noqa: BLE001
        raise GeminiWebError(
            f"Khong dong bo duoc cookie {profile.name} vao Gemini runtime: {exc}"
        ) from exc

    key_file = profile.user_data_dir / "Local State"
    if not key_file.exists():
        raise GeminiWebError(f"Khong tim thay Local State cho profile {profile.profile_name}.")

    combined = http.cookiejar.CookieJar()
    cookie_paths = [path for path in _cookie_paths_for_profile(profile.profile_dir) if path.exists()]
    if not cookie_paths:
        raise GeminiWebError(f"Khong tim thay cookie db cho profile {profile.profile_name}.")

    for cookie_path in cookie_paths:
        temp_cookie: Path | None = None
        temp_key: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as h1:
                temp_cookie = Path(h1.name)
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as h2:
                temp_key = Path(h2.name)

            _robust_copy_file(cookie_path, temp_cookie)
            _robust_copy_file(key_file, temp_key)

            if profile.name.lower() == "coccoc":
                extracted = None
                last_exc: Exception | None = None
                for crypt_name in ("coccoc", "chrome"):
                    try:
                        class CocCocProfile(browser_cookie3.ChromiumBased):
                            def __init__(self, c_file, k_file, d_name):
                                super().__init__(
                                    browser="CocCoc",
                                    cookie_file=str(c_file),
                                    domain_name=d_name,
                                    key_file=str(k_file),
                                    os_crypt_name=crypt_name,
                                    osx_key_service="CocCoc Safe Storage",
                                    osx_key_user="CocCoc",
                                )

                        extracted = CocCocProfile(temp_cookie, temp_key, "").load()
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                if extracted is None:
                    if last_exc is not None:
                        raise last_exc
                    continue
            else:
                loader_name = profile.name.lower()
                if loader_name == "chrome":
                    loader = browser_cookie3.chrome
                elif loader_name == "edge":
                    loader = browser_cookie3.edge
                else:
                    raise GeminiWebError(f"Khong ho tro dong bo cookie tu {profile.name}.")
                extracted = loader(cookie_file=str(temp_cookie), key_file=str(temp_key), domain_name="")

            for cookie in extracted:
                combined.set_cookie(cookie)
        except Exception as exc:
            print(
                f"[GeminiWebAdapter] Failed to load cookies from {cookie_path}: {exc}. "
                "This can happen with CocCoc app-bound cookie encryption.",
                flush=True,
            )
            continue
        finally:
            if temp_cookie:
                temp_cookie.unlink(missing_ok=True)
            if temp_key:
                temp_key.unlink(missing_ok=True)

    return combined


def _build_playwright_cookies(profile: GeminiBrowserProfile, domains: tuple[str, ...]) -> list[dict]:
    cookiejar = _load_browser_cookiejar(profile)
    deduped: dict[tuple[str, str, str], dict] = {}
    for cookie in cookiejar:
        if not _cookie_matches_domain(cookie.domain or "", domains):
            continue

        payload = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path or "/",
            "httpOnly": bool(
                getattr(cookie, "has_nonstandard_attr", lambda *_: False)("HttpOnly")
            ),
            "secure": bool(cookie.secure),
        }
        if cookie.expires:
            payload["expires"] = float(cookie.expires)

        deduped[(payload["domain"], payload["path"], payload["name"])] = payload

    return list(deduped.values())


def _build_playwright_cookies_from_browser_session(domains: tuple[str, ...]) -> list[dict]:
    try:
        from downloader_app.browser_session import browser_session
        _browser_name, domain_cookies = browser_session.get_domain_cookies(list(domains))
    except Exception as exc:  # noqa: BLE001
        print(f"[GeminiWebAdapter] Browser-session cookie fallback failed: {exc}", flush=True)
        return []

    deduped: dict[tuple[str, str, str], dict] = {}
    for cookie in domain_cookies:
        domain = str(cookie.domain or "")
        name = str(cookie.name or "")
        value = str(cookie.value or "")
        if not domain or not name:
            continue

        payload = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": str(cookie.path or "/"),
            "httpOnly": bool(
                getattr(cookie, "has_nonstandard_attr", lambda *_: False)("HttpOnly")
            ),
            "secure": bool(cookie.secure),
        }
        if cookie.expires:
            payload["expires"] = float(cookie.expires)

        deduped[(payload["domain"], payload["path"], payload["name"])] = payload

    return list(deduped.values())


def _gem_scan_user_data_dir() -> Path:
    profile = detect_gemini_browser_profile()
    profile.user_data_dir.mkdir(parents=True, exist_ok=True)
    return profile.user_data_dir


def _launch_browser_detached(executable: Path, args: list[str]) -> None:
    popen_kwargs: dict[str, object] = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    subprocess.Popen([str(executable), *args], **popen_kwargs)


def _sync_browser_cookies_to_context(context, profile: GeminiBrowserProfile) -> int:
    configured = browser_config_manager.get_feature("story")
    strict_profile = bool(str(configured.profile_name or "").strip())

    cookies = _build_playwright_cookies(profile, GEMINI_AUTH_DOMAINS)
    if not cookies:
        cookies = _build_playwright_cookies_from_browser_session(GEMINI_AUTH_DOMAINS)
        if cookies and strict_profile:
            print(
                "[GeminiWebAdapter] Using live browser-session cookies because the configured "
                "Story profile cookie DB is locked or unreadable.",
                flush=True,
            )
    if not cookies:
        return 0
    context.add_cookies(cookies)
    return len(cookies)


def open_gemini_login_window() -> dict:
    profile = detect_gemini_browser_profile()
    user_data_dir = _gem_scan_user_data_dir()
    try:
        _launch_browser_detached(
            profile.executable_path,
            [
                f"--user-data-dir={user_data_dir}",
                f"--profile-directory={profile.profile_name}",
                "--new-window",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                GEMINI_LOGIN_URL,
            ],
        )
    except Exception as exc:  # noqa: BLE001
        raise GeminiWebError(f"Khong mo duoc cua so Gemini login: {exc}") from exc

    return {
        "opened": True,
        "url": GEMINI_LOGIN_URL,
        "browser": profile.name,
        "profileDir": str(profile.profile_dir),
        "message": (
            f"Da mo Gemini bang profile rieng cua app tren {profile.name}. "
            "Dang nhap xong, dong cua so vua mo roi quay lai app bam Lam moi phien."
        ),
    }


def _dependencies_ready() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False
    return True


def check_gemini_session(*, headless: bool, base_url: str, runtime_root: Path) -> GeminiSessionStatus:
    _ = (headless, base_url, runtime_root)  # keep signature compatibility for callers
    try:
        profile = detect_gemini_browser_profile()
    except GeminiWebError as exc:
        return GeminiSessionStatus(
            dependencies_ready=False,
            authenticated=False,
            browser=None,
            profile_dir="",
            message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return GeminiSessionStatus(
            dependencies_ready=False,
            authenticated=False,
            browser=None,
            profile_dir="",
            message=str(exc),
        )

    cookie_count = max(
        (
            _cookie_count_for_domains(cookie_path, GEMINI_AUTH_DOMAINS)
            for cookie_path in _cookie_paths_for_profile(profile.profile_dir)
        ),
        default=0,
    )
    if cookie_count > 0:
        return GeminiSessionStatus(
            dependencies_ready=True,
            authenticated=True,
            browser=profile.name,
            profile_dir=str(profile.profile_dir),
            message=f"Da san sang voi profile Gemini rieng cua app tren {profile.name}.",
        )
    return GeminiSessionStatus(
        dependencies_ready=True,
        authenticated=False,
        browser=profile.name,
        profile_dir=str(profile.profile_dir),
        message=(
            "Chua tim thay session Gemini trong profile rieng cua app. "
            "Hay bam Login, dang nhap 1 lan, roi quay lai app bam Lam moi phien."
        ),
    )


def _looks_like_login_page(url: str) -> bool:
    lowered = url.lower()
    return (
        "accounts.google.com" in lowered
        or "signin" in lowered
        or "service=gemini" in lowered
        or "challenge" in lowered
    )


class GeminiWebAdapter:
    """Playwright adapter for Gemini web image generation.

    This adapter prefers downloading the underlying generated image bytes and
    only falls back to screenshot capture when Gemini does not expose a usable
    image source.
    """

    def __init__(
        self,
        *,
        runtime_root: Path,
        headless: bool = False,
        base_url: str = GEMINI_DEFAULT_URL,
        response_timeout_ms: int = 120_000,
        model_name: str = "gemini-2.5-flash",
        debug_selector: bool = False,
        debug_root: Path | None = None,
        max_tabs: int = 1,
    ) -> None:
        self._runtime_root = runtime_root
        self._headless = headless
        self._base_url = base_url
        self._response_timeout_ms = max(20_000, int(response_timeout_ms))
        self._model_name = str(model_name or "").strip() or "gemini-2.5-flash"
        self._debug_selector = bool(debug_selector)
        self._debug_root = Path(debug_root) if debug_root is not None else runtime_root / "_selector_debug"
        self._ffmpeg_path = resolve_binary("ffmpeg")
        self._ffprobe_path = resolve_binary("ffprobe")
        self._max_tabs = max(1, int(max_tabs))
        self._context_lock = threading.Lock()
        self._thread_contexts: dict[int, SharedBrowserContext] = {}

    def generate(
        self,
        *,
        prompt: str,
        input_image_path: Path,
        preview_path: Path,
        normalized_path: Path,
        context: dict,
    ):
        action_mode = self._normalize_ui_text(str(context.get("mode", "auto")))
        target_thread_url = self._sanitize_thread_url(context.get("threadUrl"))
        is_refine_followup = action_mode == "refine" and bool(target_thread_url)
        is_retry_followup = action_mode in {"regenerate", "retry"} and bool(target_thread_url)

        if not input_image_path.exists():
            raise GeminiWebError(f"Khong tim thay input image: {input_image_path}")

        try:
            from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
        except ImportError as exc:  # pragma: no cover
            raise GeminiWebError(
                "Chua cai Playwright. Hay chay `./.venv/bin/pip install -r requirements.txt` "
                "va `./.venv/bin/python -m playwright install chromium`."
            ) from exc

        shared = self._get_or_create_thread_context()
        page_id, page = shared.acquire_page()
        debug_run_dir = self._prepare_debug_run(context) if self._debug_selector else None

        stage = "init"
        baseline_keys: set[str] = set()
        page_had_error = False
        try:
            stage = "workspace_ready"
            self._ensure_workspace_ready(page, target_url=target_thread_url)
            stage = "select_image_tool"
            self._ensure_image_tool_selected(page)
            stage = "select_mode"
            self._apply_generation_mode(page)
            self._dump_debug_state(
                page,
                debug_run_dir=debug_run_dir,
                stage="workspace_ready",
                context=context,
                prompt=prompt,
                baseline_keys=None,
            )
            stage = "collect_baseline"
            baseline_keys = self._collect_candidate_keys(page)
            self._dump_debug_state(
                page,
                debug_run_dir=debug_run_dir,
                stage="baseline_preview",
                context=context,
                prompt=prompt,
                baseline_keys=baseline_keys,
            )

            if is_retry_followup:
                stage = "retry_response"
                if not self._click_retry_action_for_latest_response(page):
                    raise GeminiWebError("Khong tim thay nut retry/regenerate trong thread Gemini hien tai.")
                self._dump_debug_state(
                    page,
                    debug_run_dir=debug_run_dir,
                    stage="retry_response",
                    context=context,
                    prompt=prompt,
                    baseline_keys=baseline_keys,
                )
            else:
                stage = "upload_input"
                self._upload_input_image(page, input_image_path)
                self._dump_debug_state(
                    page,
                    debug_run_dir=debug_run_dir,
                    stage="upload_input",
                    context=context,
                    prompt=prompt,
                    baseline_keys=None,
                )
                stage = "collect_baseline_after_upload"
                baseline_keys = self._collect_candidate_keys(page)

                stage = "submit_prompt"
                self._submit_prompt(page, prompt)
                self._dump_debug_state(
                    page,
                    debug_run_dir=debug_run_dir,
                    stage="submit_prompt",
                    context=context,
                    prompt=prompt,
                    baseline_keys=baseline_keys,
                )

            stage = "wait_preview"
            candidate = self._wait_for_new_preview(page, baseline_keys)
            self._dump_debug_state(
                page,
                debug_run_dir=debug_run_dir,
                stage="preview_detected",
                context=context,
                prompt=prompt,
                baseline_keys=baseline_keys,
                selected_candidate=candidate,
            )

            preview_path.parent.mkdir(parents=True, exist_ok=True)
            stage = "capture_preview"
            resolved_preview_path = self._capture_preview(page, candidate, preview_path)
            resolved_normalized_path = self._normalize_preview(resolved_preview_path, normalized_path)
            self._dump_debug_state(
                page,
                debug_run_dir=debug_run_dir,
                stage="normalized_output",
                context=context,
                prompt=prompt,
                baseline_keys=baseline_keys,
                selected_candidate=candidate,
            )

            stage = "extract_response_text"
            response_text = self._extract_gemini_response_text(page)

            return GeminiGenerationResult(
                preview_path=str(resolved_preview_path),
                normalized_path=str(resolved_normalized_path),
                thread_url=self._sanitize_thread_url(page.url),
                response_text=response_text,
            )
        except Exception as exc:
            page_had_error = True
            self._dump_debug_failure(
                page,
                debug_run_dir=debug_run_dir,
                stage=stage,
                context=context,
                prompt=prompt,
                baseline_keys=baseline_keys or None,
                error=exc,
            )
            if isinstance(exc, PlaywrightTimeoutError):
                raise GeminiWebError("Het thoi gian cho Gemini tra ve image preview.") from exc
            if isinstance(exc, PlaywrightError):
                raise GeminiWebError(str(exc)) from exc
            if isinstance(exc, GeminiWebError):
                raise
            raise GeminiWebError(str(exc)) from exc
        finally:
            # Luôn đóng tab sau khi hoàn thành để giải phóng tài nguyên
            shared.close_page(page_id)

    def shutdown(self) -> None:
        """Hủy bỏ browser contexts của mọi worker thread."""
        with self._context_lock:
            for shared in self._thread_contexts.values():
                try:
                    shared.shutdown()
                except Exception:
                    pass
            self._thread_contexts.clear()

    def _get_or_create_thread_context(self) -> SharedBrowserContext:
        """Mỗi worker thread dùng context Playwright riêng để tránh lỗi greenlet/thread affinity."""
        current_thread_id = threading.get_ident()
        with self._context_lock:
            shared = self._thread_contexts.get(current_thread_id)
            if shared is None or shared.is_closed:
                profile = detect_gemini_browser_profile()
                shared = SharedBrowserContext(
                    max_tabs=1,
                    profile=profile,
                    runtime_root=self._runtime_root,
                    headless=self._headless,
                    base_url=self._base_url,
                )
                self._thread_contexts[current_thread_id] = shared
            return shared

    def _prepare_debug_run(self, context: dict) -> Path:
        self._debug_root.mkdir(parents=True, exist_ok=True)
        run_name_parts = [
            str(context.get("videoId", "")).strip(),
            str(context.get("markerId", "")).strip(),
            str(context.get("stepId", "")).strip(),
            str(context.get("attemptId", "")).strip(),
        ]
        run_name = "-".join(part for part in run_name_parts if part) or "run"
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        debug_run_dir = self._debug_root / f"{timestamp}_{run_name}_{uuid.uuid4().hex[:6]}"
        debug_run_dir.mkdir(parents=True, exist_ok=True)
        return debug_run_dir

    def _dump_debug_failure(
        self,
        page,
        *,
        debug_run_dir: Path | None,
        stage: str,
        context: dict,
        prompt: str,
        baseline_keys: set[str] | None,
        error: Exception,
    ) -> None:
        if debug_run_dir is None:
            return

        try:
            self._dump_debug_state(
                page,
                debug_run_dir=debug_run_dir,
                stage=f"{stage}_failed",
                context=context,
                prompt=prompt,
                baseline_keys=baseline_keys,
                error=f"{error.__class__.__name__}: {error}",
            )
        except Exception:
            # Debug mode must never mask the original pipeline error.
            pass

    def _dump_debug_state(
        self,
        page,
        *,
        debug_run_dir: Path | None,
        stage: str,
        context: dict,
        prompt: str,
        baseline_keys: set[str] | None,
        selected_candidate: _PreviewCandidate | None = None,
        error: str | None = None,
    ) -> None:
        if debug_run_dir is None:
            return

        try:
            state: dict[str, object] = {
                "stage": stage,
                "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "context": context,
                "promptLength": len(prompt),
                "baselineKeyCount": len(baseline_keys) if baseline_keys is not None else None,
                "error": error,
                "configuredGeminiModel": self._model_name,
                "configuredGeminiMode": self._resolve_generation_mode_label(),
            }

            if page is None:
                state["note"] = "Page object not available."
                self._write_debug_json(debug_run_dir / f"{stage}.json", state)
                return

            try:
                state["url"] = page.url
            except Exception:
                state["url"] = None
            try:
                state["title"] = page.title()
            except Exception:
                state["title"] = None

            try:
                prompt_target = self._find_prompt_target(page)
            except Exception:
                prompt_target = None
            try:
                attachment_candidates = self._find_attachment_buttons(page, prompt_target)
            except Exception:
                attachment_candidates = []
            try:
                preview_candidates = self._collect_preview_candidates(page)
            except Exception:
                preview_candidates = []
            new_preview_candidates = (
                [candidate for candidate in preview_candidates if candidate.key not in baseline_keys]
                if baseline_keys is not None
                else preview_candidates
            )

            state["promptTarget"] = self._describe_locator(prompt_target)
            state["attachmentCandidates"] = [
                self._describe_locator(candidate)
                for candidate in attachment_candidates[:12]
            ]
            state["previewCandidatesTop"] = [
                self._candidate_to_dict(candidate)
                for candidate in preview_candidates[-20:]
            ]
            state["newPreviewCandidatesTop"] = [
                self._candidate_to_dict(candidate)
                for candidate in new_preview_candidates[-20:]
            ]
            if selected_candidate is not None:
                state["selectedCandidate"] = self._candidate_to_dict(selected_candidate)

            snippet = self._collect_dom_snippet(page)
            if snippet:
                state["domSnippet"] = snippet

            html_file = debug_run_dir / f"{stage}.html"
            state["screenshotPath"] = None
            try:
                html_file.write_text(page.content(), encoding="utf-8")
                state["htmlPath"] = str(html_file)
            except Exception:
                state["htmlPath"] = None

            self._write_debug_json(debug_run_dir / f"{stage}.json", state)
        except Exception:
            # Best-effort dump only.
            pass

    def _write_debug_json(self, path: Path, payload: dict) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _describe_locator(self, locator) -> dict | None:
        if locator is None:
            return None
        try:
            if not locator.is_visible():
                return {"visible": False}
            box = locator.bounding_box()
            role = locator.get_attribute("role")
            aria_label = locator.get_attribute("aria-label")
            title = locator.get_attribute("title")
            text = (locator.inner_text() or "").strip()
            tag_name = locator.evaluate("(el) => (el.tagName || '').toLowerCase()")
            return {
                "visible": True,
                "tag": tag_name,
                "role": role,
                "ariaLabel": aria_label,
                "title": title,
                "text": text[:140],
                "box": box,
            }
        except Exception:
            return None

    def _candidate_to_dict(self, candidate: _PreviewCandidate) -> dict:
        return {
            "key": candidate.key,
            "score": candidate.score,
            "yBottom": candidate.y_bottom,
            "src": candidate.src,
            "width": candidate.width,
            "height": candidate.height,
            "x": candidate.x,
            "y": candidate.y,
        }

    def _collect_dom_snippet(self, page) -> dict | None:
        try:
            return page.evaluate(
                """() => {
                    const pickText = (el) =>
                        (el.innerText || el.textContent || '')
                            .replace(/\\s+/g, ' ')
                            .trim()
                            .slice(0, 140);
                    const box = (el) => {
                        const rect = el.getBoundingClientRect();
                        return {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                        };
                    };
                    const isVisible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                    };

                    const promptNodes = Array.from(
                        document.querySelectorAll('textarea, [contenteditable=\"true\"], [role=\"textbox\"]')
                    )
                    .filter((el) => isVisible(el))
                    .slice(-8)
                    .map((el) => ({
                        tag: (el.tagName || '').toLowerCase(),
                        role: el.getAttribute('role'),
                        ariaLabel: el.getAttribute('aria-label'),
                        text: pickText(el),
                        box: box(el),
                    }));

                    const buttonNodes = Array.from(document.querySelectorAll('button, [role=\"button\"]'))
                    .filter((el) => isVisible(el))
                    .slice(-40)
                    .map((el) => ({
                        tag: (el.tagName || '').toLowerCase(),
                        role: el.getAttribute('role'),
                        ariaLabel: el.getAttribute('aria-label'),
                        title: el.getAttribute('title'),
                        text: pickText(el),
                        box: box(el),
                    }));

                    const imageNodes = Array.from(document.querySelectorAll('img'))
                    .filter((el) => isVisible(el))
                    .slice(-50)
                    .map((el) => ({
                        src: (el.getAttribute('src') || '').slice(0, 240),
                        alt: (el.getAttribute('alt') || '').slice(0, 120),
                        box: box(el),
                    }));

                    return {
                        promptNodes,
                        buttonNodes,
                        imageNodes,
                    };
                }"""
            )
        except Exception:
            return None

    def _sanitize_thread_url(self, raw_url: object) -> str | None:
        url = str(raw_url or "").strip()
        if not url:
            return None
        if _looks_like_login_page(url):
            return None
        parsed = urlparse(url)
        if (parsed.netloc or "gemini.google.com").lower() != "gemini.google.com":
            return None
        if parsed.path.rstrip("/") in {"", "/"}:
            return None
        return url

    def _urls_match_loosely(self, left: str | None, right: str | None) -> bool:
        if not left or not right:
            return False
        left_parsed = urlparse(left)
        right_parsed = urlparse(right)
        left_query = urlencode(sorted(parse_qsl(left_parsed.query, keep_blank_values=True)))
        right_query = urlencode(sorted(parse_qsl(right_parsed.query, keep_blank_values=True)))
        left_key = ((left_parsed.netloc or "").lower(), left_parsed.path.rstrip("/"), left_query)
        right_key = ((right_parsed.netloc or "").lower(), right_parsed.path.rstrip("/"), right_query)
        return left_key == right_key

    def _ensure_workspace_ready(self, page, *, target_url: str | None = None) -> None:
        desired_url = target_url or self._base_url
        try:
            current_url = page.url
        except Exception:
            current_url = ""

        if self._urls_match_loosely(current_url, desired_url):
            if self._find_prompt_target(page) is not None:
                return

        page.goto(desired_url, wait_until="domcontentloaded", timeout=35_000)
        if _looks_like_login_page(page.url):
            raise GeminiWebAuthError(
                "Chua tim thay session Gemini trong profile rieng cua app. Hay dang nhap Gemini roi thu lai."
            )

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self._find_prompt_target(page) is not None:
                return

            try:
                if page.locator('input[type="file"]').count() > 0:
                    return
            except Exception:
                pass
            page.wait_for_timeout(350)

        raise GeminiWebError("Khong tim thay khung nhap prompt tren Gemini.")

    def _ensure_image_tool_selected(self, page) -> None:
        """
        Chọn công cụ 'Tạo hình ảnh' (Image creation) trong Gemini trước khi gửi prompt.
        Nếu không tìm thấy nút hoặc đã chọn rồi, bỏ qua và tiếp tục.
        """
        # Các selector phổ biến của nút tạo hình ảnh trên Gemini
        image_tool_selectors = [
            # Data attributes
            '[data-tool-id="image_generation"]',
            '[data-test-id="image-generation-tool"]',
            # Aria labels (EN + VI)
            'button[aria-label*="image" i][aria-label*="generat" i]',
            'button[aria-label*="tạo hình" i]',
            'button[aria-label*="tao hinh" i]',
            'button[aria-label*="image creation" i]',
            'button[aria-label*="create image" i]',
            # Pill / chip buttons at toolbar
            'button.tool-chip',
            '[role="button"][data-tool-name*="image" i]',
        ]

        # Check if there's an active/selected image tool already
        active_selectors = [
            '[data-tool-id="image_generation"][aria-pressed="true"]',
            '[data-tool-id="image_generation"].active',
            'button[aria-label*="image" i][aria-pressed="true"]',
        ]
        for sel in active_selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    return  # Already selected
            except Exception:
                pass

        # Try to find and click the image tool button
        for selector in image_tool_selectors:
            try:
                loc = page.locator(selector)
                count = loc.count()
                for idx in range(min(count, 10)):
                    candidate = loc.nth(idx)
                    try:
                        if not candidate.is_visible():
                            continue
                        text = (candidate.inner_text() or "").strip().lower()
                        aria = (candidate.get_attribute("aria-label") or "").strip().lower()
                        combined = f"{text} {aria}"
                        # Match if the button contains image/hình keywords
                        if any(kw in combined for kw in (
                            "image", "tạo hình", "tao hinh", "hình ảnh", "hinh anh",
                            "create image", "generate image", "image generation",
                        )):
                            candidate.click()
                            page.wait_for_timeout(400)
                            print(
                                f"[GeminiWebAdapter] Đã chọn công cụ tạo hình ảnh: '{text or aria}'",
                                flush=True,
                            )
                            return
                    except Exception:
                        continue
            except Exception:
                continue

        # Fallback: scan all visible toolbar buttons for image keyword
        try:
            all_buttons = page.locator("button, [role='button']")
            btn_count = all_buttons.count()
            for idx in range(min(btn_count, 60)):
                btn = all_buttons.nth(idx)
                try:
                    if not btn.is_visible():
                        continue
                    text = (btn.inner_text() or "").strip().lower()
                    aria = (btn.get_attribute("aria-label") or "").strip().lower()
                    title = (btn.get_attribute("title") or "").strip().lower()
                    combined = f"{text} {aria} {title}"
                    if any(kw in combined for kw in (
                        "tạo hình ảnh", "image creation", "create image", "generate image",
                    )):
                        btn.click()
                        page.wait_for_timeout(400)
                        print(
                            f"[GeminiWebAdapter] (fallback) Đã chọn công cụ tạo hình ảnh: '{text or aria}'",
                            flush=True,
                        )
                        return
                except Exception:
                    continue
        except Exception:
            pass

        print("[GeminiWebAdapter] Không tìm thấy nút tạo hình ảnh — bỏ qua, dùng chế độ mặc định.", flush=True)

    def _resolve_generation_mode_label(self) -> str | None:
        raw_model = str(self._model_name or "").strip()
        if not raw_model:
            return None
        normalized = self._normalize_ui_text(raw_model).replace("_", " ").replace("-", " ").strip()
        return GEMINI_MODEL_MODE_LABELS.get(raw_model.lower()) or GEMINI_MODEL_MODE_LABELS.get(normalized)

    def _apply_generation_mode(self, page) -> None:
        desired_label = self._resolve_generation_mode_label()
        if not desired_label:
            return

        current_label = self._read_mode_picker_label(page)
        if self._mode_label_matches(current_label, desired_label):
            self._dismiss_transient_overlays(page)
            return

        picker_button = self._find_mode_picker_button(page)
        if picker_button is None:
            print(
                f"[DEBUG] Gemini mode picker not found; continue with current default mode while targeting `{desired_label}`.",
                flush=True,
            )
            return

        try:
            picker_button.click()
        except Exception:
            try:
                picker_button.click(force=True)
            except Exception as exc:
                print(
                    f"[DEBUG] Gemini mode picker click failed; continue with current default mode while targeting `{desired_label}`: {exc}",
                    flush=True,
                )
                return
        page.wait_for_timeout(250)

        option = self._find_mode_menu_option(page, desired_label)
        if option is None:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            print(
                f"[DEBUG] Gemini mode option `{desired_label}` not found; continue with current default mode.",
                flush=True,
            )
            return

        try:
            option.click()
        except Exception:
            try:
                option.click(force=True)
            except Exception as exc:
                print(
                    f"[DEBUG] Gemini mode option `{desired_label}` click failed; continue with current default mode: {exc}",
                    flush=True,
                )
                return
        page.wait_for_timeout(200)
        self._dismiss_transient_overlays(page)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            page.wait_for_timeout(200)
            current_label = self._read_mode_picker_label(page)
            if self._mode_label_matches(current_label, desired_label):
                self._dismiss_transient_overlays(page)
                return

        print(
            f"[DEBUG] Gemini mode `{desired_label}` was not confirmed after selection; continue with current default mode.",
            flush=True,
        )
        self._dismiss_transient_overlays(page)

    def _find_mode_picker_button(self, page):
        selectors = [
            'button[data-test-id="bard-mode-menu-button"]',
            'button[aria-label*="bộ chọn chế độ" i]',
            'button[aria-label*="model switcher" i]',
            'button[aria-label*="mode switcher" i]',
            'button[aria-label*="mode" i]',
        ]
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                count = 0
            for index in range(count):
                candidate = locator.nth(index)
                try:
                    if candidate.is_visible():
                        return candidate
                except Exception:
                    continue
        return None

    def _read_mode_picker_label(self, page) -> str:
        picker_button = self._find_mode_picker_button(page)
        if picker_button is None:
            return ""
        try:
            return (picker_button.inner_text() or "").strip()
        except Exception:
            return ""

    def _find_mode_menu_option(self, page, desired_label: str):
        # We need to find the option that matches the desired mode.
        # Gemini UI uses different labels depending on the language (e.g. "Nhanh" vs "Flash").
        desired_key = self._normalize_ui_text(desired_label)
        
        # Mapping of canonical terms to alternative language terms
        alt_terms = {
            "nhanh": ["flash", "fast", "nhanh"],
            "tu duy": ["thinking", "tu duy"],
            "pro": ["pro"],
        }
        
        target_keys = [desired_key]
        for canonical, alts in alt_terms.items():
            if desired_key in alts:
                target_keys = alts
                break

        selectors = [
            "[role='menuitem']",
            "button",
            "[role='button']",
            ".mat-mdc-menu-item",
            ".mat-mdc-list-item",
        ]
        best = None
        best_score = float("-inf")

        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                count = 0
            for index in range(min(count, 120)):
                candidate = locator.nth(index)
                try:
                    if not candidate.is_visible():
                        continue
                    text_blob = self._button_text_blob(candidate)
                    normalized_text = self._normalize_ui_text(text_blob)
                    
                    matches = any(tk in normalized_text for tk in target_keys)
                    if not matches:
                        continue
                        
                    box = candidate.bounding_box()
                    if not box or box["width"] < 120 or box["height"] < 24:
                        continue

                    score = 0.0
                    if any(normalized_text.startswith(tk) for tk in target_keys):
                        score += 140.0
                    if "gemini 3" in normalized_text:
                        score -= 80.0
                    if "nang cap" in normalized_text or "ultra" in normalized_text:
                        score -= 120.0
                    score += min(box["width"], 420) * 0.02
                    score += min(box["height"], 120) * 0.3
                    if score > best_score:
                        best = candidate
                        best_score = score
                except Exception:
                    continue

        return best

    def _mode_label_matches(self, current_label: str, desired_label: str) -> bool:
        current_key = self._normalize_ui_text(current_label)
        desired_key = self._normalize_ui_text(desired_label)
        if not current_key or not desired_key:
            return False
            
        alt_terms = {
            "nhanh": ["flash", "fast", "nhanh"],
            "tu duy": ["thinking", "tu duy"],
            "pro": ["pro"],
        }
        
        target_keys = [desired_key]
        for canonical, alts in alt_terms.items():
            if desired_key in alts:
                target_keys = alts
                break
                
        return any(tk in current_key for tk in target_keys)

    def _normalize_ui_text(self, value: str) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(char for char in text if not unicodedata.combining(char))
        return re.sub(r"\s+", " ", text).strip().lower()

    def _upload_input_image(self, page, input_image_path: Path) -> None:
        if self._set_file_via_existing_inputs(page, input_image_path):
            return

        composer = self._find_prompt_target(page)
        attach_buttons = self._find_attachment_buttons(page, composer)
        for button in attach_buttons:
            try:
                if self._set_file_via_file_chooser_click(page, button, input_image_path):
                    return
            except Exception:
                pass

            try:
                button.click(force=True)
            except Exception:
                try:
                    button.evaluate("(el) => el.click()")
                except Exception:
                    pass
            page.wait_for_timeout(250)

            if self._set_file_via_existing_inputs(page, input_image_path):
                return
            if self._set_file_via_upload_menu_items(page, input_image_path):
                return
            if self._set_file_via_hidden_upload_triggers(page, input_image_path):
                return

        if self._set_file_via_upload_menu_items(page, input_image_path):
            return
        if self._set_file_via_hidden_upload_triggers(page, input_image_path):
            return

        raise GeminiWebError("Khong tim thay file input de upload anh vao Gemini.")

    def _submit_prompt(self, page, prompt: str) -> None:
        clean_prompt = prompt.strip()
        if not clean_prompt:
            raise GeminiWebError("Prompt rong, khong the gui len Gemini.")

        target = self._find_prompt_target(page)
        if target is None:
            raise GeminiWebError("Khong tim thay o nhap prompt tren Gemini.")

        # Dam bao focus truoc khi thuc hien bat ky thao tac nao
        try:
            target.scroll_into_view_if_needed()
            target.focus()
            page.wait_for_timeout(100)
            target.click()
            page.wait_for_timeout(100)
        except Exception:
            pass

        is_textarea = False
        try:
            tag_name = (target.evaluate("(el) => el.tagName") or "").lower()
            is_textarea = tag_name == "textarea"
        except Exception:
            is_textarea = False

        if is_textarea:
            target.fill(clean_prompt)
        else:
            # Clear existing content via JS for contenteditable for reliability
            try:
                target.evaluate("(el) => { if (el.innerText) { el.innerText = ''; } else if (el.textContent) { el.textContent = ''; } el.dispatchEvent(new Event('input', { bubbles: true })); }")
                page.wait_for_timeout(100)
            except Exception:
                pass

            # Fallback clear using keyboard if JS failed
            modifier = "Meta+A" if sys.platform == "darwin" else "Control+A"
            try:
                page.keyboard.press(modifier)
                page.keyboard.press("Backspace")
                page.wait_for_timeout(50)
            except Exception:
                pass

            self._type_rich_text_prompt(page, target, clean_prompt)

        page.wait_for_timeout(400)
        self._ensure_prompt_submission_ready(page, target, clean_prompt)
        self._dismiss_transient_overlays(page)
        sent = self._click_send_button(page, target)
        if not sent:
            page.wait_for_timeout(300)
            self._ensure_prompt_submission_ready(page, target, clean_prompt)
            self._dismiss_transient_overlays(page)
            sent = self._click_send_button(page, target)
        if not sent:
            page.keyboard.press("Enter")

    def _type_rich_text_prompt(self, page, target, prompt: str) -> None:
        # Try JS injection first for speed and reliability in headless/background
        if self._set_rich_text_prompt(target, prompt):
            # Still trigger one keyboard event to ensure the "Send" button notices the change
            try:
                target.focus()
                page.keyboard.press("End")
                page.keyboard.type(" ")
                page.keyboard.press("Backspace")
            except Exception:
                pass
            
            if self._prompt_text_matches(target, prompt):
                return

        # Fallback to standard typing
        try:
            target.focus()
            page.keyboard.type(prompt, delay=15)
        except Exception:
            try:
                page.keyboard.insert_text(prompt)
            except Exception:
                pass

        if self._prompt_text_matches(target, prompt):
            return

        # Final attempt via JS if typing failed
        self._set_rich_text_prompt(target, prompt)

    def _normalize_prompt_text(self, value: str | None) -> str:
        if not value:
            return ""
        normalized = unicodedata.normalize("NFKC", str(value))
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
        normalized = normalized.replace("\u00a0", " ")
        normalized = re.sub(r"[\u200b-\u200d\ufeff]", "", normalized)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n")]
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)

    def _read_prompt_text(self, target) -> str:
        try:
            value = target.evaluate(
                """
                (el) => {
                  if (!el) return '';
                  return el.innerText || el.textContent || '';
                }
                """
            )
        except Exception:
            try:
                value = target.inner_text() or ""
            except Exception:
                value = ""
        return self._normalize_prompt_text(value)

    def _prompt_text_matches(self, target, prompt: str) -> bool:
        current_text = self._read_prompt_text(target)
        expected_text = self._normalize_prompt_text(prompt)
        return current_text == expected_text

    def _set_rich_text_prompt(self, target, prompt: str) -> bool:
        try:
            target.evaluate(
                "(el, val) => { if (el.innerText !== undefined) { el.innerText = val; } else { el.textContent = val; } el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }",
                prompt
            )
            return True
        except Exception:
            return False

    def _ensure_prompt_submission_ready(self, page, target, prompt: str) -> None:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            self._dismiss_transient_overlays(page)
            if self._is_send_button_enabled(page):
                return
            try:
                target.click()
            except Exception:
                pass
            page.wait_for_timeout(250)

        try:
            target.click()
            page.keyboard.press(" ")
            page.keyboard.press("Backspace")
        except Exception:
            pass
        page.wait_for_timeout(250)
        self._dismiss_transient_overlays(page)
        if self._is_send_button_enabled(page):
            return
        raise GeminiWebError("Nut gui Gemini van bi khoa sau khi nhap prompt.")

    def _is_send_button_enabled(self, page) -> bool:
        send_selectors = [
            ".send-button-container button",
            "button.send-button",
            'button[aria-label*="Gửi tin nhắn" i]',
            'button[aria-label*="send" i]',
            'button[aria-label*="message" i]',
            'button[aria-label*="gui" i]',
            'button[data-testid*="send" i]',
            'button:has-text("Gửi")',
            'button:has-text("Send")',
        ]
        for selector in send_selectors:
            locator = page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                count = 0
            for index in range(min(count, 6)):
                candidate = locator.nth(index)
                try:
                    if not candidate.is_visible():
                        continue
                    if self._is_stop_or_cancel_button(candidate):
                        continue
                    aria_disabled = (candidate.get_attribute("aria-disabled") or "").strip().lower()
                    disabled_attr = candidate.get_attribute("disabled")
                    if aria_disabled == "true" or disabled_attr is not None or candidate.is_disabled():
                        continue
                    return True
                except Exception:
                    continue
        return False

    def _is_stop_or_cancel_button(self, candidate) -> bool:
        parts: list[str] = []
        for attr in ("aria-label", "title", "class", "data-testid", "data-test-id"):
            try:
                parts.append(candidate.get_attribute(attr) or "")
            except Exception:
                pass
        try:
            parts.append(candidate.inner_text() or "")
        except Exception:
            pass

        text_blob = self._normalize_ui_text(" ".join(parts))
        if not text_blob:
            return False

        stop_tokens = (
            "stop",
            "stop response",
            "stop generating",
            "cancel response",
            "dung",
            "ngung",
            "tam dung",
            "huy",
        )
        return any(token in text_blob for token in stop_tokens)

    def _dismiss_transient_overlays(self, page) -> None:
        overlay_selectors = [
            "[role='menu']",
            "[role='listbox']",
            ".mat-mdc-menu-panel",
            ".cdk-overlay-pane",
        ]

        for _ in range(2):
            overlay_visible = False
            for selector in overlay_selectors:
                locator = page.locator(selector)
                try:
                    count = locator.count()
                except Exception:
                    count = 0
                for index in range(min(count, 8)):
                    candidate = locator.nth(index)
                    try:
                        if candidate.is_visible():
                            overlay_visible = True
                            break
                    except Exception:
                        continue
                if overlay_visible:
                    break

            if not overlay_visible:
                return

            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            try:
                picker = page.locator('button[data-test-id="bard-mode-menu-button"][aria-expanded="true"]').first
                if picker.count() > 0:
                    picker.click(force=True)
            except Exception:
                pass
            page.wait_for_timeout(180)

    def _find_prompt_target(self, page):
        selectors = [
            "textarea",
            ".ql-editor",
            "div[contenteditable='true']",
            "[role='textbox'][contenteditable='true']",
            "[contenteditable='true'][role='textbox']",
            "div[aria-label*='Nhập' i]",
            "div[aria-label*='Prompt' i]",
            "div[aria-label*='tin nhắn' i]",
            "div[aria-label*='Enter' i]",
            "div[aria-label*='Type' i]",
            "div[aria-label*='message' i]",
            "div[aria-label*='ask' i]",
            "[role='textbox']",
        ]

        best = None
        best_score = float("-inf")
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                continue

            limit = min(count, 20)
            for index in range(limit):
                candidate = locator.nth(index)
                try:
                    if not candidate.is_visible():
                        continue
                    box = candidate.bounding_box()
                    if not box:
                        continue
                    if box["width"] < 220 or box["height"] < 24:
                        continue
                    aria_disabled = (candidate.get_attribute("aria-disabled") or "").strip().lower()
                    if aria_disabled == "true":
                        continue

                    score = (
                        box["y"] * 1.8
                        + box["width"] * 0.02
                        + min(box["height"], 120) * 0.08
                    )
                    try:
                        role = (candidate.get_attribute("role") or "").strip().lower()
                        if role == "textbox":
                            score += 40
                    except Exception:
                        pass
                    if score > best_score:
                        best = candidate
                        best_score = score
                except Exception:
                    continue

        return best

    def _set_file_via_existing_inputs(self, page, input_image_path: Path) -> bool:
        file_inputs = page.locator('input[type="file"]')
        try:
            count = file_inputs.count()
        except Exception:
            count = 0

        for index in reversed(range(count)):
            try:
                file_inputs.nth(index).set_input_files(str(input_image_path))
                page.wait_for_timeout(450)
                return True
            except Exception:
                continue
        return False

    def _set_file_via_hidden_upload_triggers(self, page, input_image_path: Path) -> bool:
        selectors = [
            'button[data-test-id="hidden-local-image-upload-button"]',
            'button[data-test-id="hidden-local-file-upload-button"]',
            'button[xapfileselectortrigger][data-test-id*="upload" i]',
            'button[xapfileselectortrigger]',
        ]

        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                count = 0

            for index in reversed(range(count)):
                if self._set_file_via_file_chooser_click(page, locator.nth(index), input_image_path, timeout_ms=1_000):
                    return True

        return False

    def _set_file_via_upload_menu_items(self, page, input_image_path: Path) -> bool:
        candidates: list[tuple[float, object]] = []
        selectors = [
            "[role='menuitem']",
            "button",
            "[role='button']",
            ".mat-mdc-menu-item",
            ".mat-mdc-list-item",
        ]
        preferred_patterns = [
            r"tải\s*tệp\s*lên",
            r"thêm\s*tệp",
            r"upload",
            r"from\s+computer",
            r"local\s+file",
            r"ảnh",
            r"image",
            r"photo",
        ]
        reject_patterns = [
            r"drive",
            r"notebooklm",
            r"nhập\s*mã",
            r"code",
        ]

        seen: set[str] = set()
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                count = 0

            for index in range(min(count, 80)):
                item = locator.nth(index)
                try:
                    if not item.is_visible():
                        continue
                    box = item.bounding_box()
                    if not box or box["width"] < 60 or box["height"] < 24:
                        continue
                    text_blob = self._button_text_blob(item)
                    if not text_blob or text_blob in seen:
                        continue
                    seen.add(text_blob)
                    if any(re.search(pattern, text_blob, flags=re.IGNORECASE) for pattern in reject_patterns):
                        continue

                    score = 0.0
                    for pattern in preferred_patterns:
                        if re.search(pattern, text_blob, flags=re.IGNORECASE):
                            score += 120.0
                    if "ảnh" in text_blob or "image" in text_blob or "photo" in text_blob:
                        score += 30.0
                    if score <= 0:
                        continue

                    candidates.append((score, item))
                except Exception:
                    continue

        candidates.sort(key=lambda item: item[0], reverse=True)
        for _, item in candidates[:8]:
            if self._set_file_via_file_chooser_click(page, item, input_image_path, timeout_ms=1_500):
                return True
            if self._set_file_via_existing_inputs(page, input_image_path):
                return True

        return False

    def _set_file_via_file_chooser_click(self, page, target, input_image_path: Path, *, timeout_ms: int = 1_500) -> bool:
        clickers = [
            lambda: target.click(),
            lambda: target.click(force=True),
            lambda: target.evaluate("(el) => el.click()"),
        ]
        for clicker in clickers:
            try:
                with page.expect_file_chooser(timeout=timeout_ms) as chooser_info:
                    clicker()
                chooser = chooser_info.value
                chooser.set_files(str(input_image_path))
                page.wait_for_timeout(500)
                return True
            except Exception:
                if self._set_file_via_existing_inputs(page, input_image_path):
                    return True
                continue
        return False

    def _button_text_blob(self, candidate) -> str:
        try:
            aria_label = candidate.get_attribute("aria-label") or ""
        except Exception:
            aria_label = ""
        try:
            inner_text = candidate.inner_text() or ""
        except Exception:
            inner_text = ""
        try:
            title = candidate.get_attribute("title") or ""
        except Exception:
            title = ""
        return " ".join([aria_label, inner_text, title]).strip().lower()

    def _collect_locator_source_urls(self, locator) -> list[str]:
        try:
            raw_urls = locator.evaluate(
                """(el) => {
                    const collected = [];
                    const seen = new Set();
                    const push = (value) => {
                        if (typeof value !== 'string') return;
                        const normalized = value.trim();
                        if (!normalized || seen.has(normalized)) return;
                        if (
                            normalized.startsWith('blob:') ||
                            normalized.startsWith('data:') ||
                            normalized.startsWith('http://') ||
                            normalized.startsWith('https://') ||
                            normalized.startsWith('/')
                        ) {
                            seen.add(normalized);
                            collected.push(normalized);
                        }
                    };

                    const pushSrcSet = (value) => {
                        if (typeof value !== 'string') return;
                        for (const part of value.split(',')) {
                            const candidateUrl = part.trim().split(/\\s+/)[0];
                            push(candidateUrl);
                        }
                    };

                    const attrNames = [
                        'data-full-src',
                        'data-full-image-src',
                        'data-image-src',
                        'data-image-url',
                        'data-download-url',
                        'data-large-src',
                        'data-src',
                    ];

                    push(el.currentSrc || '');
                    push(el.src || '');
                    push(el.getAttribute('src') || '');
                    pushSrcSet(el.currentSrc ? '' : el.getAttribute('srcset') || '');
                    pushSrcSet(el.getAttribute('srcset') || '');
                    pushSrcSet(el.getAttribute('data-srcset') || '');
                    for (const name of attrNames) {
                        push(el.getAttribute?.(name) || '');
                    }

                    let node = el;
                    while (node) {
                        if (node instanceof HTMLAnchorElement) {
                            push(node.href || node.getAttribute('href') || '');
                        }
                        for (const name of attrNames) {
                            push(node.getAttribute?.(name) || '');
                        }
                        node = node.parentElement;
                    }

                    return collected;
                }"""
            )
        except Exception:
            return []

        if not isinstance(raw_urls, list):
            return []
        return [str(item).strip() for item in raw_urls if str(item).strip()]

    def _is_probable_attachment_button(self, text_blob: str) -> bool:
        attach_tokens = ["upload", "attach", "image", "photo", "file", "tải", "anh", "ảnh", "hình", "đính", "tệp"]
        reject_tokens = ["bỏ chọn", "deselect", "công cụ", "toolbox", "tools", "micrô", "microphone", "gửi", "send"]
        if any(token in text_blob for token in reject_tokens):
            return False
        return any(token in text_blob for token in attach_tokens)

    def _find_attachment_buttons(self, page, composer) -> list[object]:
        """
        Locates buttons used for attaching files/images.
        Uses both specific ARIA labels and proximity to the prompt composer.
        """
        targeted_selectors = [
            'button[aria-label*="upload" i]',
            'button[aria-label*="attach" i]',
            'button[aria-label*="add" i]',
            'button[aria-label*="tải" i]',
            'button[aria-label*="đính" i]',
            'button[aria-label*="ảnh" i]',
            'button[aria-label*="image" i]',
            'button:has(svg[path*="upload"])',
            'button:has(svg[path*="attach"])',
            'button:has(svg[path*="image"])',
        ]
        
        candidates = []
        for selector in targeted_selectors:
            try:
                locators = page.locator(selector)
                count = locators.count()
                for i in range(count):
                    btn = locators.nth(i)
                    if btn.is_visible() and self._is_probable_attachment_button(self._button_text_blob(btn)):
                        candidates.append(btn)
            except Exception:
                continue
        
        if candidates:
            return candidates

        send_tokens = ["send", "run", "generate", "gửi", "gui", "tạo", "tao", "chạy", "chay"]
        
        composer_box = None
        if composer is not None:
            try:
                composer_box = composer.bounding_box()
            except Exception:
                pass

        try:
            buttons = page.locator("button, [role='button']")
            count = buttons.count()
            limit = min(count, 100)
            scored: list[tuple[float, object]] = []
            
            for i in range(limit):
                btn = buttons.nth(i)
                if not btn.is_visible():
                    continue

                combined = self._button_text_blob(btn)
                
                if any(token in combined for token in send_tokens):
                    continue
                
                score = 0.0
                if self._is_probable_attachment_button(combined):
                    score += 200.0
                
                if composer_box:
                    box = btn.bounding_box()
                    if box:
                        dist = abs(box["x"] - composer_box["x"]) + abs(box["y"] - composer_box["y"])
                        score += max(0.0, 300.0 - dist)
                
                if score > 0:
                    scored.append((score, btn))
            
            scored.sort(key=lambda x: x[0], reverse=True)
            return [x[1] for x in scored[:5]]
        except Exception:
            pass

        return []

    def _list_gems_with_playwright(self) -> list[dict]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return []

        profile = detect_gemini_browser_profile()

        def _is_login_gate(page) -> bool:
            return bool(
                page.evaluate("""() => {
                    // Check for redirect to accounts.google.com
                    if (window.location.host.includes('accounts.google.com')) return true;
                    
                    // Check for explicit login buttons that are prominent
                    const loginButtons = Array.from(document.querySelectorAll('a, button')).filter(el => {
                        const text = (el.innerText || el.textContent || '').toLowerCase();
                        return (text === 'sign in' || text === 'đăng nhập') && el.offsetParent !== null;
                    });
                    if (loginButtons.length > 0 && document.querySelectorAll('gemini-app, .main-content').length === 0) return true;
                    
                    // Check for the Absence of the main app container which indicates we are not inside Gemini
                    const hasApp = !!document.querySelector('gemini-app') || !!document.querySelector('.chat-history') || !!document.querySelector('chat-window');
                    if (!hasApp && (window.location.pathname.includes('/app') || window.location.pathname.includes('/gems'))) {
                         // If we are on an app path but don't see the app container, we might be on a landing page or login gate
                         return true;
                    }
                    
                    return false;
                }""")
            )

        def _collect_gems_from_page(page) -> list[dict]:
            dismiss_button = page.get_by_role("button", name="Dismiss")
            try:
                if dismiss_button.count():
                    dismiss_button.first.click()
            except Exception:
                pass

            def read_all_gems_state() -> dict:
                return page.evaluate("""() => {
                    const containers = Array.from(document.querySelectorAll('[data-test-id$="-gems-list"]'));
                    if (containers.length === 0) {
                        return { hasContainer: false, text: '', links: [] };
                    }

                    let allLinks = [];
                    containers.forEach(container => {
                        const links = Array.from(container.querySelectorAll('a[href]')).map((link) => ({
                            url: link.href || link.getAttribute('href') || '',
                            text: (link.innerText || link.textContent || '').trim(),
                            ariaLabel: (link.getAttribute('aria-label') || '').trim(),
                            title: (link.getAttribute('title') || '').trim(),
                        }));
                        allLinks = allLinks.concat(links);
                    });

                    return {
                        hasContainer: true,
                        links: allLinks,
                    };
            }""")

            def read_fallback_gem_links() -> list[dict]:
                return page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll('a[href]')).map((link) => ({
                        url: link.href || link.getAttribute('href') || '',
                        text: (link.innerText || link.textContent || '').trim(),
                        ariaLabel: (link.getAttribute('aria-label') || '').trim(),
                        title: (link.getAttribute('title') || '').trim(),
                    }));
                    return links.filter((link) =>
                        /gemini\\.google\\.com\\/(gem|gems|app\\/gems)/i.test(link.url) ||
                        /^\\/(gem|gems|app\\/gems)/i.test(link.url)
                    );
                }""")

            raw_gems: list[dict] = []
            for i in range(15):
                state = read_all_gems_state()
                container_links = list(state.get("links") or [])
                fallback_links = [l for l in read_fallback_gem_links() if _is_custom_gem_link(l)]
                combined_links = container_links + fallback_links

                if combined_links:
                    if i < 3:
                        page.wait_for_timeout(1500)
                        state = read_all_gems_state()
                        container_links = list(state.get("links") or [])
                        fallback_links = [l for l in read_fallback_gem_links() if _is_custom_gem_link(l)]
                        combined_links = container_links + fallback_links

                    raw_gems = [
                        {
                            "name": _derive_custom_gem_name(
                                str(link.get("text", "")),
                                aria_label=str(link.get("ariaLabel", "")),
                                title=str(link.get("title", "")),
                            ),
                            "url": str(link.get("url", "")),
                        }
                        for link in combined_links
                    ]
                    raw_gems = [entry for entry in raw_gems if entry["name"] and entry["url"]]
                    break
                page.wait_for_timeout(1000)

            return _normalize_gem_entries(raw_gems)

        playwright = None
        browser = None
        context = None
        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=str(profile.executable_path),
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-sync",
                    "--disable-features=Translate,OptimizationHints",
                    "--disable-background-networking",
                    "--disable-component-update",
                ],
            )
            context = browser.new_context()
            cookie_count = _sync_browser_cookies_to_context(context, profile)
            if cookie_count <= 0:
                print("[DEBUG] Gem scan khong nap duoc cookie nao vao context tam.")
                return []

            page = context.new_page()
            page.set_default_timeout(30_000)

            candidate_urls = [
                GEMINI_GEMS_VIEW_URL,
                "https://gemini.google.com/gems",
                "https://gemini.google.com/app/gems",
            ]
            for target_url in candidate_urls:
                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=45_000)
                    page.wait_for_timeout(4_000)
                except Exception as exc:
                    print(f"[DEBUG] Gem scan goto failed for {target_url}: {exc}")
                    continue

                if _is_login_gate(page):
                    print(f"[DEBUG] Gem scan bi chuyen toi login gate tai {target_url}.")
                    continue

                gems = _collect_gems_from_page(page)
                if gems:
                    return gems

            print("[DEBUG] Gem scan khong tim thay Gem nao tren cac trang da thu.")
            return []
        except Exception as exc:
            print(f"[DEBUG] Failed to list gems from dedicated Gemini profile: {exc}")
            return []
        finally:
            if context:
                context.close()
            if browser:
                browser.close()
            if playwright:
                playwright.stop()

    def list_gems(self) -> list[dict]:
        """
        Runs gem scanning in a subprocess to avoid GUI/runtime conflicts with
        the desktop app process.
        """
        if os.environ.get("FLOWGEN_GEM_SCAN_MODE") == "child":
            return self._list_gems_with_playwright()

        script = (
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "from downloader_app.gemini_web_adapter import GeminiWebAdapter\n"
            "os.environ['FLOWGEN_GEM_SCAN_MODE'] = 'child'\n"
            "adapter = GeminiWebAdapter(runtime_root=Path(sys.argv[1]))\n"
            "gems = adapter._list_gems_with_playwright()\n"
            "payload = json.dumps(gems, ensure_ascii=False)\n"
            "sys.stdout.write('\\n__GEM_SCAN_JSON_START__\\n')\n"
            "sys.stdout.write(payload)\n"
            "sys.stdout.write('\\n__GEM_SCAN_JSON_END__\\n')\n"
        )
        try:
            completed = subprocess.run(
                [sys.executable, "-c", script, str(self._runtime_root)],
                capture_output=True,
                check=False,
                timeout=60,
                cwd=str(Path(__file__).resolve().parent.parent),
            )
        except Exception as exc:
            print(f"[DEBUG] Gem scan subprocess launch failed: {exc}")
            return []

        if completed.returncode == 0 and completed.stdout:
            try:
                stdout_str = completed.stdout.decode('utf-8').strip()
                start_marker = "__GEM_SCAN_JSON_START__"
                end_marker = "__GEM_SCAN_JSON_END__"
                start = stdout_str.rfind(start_marker)
                end = stdout_str.rfind(end_marker)
                if start != -1 and end != -1 and end > start:
                    payload = stdout_str[start + len(start_marker):end].strip()
                else:
                    payload = stdout_str.splitlines()[-1]
                return _normalize_gem_entries(json.loads(payload))
            except Exception as exc:
                print("[DEBUG] Gem scan subprocess returned unparsable JSON.")
                print(f"[DEBUG] Gem scan raw stdout: {stdout_str[:600]}")
                print(f"[DEBUG] Gem scan parse error: {exc}")
                return []

        stderr = str(completed.stderr or "").strip()
        if completed.returncode != 0:
            print(f"[DEBUG] Gem scan subprocess exited with code {completed.returncode}: {stderr}")
        return []

    def _click_send_button(self, page, composer) -> bool:
        send_selectors = [
            ".send-button-container button",
            "button.send-button",
            'button[aria-label*="send" i]',
            'button[aria-label*="message" i]',
            'button[aria-label*="gửi" i]',
            'button[aria-label*="gui" i]',
            'button[aria-label*="run" i]',
            '[role="button"][aria-label*="send" i]',
            '[role="button"][aria-label*="gửi" i]',
            'button[data-testid*="send" i]',
            'button[data-testid*="submit" i]',
        ]
        send_tokens = [
            "send",
            "message",
            "run",
            "generate",
            "submit",
            "gửi",
            "gui",
            "tạo",
            "tao",
            "chạy",
            "chay",
        ]
        attach_tokens = [
            "upload",
            "attach",
            "image",
            "photo",
            "file",
            "tải",
            "ảnh",
            "hình",
            "đính",
        ]

        composer_box = None
        if composer is not None:
            try:
                composer_box = composer.bounding_box()
            except Exception:
                composer_box = None

        for _ in range(8):
            for selector in send_selectors:
                try:
                    locator = page.locator(selector)
                    count = locator.count()
                    for index in reversed(range(min(count, 8))):
                        candidate = locator.nth(index)
                        if not candidate.is_visible() or candidate.is_disabled():
                            continue
                        if self._is_stop_or_cancel_button(candidate):
                            continue
                        candidate.click()
                        return True
                except Exception:
                    continue

            best = None
            best_score = float("-inf")
            buttons = page.locator("button, [role='button']")
            try:
                count = buttons.count()
            except Exception:
                count = 0
            for index in range(min(count, 160)):
                candidate = buttons.nth(index)
                try:
                    if not candidate.is_visible() or candidate.is_disabled():
                        continue
                    box = candidate.bounding_box()
                    if not box:
                        continue
                    if box["width"] < 20 or box["height"] < 20:
                        continue
                    if box["width"] > 220 or box["height"] > 140:
                        continue
                    text_blob = " ".join(
                        [
                            (candidate.get_attribute("aria-label") or ""),
                            (candidate.inner_text() or ""),
                            (candidate.get_attribute("title") or ""),
                            (candidate.get_attribute("class") or ""),
                        ]
                    ).strip().lower()
                    normalized_text_blob = self._normalize_ui_text(text_blob)
                    if self._is_stop_or_cancel_button(candidate):
                        continue
                    attach_hint = any(token in normalized_text_blob for token in attach_tokens)
                    if attach_hint:
                        continue

                    send_hint = any(token in normalized_text_blob for token in send_tokens)
                    score = 0.0
                    if "send-button" in normalized_text_blob:
                        score += 320.0
                    if send_hint:
                        score += 220.0

                    if composer_box:
                        center_x = box["x"] + box["width"] / 2
                        center_y = box["y"] + box["height"] / 2
                        composer_x = composer_box["x"] + composer_box["width"] / 2
                        composer_y = composer_box["y"] + composer_box["height"] / 2
                        distance = abs(center_x - composer_x) + abs(center_y - composer_y)
                        score += max(0.0, 420.0 - distance)

                        if center_x > composer_x:
                            score += 30.0
                        if (
                            box["y"] + box["height"] >= composer_box["y"] - 30
                            and box["y"] <= composer_box["y"] + composer_box["height"] + 30
                        ):
                            score += 60.0
                    score += min(box["width"] * box["height"], 3_000) * 0.02
                    if score > best_score:
                        best = candidate
                        best_score = score
                except Exception:
                    continue

            if best is not None and best_score >= 120:
                try:
                    best.click()
                    return True
                except Exception:
                    pass
            page.wait_for_timeout(250)
        return False

    def _collect_preview_candidates(self, page) -> list[_PreviewCandidate]:
        candidates: list[_PreviewCandidate] = []
        seen: set[str] = set()
        locator = page.locator("img")
        try:
            count = locator.count()
        except Exception:
            count = 0

        limit = min(count, 300)
        for index in range(limit):
            candidate = locator.nth(index)
            try:
                if not candidate.is_visible():
                    continue
                box = candidate.bounding_box()
                if not box:
                    continue

                width = box.get("width", 0)
                height = box.get("height", 0)
                if width < 180 or height < 140:
                    continue

                src = (candidate.get_attribute("src") or "").strip()
                if not src:
                    continue
                alt = (candidate.get_attribute("alt") or "").strip()
                if self._is_uploaded_input_preview(candidate, alt=alt):
                    continue

                source_score = 0.0
                lowered_src = src.lower()
                if lowered_src.startswith("blob:"):
                    source_score += 380.0
                if "googleusercontent" in lowered_src:
                    source_score += 260.0
                if "gstatic" in lowered_src:
                    source_score += 140.0

                y_bottom = box["y"] + height
                area = width * height
                score = (
                    source_score
                    + min(area / 1_200.0, 1_000.0)
                    + (y_bottom * 1.1)
                )

                key = (
                    f"{src}|{int(width)}x{int(height)}|"
                    f"{int(box['x'])}:{int(box['y'])}|{alt[:80]}"
                )
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    _PreviewCandidate(
                        key=key,
                        locator=candidate,
                        score=score,
                        y_bottom=y_bottom,
                        src=src[:260],
                        width=int(width),
                        height=int(height),
                        x=int(box["x"]),
                        y=int(box["y"]),
                    )
                )
            except Exception:
                continue

        candidates.sort(key=lambda item: (item.score, item.y_bottom))
        return candidates

    def _collect_uploaded_preview_candidates(self, page) -> list[_PreviewCandidate]:
        candidates: list[_PreviewCandidate] = []
        seen: set[str] = set()
        locator = page.locator("img")
        try:
            count = locator.count()
        except Exception:
            count = 0

        for index in range(min(count, 200)):
            candidate = locator.nth(index)
            try:
                if not candidate.is_visible():
                    continue
                box = candidate.bounding_box()
                if not box:
                    continue
                src = (candidate.get_attribute("src") or "").strip()
                alt = (candidate.get_attribute("alt") or "").strip()
                if not src or not self._is_uploaded_input_preview(candidate, alt=alt):
                    continue

                width = int(box.get("width", 0))
                height = int(box.get("height", 0))
                key = (
                    f"{src}|{width}x{height}|"
                    f"{int(box['x'])}:{int(box['y'])}|{alt[:80]}"
                )
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    _PreviewCandidate(
                        key=key,
                        locator=candidate,
                        score=float((width * height) + box["y"]),
                        y_bottom=float(box["y"] + box["height"]),
                        src=src[:260],
                        width=width,
                        height=height,
                        x=int(box["x"]),
                        y=int(box["y"]),
                    )
                )
            except Exception:
                continue

        candidates.sort(key=lambda item: (item.y_bottom, item.score))
        return candidates

    def _collect_uploaded_preview_keys(self, page) -> set[str]:
        return {candidate.key for candidate in self._collect_uploaded_preview_candidates(page)}

    def _wait_for_new_uploaded_preview(self, page, baseline_keys: set[str]) -> _PreviewCandidate:
        deadline = time.monotonic() + 12
        stable_candidate: _PreviewCandidate | None = None
        stable_count = 0

        while time.monotonic() < deadline:
            candidates = self._collect_uploaded_preview_candidates(page)
            new_candidates = [candidate for candidate in candidates if candidate.key not in baseline_keys]
            if new_candidates:
                latest = new_candidates[-1]
                if stable_candidate and latest.key == stable_candidate.key:
                    stable_count += 1
                else:
                    stable_candidate = latest
                    stable_count = 1
                if stable_count >= 2:
                    return latest
            page.wait_for_timeout(300)

        raise GeminiWebError("Khong phat hien uploaded preview moi sau khi paste anh vao Gemini.")

    def _is_candidate_in_composer_area(self, page, candidate: _PreviewCandidate) -> bool:
        composer = self._find_prompt_target(page)
        if composer is None:
            return False

        try:
            composer_box = composer.bounding_box()
        except Exception:
            composer_box = None
        if not composer_box:
            return False

        candidate_center_x = candidate.x + (candidate.width / 2)
        composer_left = composer_box["x"] - 120
        composer_right = composer_box["x"] + composer_box["width"] + 120
        if not (composer_left <= candidate_center_x <= composer_right):
            return False

        candidate_bottom = candidate.y + candidate.height
        composer_top = composer_box["y"] - 120
        composer_bottom = composer_box["y"] + composer_box["height"] + 160
        return candidate_bottom >= composer_top and candidate.y <= composer_bottom

    def _uploaded_candidates_match(self, page, left: _PreviewCandidate, right: _PreviewCandidate) -> bool:
        left_urls = set(self._collect_candidate_source_urls(left))
        right_urls = set(self._collect_candidate_source_urls(right))
        if left_urls and right_urls and left_urls.intersection(right_urls):
            return True

        if abs(left.width - right.width) > 24 or abs(left.height - right.height) > 24:
            return False

        if self._is_candidate_in_composer_area(page, left) == self._is_candidate_in_composer_area(page, right):
            return False

        return True

    def _wait_for_sent_uploaded_preview(
        self,
        page,
        baseline_keys: set[str],
        reference_candidate: _PreviewCandidate,
        *,
        minimum_y_bottom: float | None = None,
        stable_samples: int = 2,
    ) -> _PreviewCandidate | None:
        deadline = time.monotonic() + 12
        stable_candidate: _PreviewCandidate | None = None
        stable_count = 0

        while time.monotonic() < deadline:
            candidates = [
                candidate
                for candidate in self._collect_uploaded_preview_candidates(page)
                if not self._is_candidate_in_composer_area(page, candidate)
            ]

            preferred = []
            for candidate in candidates:
                if candidate.key in baseline_keys:
                    continue
                if minimum_y_bottom is not None and candidate.y_bottom <= (minimum_y_bottom + 24):
                    continue
                preferred.append(candidate)

            if not preferred and minimum_y_bottom is None:
                preferred = [
                    candidate
                    for candidate in candidates
                    if candidate.key not in baseline_keys
                    and self._uploaded_candidates_match(page, candidate, reference_candidate)
                ]

            if preferred:
                latest = preferred[-1]
                if stable_candidate and latest.key == stable_candidate.key:
                    stable_count += 1
                else:
                    stable_candidate = latest
                    stable_count = 1
                if stable_count >= max(1, stable_samples):
                    return latest

            page.wait_for_timeout(300)

        return None

    def _is_uploaded_input_preview(self, candidate, *, alt: str) -> bool:
        normalized_alt = self._normalize_ui_text(alt)
        if normalized_alt and (
            "ban xem truoc hinh anh da tai len" in normalized_alt
            or "uploaded image preview" in normalized_alt
            or "preview image" in normalized_alt
        ):
            return True

        try:
            is_uploaded = candidate.evaluate(
                """(el) => {
                    if (!el) return false;
                    const dataTestId = (el.getAttribute('data-test-id') || '').toLowerCase();
                    if (dataTestId.includes('uploaded-img')) return true;

                    const uploadPreview = el.closest(
                      'user-query, user-query-file-preview, user-query-file-carousel, .file-preview-container'
                    );
                    if (uploadPreview) return true;

                    const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
                    if (ariaLabel.includes('tải lên') || ariaLabel.includes('uploaded')) return true;
                    return false;
                }"""
            )
            return bool(is_uploaded)
        except Exception:
            return False

    def _collect_candidate_keys(self, page) -> set[str]:
        return {candidate.key for candidate in self._collect_preview_candidates(page)}

    def _wait_for_new_preview(self, page, baseline_keys: set[str]) -> _PreviewCandidate:
        deadline = time.monotonic() + (self._response_timeout_ms / 1000)
        stable_candidate: _PreviewCandidate | None = None
        stable_count = 0

        while time.monotonic() < deadline:
            candidates = self._collect_preview_candidates(page)
            new_candidates = [candidate for candidate in candidates if candidate.key not in baseline_keys]
            if new_candidates:
                latest = new_candidates[-1]
                if stable_candidate and latest.key == stable_candidate.key:
                    stable_count += 1
                else:
                    stable_candidate = latest
                    stable_count = 1

                if stable_count >= 3:
                    return latest

            error_text = self._extract_error_text(page)
            if error_text:
                raise GeminiWebError(error_text)

            page.wait_for_timeout(900)

        raise GeminiWebError("Khong phat hien preview moi tu Gemini trong thoi gian cho phep.")

    def _extract_error_text(self, page) -> str | None:
        try:
            message = page.evaluate(
                r"""() => {
                    const nodes = Array.from(document.querySelectorAll('body *'));
                    const isVisible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    for (const el of nodes) {
                        if (!isVisible(el)) continue;
                        const text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                        if (!text || text.length < 6 || text.length > 240) continue;
                        const lower = text.toLowerCase();
                        if (
                            lower.includes('something went wrong') ||
                            lower.includes('try again') ||
                            lower.includes('error') ||
                            lower.includes('unable to') ||
                            lower.includes('failed') ||
                            lower.includes('đã xảy ra lỗi') ||
                            lower.includes('da xay ra loi') ||
                            lower.includes('thử lại') ||
                            lower.includes('thu lai') ||
                            lower.includes('không thể') ||
                            lower.includes('khong the')
                        ) {
                            return text;
                        }
                    }
                    return null;
                }"""
            )
        except Exception:
            return None

        if message is None:
            return None
        text = str(message).strip()
        return text or None

    def _extract_gemini_response_text(self, page) -> str | None:
        """
        Trích xuất text message mà Gemini trả về cùng với hình ảnh (dòng mô tả, ghi chú...).
        Tìm phần text trong response cuối cùng, loại trừ UI boilerplate.
        """
        try:
            text = page.evaluate(r"""() => {
                // Tìm các container response Gemini — thường là model-response, response-content, etc.
                const responseSelectors = [
                    'model-response',
                    '[data-response-id]',
                    '.model-response-text',
                    '.response-content',
                    '.conversation-item:last-child',
                    'message-content',
                    '.message-content',
                ];

                let best = '';
                for (const sel of responseSelectors) {
                    const els = Array.from(document.querySelectorAll(sel));
                    if (!els.length) continue;
                    // Lấy phần tử cuối cùng (response mới nhất)
                    const el = els[els.length - 1];
                    const text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                    if (text && text.length > best.length && text.length < 3000) {
                        best = text;
                    }
                }

                if (best) return best;

                // Fallback: tìm paragraphs trong khu vực response
                const paras = Array.from(document.querySelectorAll('p, [role="paragraph"]'));
                const SKIP_PATTERNS = [
                    /^(gemini|google|flash|pro|thinking)/i,
                    /^(share|copy|export|feedback|like|dislike)/i,
                    /^\s*$/,
                ];
                const goodParas = paras.filter(p => {
                    const t = (p.innerText || p.textContent || '').trim();
                    if (!t || t.length < 10 || t.length > 1000) return false;
                    return !SKIP_PATTERNS.some(rx => rx.test(t));
                });
                if (goodParas.length) {
                    return goodParas[goodParas.length - 1].innerText?.trim() || null;
                }

                return null;
            }""")
        except Exception:
            return None

        if not text:
            return None
        result = str(text).strip()
        # Filter out very short/useless texts
        return result if len(result) > 5 else None

    def _collect_candidate_source_urls(self, candidate: _PreviewCandidate) -> list[str]:
        return self._collect_locator_source_urls(candidate.locator)

    def _resolve_output_path(self, target_path: Path, *, source_url: str = "", content_type: str = "") -> Path:
        suffix = ""
        lowered_type = str(content_type or "").split(";", 1)[0].strip().lower()
        if lowered_type == "image/jpeg":
            suffix = ".jpg"
        elif lowered_type == "image/png":
            suffix = ".png"
        elif lowered_type == "image/webp":
            suffix = ".webp"
        elif lowered_type == "image/gif":
            suffix = ".gif"

        if not suffix and source_url:
            parsed = urlparse(source_url)
            source_suffix = Path(parsed.path).suffix.lower()
            if source_suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                suffix = ".jpg" if source_suffix == ".jpeg" else source_suffix

        if not suffix:
            suffix = target_path.suffix or ".jpg"

        return target_path.with_suffix(suffix)

    def _fetch_image_bytes_from_page(self, page, source_url: str) -> tuple[bytes, str] | None:
        try:
            payload = page.evaluate(
                """async (url) => {
                    const toBase64 = (buffer) => {
                        const bytes = new Uint8Array(buffer);
                        const chunkSize = 0x8000;
                        let binary = '';
                        for (let index = 0; index < bytes.length; index += chunkSize) {
                            const slice = bytes.subarray(index, index + chunkSize);
                            binary += String.fromCharCode(...slice);
                        }
                        return btoa(binary);
                    };

                    try {
                        const response = await fetch(url, { credentials: 'include' });
                        if (!response.ok) {
                            return null;
                        }
                        const blob = await response.blob();
                        if (!blob.type || !blob.type.startsWith('image/')) {
                            return null;
                        }
                        const buffer = await blob.arrayBuffer();
                        return {
                            data: toBase64(buffer),
                            contentType: blob.type,
                        };
                    } catch (_error) {
                        return null;
                    }
                }""",
                source_url,
            )
        except Exception:
            return None

        if not isinstance(payload, dict):
            return None

        encoded = str(payload.get("data") or "").strip()
        content_type = str(payload.get("contentType") or "").strip()
        if not encoded:
            return None

        try:
            return base64.b64decode(encoded), content_type
        except Exception:
            return None

    def _fetch_image_bytes(self, page, source_url: str) -> tuple[bytes, str] | None:
        if not source_url:
            return None

        lowered = source_url.lower()
        if lowered.startswith(("blob:", "data:")):
            return self._fetch_image_bytes_from_page(page, source_url)

        resolved_url = urljoin(page.url, source_url)
        try:
            response = page.context.request.get(resolved_url, fail_on_status_code=False, timeout=20_000)
            if response.ok:
                content_type = str(response.headers.get("content-type") or "").strip()
                if content_type.startswith("image/"):
                    body = response.body()
                    if body:
                        return body, content_type
        except Exception:
            pass

        # Thử lấy ảnh bằng cách điều hướng trực tiếp bằng tab mới (giống user "Mở hình ảnh trong thẻ mới")
        try:
            new_page = page.context.new_page()
            try:
                response = new_page.goto(resolved_url, timeout=15_000)
                if response and response.ok:
                    content_type = str(response.headers.get("content-type") or "").strip()
                    if content_type.startswith("image/"):
                        body = response.body()
                        if body:
                            new_page.close()
                            return body, content_type
            finally:
                if not new_page.is_closed():
                    new_page.close()
        except Exception:
            pass

        return self._fetch_image_bytes_from_page(page, resolved_url)

    def _download_candidate_image(self, page, candidate: _PreviewCandidate, preview_path: Path) -> Path | None:
        for source_url in self._collect_candidate_source_urls(candidate):
            fetched = self._fetch_image_bytes(page, source_url)
            if not fetched:
                continue

            image_bytes, content_type = fetched
            if not image_bytes:
                continue

            resolved_path = self._resolve_output_path(
                preview_path,
                source_url=source_url,
                content_type=content_type,
            )
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_path.write_bytes(image_bytes)
            if resolved_path.stat().st_size > 0:
                return resolved_path

        # Mô phỏng thao tác "Chuột phải -> Lưu hình ảnh dưới dạng..."
        # bằng cách đọc data trực tiếp từ bộ nhớ render của trình duyệt (giữ nguyên độ phân giải gốc)
        try:
            payload = candidate.locator.evaluate(
                """(img) => {
                    try {
                        const canvas = document.createElement('canvas');
                        canvas.width = img.naturalWidth || img.width;
                        canvas.height = img.naturalHeight || img.height;
                        if (!canvas.width || !canvas.height) return null;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(img, 0, 0);
                        return canvas.toDataURL('image/jpeg', 1.0);
                    } catch (e) {
                        return null; // Lỗi CORS hoặc không vẽ được
                    }
                }"""
            )
            if payload and isinstance(payload, str) and payload.startswith("data:image/jpeg;base64,"):
                b64_data = payload.split(",")[1]
                image_bytes = base64.b64decode(b64_data)
                resolved_path = preview_path.with_suffix(".jpg")
                resolved_path.parent.mkdir(parents=True, exist_ok=True)
                resolved_path.write_bytes(image_bytes)
                if resolved_path.stat().st_size > 0:
                    return resolved_path
        except Exception:
            pass

        return None

    def _write_image_payload_to_path(
        self,
        preview_path: Path,
        payload: tuple[bytes, str],
    ) -> Path | None:
        image_bytes, content_type = payload
        if not image_bytes:
            return None

        resolved_path = self._resolve_output_path(
            preview_path,
            content_type=content_type,
        )
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_bytes(image_bytes)
        if resolved_path.exists() and resolved_path.stat().st_size > 0:
            return resolved_path
        return None

    def _fetch_candidate_image_payload(self, page, candidate: _PreviewCandidate) -> tuple[bytes, str] | None:
        for source_url in self._collect_candidate_source_urls(candidate):
            fetched = self._fetch_image_bytes(page, source_url)
            if not fetched:
                continue
            image_bytes, content_type = fetched
            if image_bytes:
                return image_bytes, content_type
        return None

    def _find_response_actions_root(self, candidate: _PreviewCandidate):
        roots = [
            "xpath=ancestor::response-container[1]",
            "xpath=ancestor::model-response[1]",
            "xpath=ancestor::*[@data-test-id='image-response'][1]",
        ]
        for selector in roots:
            try:
                root = candidate.locator.locator(selector).first
                if root.count() > 0:
                    return root
            except Exception:
                continue
        return None

    def _click_retry_action_for_latest_response(self, page) -> bool:
        candidates = self._collect_preview_candidates(page)
        if candidates:
            if self._click_retry_action_for_candidate(page, candidates[-1]):
                return True
        
        # Fallback: Search for retry buttons globally if no images found
        retry_selectors = [
            'button[aria-label*="retry" i]',
            'button[aria-label*="regenerate" i]',
            'button[aria-label*="redo" i]',
            'button[aria-label*="thử lại" i]',
            'button[aria-label*="thu lai" i]',
            'button[aria-label*="tạo lại" i]',
            'button[aria-label*="tao lai" i]',
            'button[aria-label*="khôi phục" i]',
            'button[aria-label*="khoi phuc" i]',
            'button[data-testid*="retry" i]',
            'button[data-testid*="regenerate" i]',
            'button:has(mat-icon:has-text("refresh"))',
            'button:has(mat-icon:has-text("rotate_right"))',
            'button:has(.google-symbols:has-text("refresh"))',
        ]
        
        for selector in retry_selectors:
            try:
                locator = page.locator(selector)
                count = locator.count()
                if count > 0:
                    # Click the last one found (most likely the latest response)
                    last_button = locator.nth(count - 1)
                    if last_button.is_visible() and not last_button.is_disabled():
                        last_button.scroll_into_view_if_needed()
                        last_button.click()
                        return True
            except Exception:
                continue
        
        return False

    def _click_retry_action_for_candidate(self, page, candidate: _PreviewCandidate) -> bool:
        try:
            candidate.locator.scroll_into_view_if_needed(timeout=5_000)
            page.wait_for_timeout(300)
        except Exception:
            pass

        action_root = self._find_response_actions_root(candidate)
        direct_selectors = [
            'button[aria-label*="retry" i]',
            'button[aria-label*="regenerate" i]',
            'button[aria-label*="redo" i]',
            'button[aria-label*="try again" i]',
            'button[aria-label*="rerun" i]',
            'button[aria-label*="thử lại" i]',
            'button[aria-label*="thu lai" i]',
            'button[aria-label*="tạo lại" i]',
            'button[aria-label*="tao lai" i]',
            'button[aria-label*="khôi phục" i]',
            'button[aria-label*="khoi phuc" i]',
            '[role="button"][aria-label*="retry" i]',
            '[role="button"][aria-label*="regenerate" i]',
            '[role="button"][aria-label*="redo" i]',
            '[role="button"][aria-label*="try again" i]',
            '[role="button"][aria-label*="thử lại" i]',
            '[role="button"][aria-label*="thu lai" i]',
        ]

        if action_root is not None:
            for selector in direct_selectors:
                try:
                    locator = action_root.locator(selector)
                    count = locator.count()
                except Exception:
                    count = 0
                for index in range(min(count, 8)):
                    button = locator.nth(index)
                    try:
                        if not button.is_visible() or button.is_disabled():
                            continue
                        button.click()
                        page.wait_for_timeout(350)
                        return True
                    except Exception:
                        continue

            action_buttons = action_root.locator("button, [role='button']")
            try:
                count = action_buttons.count()
            except Exception:
                count = 0
            best = None
            best_score = float("-inf")
            for index in range(min(count, 24)):
                button = action_buttons.nth(index)
                try:
                    if not button.is_visible() or button.is_disabled():
                        continue
                    text_blob = self._button_text_blob(button)
                    if not text_blob:
                        continue
                    score = 0.0
                    if "retry" in text_blob or "regenerate" in text_blob or "try again" in text_blob:
                        score += 240.0
                    if "thử lại" in text_blob or "thu lai" in text_blob:
                        score += 220.0
                    if "refresh" in text_blob or "reload" in text_blob or "rotate" in text_blob:
                        score += 80.0
                    if score > best_score:
                        best = button
                        best_score = score
                except Exception:
                    continue

            if best is not None and best_score >= 120:
                try:
                    best.click()
                    page.wait_for_timeout(350)
                    return True
                except Exception:
                    pass

        return False

    def _resolve_download_output_path(self, target_path: Path, suggested_filename: str) -> Path:
        suggested_suffix = Path(str(suggested_filename or "")).suffix.lower()
        if suggested_suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            normalized_suffix = ".jpg" if suggested_suffix == ".jpeg" else suggested_suffix
            return target_path.with_suffix(normalized_suffix)
        return target_path

    def _download_via_button(self, page, button, preview_path: Path) -> Path | None:
        try:
            with page.expect_download(timeout=5_000) as download_info:
                try:
                    button.click()
                except Exception:
                    button.click(force=True)
            download = download_info.value
        except Exception:
            return None

        try:
            resolved_path = self._resolve_download_output_path(
                preview_path,
                getattr(download, "suggested_filename", "") or "",
            )
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            download.save_as(str(resolved_path))
            if resolved_path.exists() and resolved_path.stat().st_size > 0:
                return resolved_path
        except Exception:
            return None
        return None

    def _download_candidate_via_response_action(self, page, candidate: _PreviewCandidate, preview_path: Path) -> Path | None:
        # Scroll ảnh vào viewport trước khi tìm nút — vì nút action nằm ngay cạnh ảnh
        try:
            candidate.locator.scroll_into_view_if_needed(timeout=5_000)
            page.wait_for_timeout(400)
        except Exception:
            pass

        action_root = self._find_response_actions_root(candidate)
        direct_selectors = [
            'button[aria-label*="Tải hình ảnh có kích thước đầy đủ xuống" i]',
            'button[aria-label*="Download full size" i]',
            'button[aria-label*="download" i]',
            'button[aria-label*="tải" i]',
            'button[aria-label*="lưu" i]',
            'button[aria-label*="save" i]',
            '[role="button"][aria-label*="Tải hình ảnh có kích thước đầy đủ xuống" i]',
            '[role="button"][aria-label*="Download full size" i]',
            '[role="button"][aria-label*="download" i]',
            '[role="button"][aria-label*="tải" i]',
            '[role="button"][aria-label*="lưu" i]',
            '[role="button"][aria-label*="save" i]',
            'a[download]',
        ]
        if action_root is not None:
            for selector in direct_selectors:
                try:
                    locator = action_root.locator(selector)
                    count = locator.count()
                except Exception:
                    count = 0
                for index in range(min(count, 8)):
                    button = locator.nth(index)
                    try:
                        # Scroll nút vào viewport thay vì bỏ qua khi không thấy
                        button.scroll_into_view_if_needed(timeout=3_000)
                        page.wait_for_timeout(200)
                        if button.is_disabled():
                            continue
                    except Exception:
                        continue
                    downloaded_path = self._download_via_button(page, button, preview_path)
                    if downloaded_path is not None:
                        return downloaded_path

        # Try to find download button inside or near the candidate locator (image overlay)
        for selector in direct_selectors:
            try:
                locator = candidate.locator.locator(f"xpath=ancestor::*[1]//{selector}").first
                if locator.count() > 0 and locator.is_visible() and not locator.is_disabled():
                    downloaded_path = self._download_via_button(page, locator, preview_path)
                    if downloaded_path is not None:
                        return downloaded_path
            except Exception:
                pass
            try:
                # Also try looking broadly in the whole page if there's only 1 matching the candidate's block
                # but it's safer to just check candidate's parent
                parent_locator = candidate.locator.locator("xpath=ancestor::div[contains(@class, 'image') or contains(@class, 'preview')][1]")
                if parent_locator.count() > 0:
                    locator = parent_locator.locator(selector).first
                    if locator.count() > 0 and locator.is_visible() and not locator.is_disabled():
                        downloaded_path = self._download_via_button(page, locator, preview_path)
                        if downloaded_path is not None:
                            return downloaded_path
            except Exception:
                pass

        menu_buttons = []
        if action_root is not None:
            menu_buttons.append(action_root.locator('button[data-test-id="more-menu-button"]').first)
            menu_buttons.append(action_root.locator('button[aria-label*="tuỳ chọn" i]').first)
            menu_buttons.append(action_root.locator('button[aria-label*="more" i]').first)

        for menu_button in menu_buttons:
            try:
                if menu_button.count() <= 0 or not menu_button.is_visible():
                    continue
                menu_button.click()
                page.wait_for_timeout(250)
            except Exception:
                continue

            menu_selectors = [
                "[role='menuitem']",
                ".mat-mdc-menu-item",
                "button",
                "[role='button']",
            ]
            for selector in menu_selectors:
                locator = page.locator(selector)
                try:
                    count = locator.count()
                except Exception:
                    count = 0
                for index in range(min(count, 80)):
                    item = locator.nth(index)
                    try:
                        if not item.is_visible() or item.is_disabled():
                            continue
                        text_blob = self._button_text_blob(item)
                        if not text_blob or ("download" not in text_blob and "tải" not in text_blob and "tai" not in text_blob and "lưu" not in text_blob and "luu" not in text_blob and "save" not in text_blob):
                            continue
                    except Exception:
                        continue
                    downloaded_path = self._download_via_button(page, item, preview_path)
                    if downloaded_path is not None:
                        return downloaded_path
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass

        return None

    def _click_copy_action_for_candidate(self, page, candidate: _PreviewCandidate) -> bool:
        action_root = self._find_response_actions_root(candidate)
        direct_selectors = [
            'button[aria-label*="copy" i]',
            'button[aria-label*="sao ch" i]',
            '[role="button"][aria-label*="copy" i]',
            '[role="button"][aria-label*="sao ch" i]',
        ]
        if action_root is not None:
            for selector in direct_selectors:
                try:
                    locator = action_root.locator(selector)
                    count = locator.count()
                except Exception:
                    count = 0
                for index in range(min(count, 6)):
                    button = locator.nth(index)
                    try:
                        if not button.is_visible() or button.is_disabled():
                            continue
                        button.click()
                        page.wait_for_timeout(250)
                        return True
                    except Exception:
                        continue

        menu_buttons = []
        if action_root is not None:
            menu_buttons.append(action_root.locator('button[data-test-id="more-menu-button"]').first)
            menu_buttons.append(action_root.locator('button[aria-label*="tuỳ chọn" i]').first)
            menu_buttons.append(action_root.locator('button[aria-label*="more" i]').first)

        for menu_button in menu_buttons:
            try:
                if menu_button.count() <= 0 or not menu_button.is_visible():
                    continue
                menu_button.click()
                page.wait_for_timeout(250)
                if self._click_visible_menu_action(page, ["copy", "sao ch", "copiar"]):
                    return True
            except Exception:
                continue

        return False

    def _click_visible_menu_action(self, page, tokens: list[str]) -> bool:
        selectors = [
            "[role='menuitem']",
            ".mat-mdc-menu-item",
            "button",
            "[role='button']",
        ]
        best = None
        best_score = float("-inf")
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                count = 0
            for index in range(min(count, 80)):
                item = locator.nth(index)
                try:
                    if not item.is_visible() or item.is_disabled():
                        continue
                    text_blob = self._button_text_blob(item)
                    if not text_blob:
                        continue
                    matched = [token for token in tokens if token in text_blob]
                    if not matched:
                        continue
                    box = item.bounding_box()
                    if not box or box["width"] < 60 or box["height"] < 24:
                        continue
                    score = len(matched) * 100.0 + min(box["width"], 260) * 0.05
                    if score > best_score:
                        best = item
                        best_score = score
                except Exception:
                    continue

        if best is None:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return False

        try:
            best.click()
            page.wait_for_timeout(300)
            return True
        except Exception:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    def _read_copy_confirmation_message(self, page) -> str | None:
        try:
            message = page.evaluate(
                """() => {
                    const selectors = [
                        '[role="status"]',
                        '[role="alert"]',
                        '[aria-live]',
                        'snack-bar-container',
                        '.mat-mdc-snack-bar-container',
                        '.toast',
                        '[data-testid*="toast" i]',
                    ];
                    const nodes = Array.from(document.querySelectorAll(selectors.join(',')));
                    const isVisible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    for (const el of nodes) {
                        if (!isVisible(el)) continue;
                        const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                        if (text) return text;
                    }
                    return null;
                }"""
            )
        except Exception:
            return None

        if message is None:
            return None

        text = str(message).strip()
        if not text:
            return None

        normalized = self._normalize_ui_text(text)
        copy_markers = (
            "copied",
            "copy to clipboard",
            "copied to clipboard",
            "sao chep",
            "da sao chep",
            "da duoc sao chep",
            "hinh anh da duoc sao chep",
        )
        if any(marker in normalized for marker in copy_markers):
            return text
        return None

    def _wait_for_copy_confirmation(
        self,
        page,
        previous_signature: str | None,
        *,
        timeout_ms: int = 4_000,
    ) -> tuple[bool, tuple[bytes, str] | None]:
        deadline = time.monotonic() + (timeout_ms / 1000)
        saw_confirmation = False
        latest_payload: tuple[bytes, str] | None = None

        while time.monotonic() < deadline:
            latest_payload = self._read_image_from_clipboard(page)
            signature = self._image_payload_signature(latest_payload)
            if signature and signature != previous_signature:
                page.wait_for_timeout(200)
                return True, latest_payload

            if self._read_copy_confirmation_message(page):
                saw_confirmation = True
                page.wait_for_timeout(350)
                latest_payload = self._read_image_from_clipboard(page)
                signature = self._image_payload_signature(latest_payload)
                if signature and signature != previous_signature:
                    return True, latest_payload
                return True, latest_payload

            page.wait_for_timeout(150)

        return saw_confirmation, latest_payload

    def _read_image_from_clipboard(self, page) -> tuple[bytes, str] | None:
        try:
            payload = page.evaluate(
                """async () => {
                    const toBase64 = (buffer) => {
                        const bytes = new Uint8Array(buffer);
                        const chunkSize = 0x8000;
                        let binary = '';
                        for (let index = 0; index < bytes.length; index += chunkSize) {
                            const slice = bytes.subarray(index, index + chunkSize);
                            binary += String.fromCharCode(...slice);
                        }
                        return btoa(binary);
                    };

                    if (!navigator.clipboard?.read) return null;
                    try {
                        const items = await navigator.clipboard.read();
                        for (const item of items) {
                            for (const type of item.types) {
                                if (!type.startsWith('image/')) continue;
                                const blob = await item.getType(type);
                                const buffer = await blob.arrayBuffer();
                                return {
                                    data: toBase64(buffer),
                                    contentType: blob.type,
                                };
                            }
                        }
                    } catch (_error) {
                        return null;
                    }
                    return null;
                }"""
            )
        except Exception:
            return None

        if not isinstance(payload, dict):
            return None
        encoded = str(payload.get("data") or "").strip()
        content_type = str(payload.get("contentType") or "").strip()
        if not encoded:
            return None
        try:
            return base64.b64decode(encoded), content_type
        except Exception:
            return None

    def _image_payload_signature(self, payload: tuple[bytes, str] | None) -> str | None:
        if not payload:
            return None
        image_bytes, content_type = payload
        if not image_bytes:
            return None
        digest = hashlib.sha256(image_bytes).hexdigest()
        normalized_type = str(content_type or "").strip().lower()
        return f"{normalized_type}:{len(image_bytes)}:{digest}"

    def _wait_for_changed_clipboard_image(
        self,
        page,
        previous_signature: str | None,
        *,
        timeout_ms: int = 2_500,
    ) -> tuple[bytes, str] | None:
        if previous_signature is None:
            return None

        deadline = time.monotonic() + (timeout_ms / 1000)
        while time.monotonic() < deadline:
            payload = self._read_image_from_clipboard(page)
            signature = self._image_payload_signature(payload)
            if signature and signature != previous_signature:
                return payload
            page.wait_for_timeout(150)
        return None

    def _upload_image_payload_into_prompt(
        self,
        page,
        payload: tuple[bytes, str],
        baseline_keys: set[str],
    ) -> _PreviewCandidate:
        image_bytes, content_type = payload
        suffix = ".png"
        lowered_type = str(content_type or "").lower()
        if "jpeg" in lowered_type or "jpg" in lowered_type:
            suffix = ".jpg"
        elif "webp" in lowered_type:
            suffix = ".webp"
        elif "gif" in lowered_type:
            suffix = ".gif"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            temp_path = Path(handle.name)
        try:
            temp_path.write_bytes(image_bytes)
            self._upload_input_image(page, temp_path)
            return self._wait_for_new_uploaded_preview(page, baseline_keys)
        finally:
            temp_path.unlink(missing_ok=True)

    def _paste_clipboard_image_into_prompt(
        self,
        page,
        *,
        previous_clipboard_signature: str | None = None,
        fallback_payload: tuple[bytes, str] | None = None,
        skip_clipboard_paste: bool = False,
    ) -> _PreviewCandidate:
        target = self._find_prompt_target(page)
        if target is None:
            raise GeminiWebError("Khong tim thay o nhap prompt de paste anh vao Gemini.")

        baseline_keys = self._collect_uploaded_preview_keys(page)
        try:
            target.click()
        except Exception:
            pass

        if skip_clipboard_paste:
            if fallback_payload is not None:
                return self._upload_image_payload_into_prompt(page, fallback_payload, baseline_keys)
            raise GeminiWebError("Khong co fallback payload de upload vao Gemini.")

        modifier = "Meta+V" if sys.platform == "darwin" else "Control+V"
        try:
            page.keyboard.press(modifier)
            return self._wait_for_new_uploaded_preview(page, baseline_keys)
        except Exception:
            clipboard_image = self._wait_for_changed_clipboard_image(
                page,
                previous_clipboard_signature,
            )
            if clipboard_image is not None:
                return self._upload_image_payload_into_prompt(page, clipboard_image, baseline_keys)
            if fallback_payload is not None:
                return self._upload_image_payload_into_prompt(page, fallback_payload, baseline_keys)
            raise GeminiWebError("Khong doc duoc image moi tu clipboard sau khi bam copy.")

    def _click_stop_button(self, page, composer) -> bool:
        selectors = [
            'button[aria-label*="dừng" i]',
            'button[aria-label*="stop" i]',
            '[role="button"][aria-label*="dừng" i]',
            '[role="button"][aria-label*="stop" i]',
            'button[data-testid*="stop" i]',
            'button[class*="stop" i]',
        ]
        for _ in range(16):
            for selector in selectors:
                locator = page.locator(selector)
                try:
                    count = locator.count()
                except Exception:
                    count = 0
                for index in range(min(count, 8)):
                    button = locator.nth(index)
                    try:
                        if not button.is_visible() or button.is_disabled():
                            continue
                        button.click()
                        return True
                    except Exception:
                        continue
            page.wait_for_timeout(250)
        return False

    def _capture_via_copy_roundtrip(self, page, candidate: _PreviewCandidate, preview_path: Path) -> Path | None:
        try:
            clipboard_before = self._read_image_from_clipboard(page)
            clipboard_before_signature = self._image_payload_signature(clipboard_before)
            copied = self._click_copy_action_for_candidate(page, candidate)
            if not copied:
                return None
            _, clipboard_after_copy = self._wait_for_copy_confirmation(
                page,
                clipboard_before_signature,
            )
            fallback_payload = clipboard_after_copy
            if fallback_payload is None:
                fallback_payload = self._fetch_candidate_image_payload(page, candidate)

            uploaded_candidate = self._paste_clipboard_image_into_prompt(
                page,
                previous_clipboard_signature=clipboard_before_signature,
                fallback_payload=fallback_payload,
                skip_clipboard_paste=False,
            )

            downloaded_path = self._download_candidate_image(page, uploaded_candidate, preview_path)
            if downloaded_path is not None:
                return downloaded_path

            send_baseline_candidates = self._collect_uploaded_preview_candidates(page)
            send_baseline_keys = {item.key for item in send_baseline_candidates}
            baseline_sent_y_bottom = max(
                (
                    item.y_bottom
                    for item in send_baseline_candidates
                    if not self._is_candidate_in_composer_area(page, item)
                ),
                default=None,
            )
            composer = self._find_prompt_target(page)
            self._dismiss_transient_overlays(page)
            sent = self._click_send_button(page, composer)
            if not sent:
                try:
                    page.keyboard.press("Enter")
                except Exception:
                    pass

            sent_candidate = self._wait_for_sent_uploaded_preview(
                page,
                send_baseline_keys,
                uploaded_candidate,
                minimum_y_bottom=baseline_sent_y_bottom,
                stable_samples=1,
            )
            if sent_candidate is None:
                return None

            page.wait_for_timeout(250)
            capture_candidate = sent_candidate

            downloaded_path = self._download_candidate_image(page, capture_candidate, preview_path)
            if downloaded_path is not None:
                return downloaded_path

            downloaded_path = self._download_candidate_via_response_action(page, capture_candidate, preview_path)
            if downloaded_path is not None:
                return downloaded_path
        except Exception:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return None
        return None

    def _capture_preview(self, page, candidate: _PreviewCandidate, preview_path: Path) -> Path:
        # Bước 1: Thử tải trực tiếp từ ảnh gốc Gemini mới sinh (không cần roundtrip)
        # Scroll ảnh vào màn hình, bấm nút "Tải hình ảnh có kích thước đầy đủ xuống"
        direct_path = self._download_candidate_via_response_action(page, candidate, preview_path)
        if direct_path is not None:
            return direct_path

        # Thử lấy bytes của ảnh gốc trực tiếp qua URL (blob / network)
        direct_path = self._download_candidate_image(page, candidate, preview_path)
        if direct_path is not None:
            return direct_path

        # Bước 2: Nếu không tải được trực tiếp, mới dùng flow copy → paste → gửi → tải lại
        roundtrip_path = self._capture_via_copy_roundtrip(page, candidate, preview_path)
        if roundtrip_path is not None:
            return roundtrip_path

        raise GeminiWebError("Khong the tai anh: da thu tai truc tiep va copy-roundtrip nhung deu that bai.")

    def _probe_image_size(self, image_path: Path) -> tuple[int, int] | None:
        if not self._ffprobe_path:
            return None

        try:
            completed = subprocess.run(
                [
                    self._ffprobe_path,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height",
                    "-of",
                    "json",
                    str(image_path),
                ],
                capture_output=True,
                check=True,
                text=True,
                timeout=20,
            )
            payload = json.loads(completed.stdout or "{}")
            streams = payload.get("streams") or []
            if not streams:
                return None
            width = int(streams[0].get("width") or 0)
            height = int(streams[0].get("height") or 0)
            if width <= 0 or height <= 0:
                return None
            return width, height
        except Exception:
            return None

    def _read_rgb_frame(self, image_path: Path, width: int, height: int) -> bytes | None:
        if not self._ffmpeg_path:
            return None

        try:
            completed = subprocess.run(
                [
                    self._ffmpeg_path,
                    "-v",
                    "error",
                    "-i",
                    str(image_path),
                    "-frames:v",
                    "1",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-",
                ],
                capture_output=True,
                check=True,
                timeout=30,
            )
        except Exception:
            return None

        expected_size = width * height * 3
        payload = completed.stdout or b""
        if len(payload) != expected_size:
            return None
        return payload

    def _estimate_background_color(self, rgb_bytes: bytes, width: int, height: int) -> tuple[int, int, int]:
        sample_span = max(6, min(18, min(width, height) // 12 or 6))
        points: list[tuple[int, int, int]] = []
        x_ranges = (
            range(0, min(sample_span, width)),
            range(max(0, width - sample_span), width),
        )
        y_ranges = (
            range(0, min(sample_span, height)),
            range(max(0, height - sample_span), height),
        )
        for xs in x_ranges:
            for ys in y_ranges:
                for y in ys:
                    row_offset = y * width * 3
                    for x in xs:
                        offset = row_offset + x * 3
                        points.append(
                            (
                                rgb_bytes[offset],
                                rgb_bytes[offset + 1],
                                rgb_bytes[offset + 2],
                            )
                        )

        if not points:
            return 255, 255, 255

        def _median(values: list[int]) -> int:
            ordered = sorted(values)
            return int(ordered[len(ordered) // 2])

        return (
            _median([item[0] for item in points]),
            _median([item[1] for item in points]),
            _median([item[2] for item in points]),
        )

    def _build_foreground_ratios(
        self,
        rgb_bytes: bytes,
        width: int,
        height: int,
        background: tuple[int, int, int],
    ) -> tuple[list[float], list[float]]:
        delta_threshold = 22
        sample_x_step = max(1, width // 480)
        sample_y_step = max(1, height // 480)
        bg_r, bg_g, bg_b = background

        row_ratios: list[float] = []
        for y in range(height):
            changed = 0
            total = 0
            row_offset = y * width * 3
            for x in range(0, width, sample_x_step):
                offset = row_offset + x * 3
                if max(
                    abs(rgb_bytes[offset] - bg_r),
                    abs(rgb_bytes[offset + 1] - bg_g),
                    abs(rgb_bytes[offset + 2] - bg_b),
                ) > delta_threshold:
                    changed += 1
                total += 1
            row_ratios.append(changed / max(total, 1))

        col_ratios: list[float] = []
        for x in range(width):
            changed = 0
            total = 0
            for y in range(0, height, sample_y_step):
                offset = (y * width + x) * 3
                if max(
                    abs(rgb_bytes[offset] - bg_r),
                    abs(rgb_bytes[offset + 1] - bg_g),
                    abs(rgb_bytes[offset + 2] - bg_b),
                ) > delta_threshold:
                    changed += 1
                total += 1
            col_ratios.append(changed / max(total, 1))

        return row_ratios, col_ratios

    def _find_dominant_segment(
        self,
        ratios: list[float],
        *,
        threshold: float,
        gap_tolerance: int,
        min_coverage: float,
    ) -> tuple[int, int] | None:
        if not ratios:
            return None

        minimum_length = max(8, int(len(ratios) * min_coverage))
        segments: list[tuple[int, int]] = []
        start: int | None = None
        gap_count = 0

        for index, value in enumerate(ratios):
            active = value >= threshold
            if start is None:
                if active:
                    start = index
                    gap_count = 0
                continue

            if active:
                gap_count = 0
                continue

            gap_count += 1
            if gap_count > gap_tolerance:
                end = index - gap_count
                if end >= start:
                    segments.append((start, end))
                start = None
                gap_count = 0

        if start is not None:
            end = len(ratios) - 1 - gap_count
            if end >= start:
                segments.append((start, end))

        best_segment: tuple[int, int] | None = None
        best_score = -1.0
        for segment_start, segment_end in segments:
            length = segment_end - segment_start + 1
            if length < minimum_length:
                continue
            average_density = sum(ratios[segment_start:segment_end + 1]) / length
            score = length * max(average_density, threshold)
            if score > best_score:
                best_segment = (segment_start, segment_end)
                best_score = score
        return best_segment

    def _detect_content_crop(self, image_path: Path) -> tuple[int, int, int, int] | None:
        size = self._probe_image_size(image_path)
        if not size:
            return None
        width, height = size
        if width < 200 or height < 200:
            return None

        rgb_bytes = self._read_rgb_frame(image_path, width, height)
        if not rgb_bytes:
            return None

        background = self._estimate_background_color(rgb_bytes, width, height)
        row_ratios, col_ratios = self._build_foreground_ratios(rgb_bytes, width, height, background)
        row_segment = self._find_dominant_segment(
            row_ratios,
            threshold=0.02,
            gap_tolerance=max(6, height // 90),
            min_coverage=0.45,
        )
        col_segment = self._find_dominant_segment(
            col_ratios,
            threshold=0.02,
            gap_tolerance=max(4, width // 120),
            min_coverage=0.45,
        )
        if not row_segment or not col_segment:
            return None

        top, bottom = row_segment
        left, right = col_segment
        padding = max(1, min(4, min(width, height) // 160 or 1))
        left = max(0, left - padding)
        top = max(0, top - padding)
        right = min(width - 1, right + padding)
        bottom = min(height - 1, bottom + padding)

        cropped_width = right - left + 1
        cropped_height = bottom - top + 1
        if cropped_width <= 0 or cropped_height <= 0:
            return None

        trim_left = left
        trim_top = top
        trim_right = width - 1 - right
        trim_bottom = height - 1 - bottom
        min_trim = max(8, int(min(width, height) * 0.02))
        if max(trim_left, trim_top, trim_right, trim_bottom) < min_trim:
            return None

        retained_area = cropped_width * cropped_height
        if retained_area < int(width * height * 0.55):
            return None

        return left, top, cropped_width, cropped_height

    def _write_cropped_image(
        self,
        source_path: Path,
        target_path: Path,
        crop_box: tuple[int, int, int, int],
    ) -> bool:
        if not self._ffmpeg_path:
            return False

        crop_x, crop_y, crop_width, crop_height = crop_box
        target_path.parent.mkdir(parents=True, exist_ok=True)
        output_path = target_path
        temp_path: Path | None = None

        if source_path.resolve() == target_path.resolve():
            temp_path = target_path.with_name(f"{target_path.stem}.cropped{target_path.suffix}")
            output_path = temp_path

        command = [
            self._ffmpeg_path,
            "-y",
            "-v",
            "error",
            "-i",
            str(source_path),
            "-vf",
            f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y}",
            "-frames:v",
            "1",
        ]
        if output_path.suffix.lower() in {".jpg", ".jpeg"}:
            command.extend(["-q:v", "2"])
        command.append(str(output_path))

        try:
            subprocess.run(command, capture_output=True, check=True, timeout=30)
            if not output_path.exists() or output_path.stat().st_size == 0:
                return False
            if temp_path is not None:
                temp_path.replace(target_path)
            return True
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            return False

    def _normalize_preview(self, preview_path: Path, normalized_path: Path) -> Path:
        resolved_normalized_path = normalized_path.with_suffix(preview_path.suffix or normalized_path.suffix)
        crop_box = self._detect_content_crop(preview_path)
        if crop_box and self._write_cropped_image(preview_path, resolved_normalized_path, crop_box):
            if resolved_normalized_path.stat().st_size == 0:
                raise GeminiWebError("Normalize image that bai: file rong.")
            return resolved_normalized_path

        if preview_path.resolve() == resolved_normalized_path.resolve():
            if preview_path.stat().st_size == 0:
                raise GeminiWebError("Normalize image that bai: file rong.")
            return preview_path

        resolved_normalized_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(preview_path, resolved_normalized_path)
        if resolved_normalized_path.stat().st_size == 0:
            raise GeminiWebError("Normalize image that bai: file rong.")
        return resolved_normalized_path
