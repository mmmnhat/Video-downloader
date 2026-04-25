from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.cookiejar import Cookie, CookieJar
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from urllib.parse import urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from downloader_app.browser_session import browser_session
from downloader_app.jobs import build_sheet_sequence_stem, sanitize_file_stem, utc_now
from downloader_app.runtime import app_path
from downloader_app.tts_sheet import SheetTextEntry, scan_text_sheet


ELEVENLABS_LOGIN_URL = "https://elevenlabs.io/app/sign-in?redirect=%2Fapp%2Fspeech-synthesis%2Ftext-to-speech"
ELEVENLABS_TTS_URL = "https://elevenlabs.io/app/speech-synthesis/text-to-speech"
TTS_BATCH_ROOT = app_path("tts_batches")
TTS_STATE_FILE = app_path("tts_state.json")
TTS_PROFILE_ROOT = app_path("tts_profiles")
TTS_RUNTIME_ROOT = TTS_PROFILE_ROOT / "runtime"
FINAL_BATCH_STATUSES = {"completed", "completed_with_errors", "cancelled"}
ACTIVE_BATCH_STATUSES = {"queued", "running", "cancelling"}
TTS_AUTH_DOMAIN = "elevenlabs.io"
TTS_PROFILE_ROOT_ITEMS = ("Local State",)
TTS_PROFILE_ITEMS = (
    "Cookies",
    "Network",
    "Local Storage",
    "Session Storage",
    "Preferences",
    "Secure Preferences",
    "Network Persistent State",
)
TTS_GENERATE_DISABLE_TIMEOUT_MS = 3_000
TTS_GENERATE_COMPLETE_TIMEOUT_MS = 20_000
TTS_DOWNLOAD_WAIT_TIMEOUT_MS = 8_000
TTS_EXPECT_DOWNLOAD_TIMEOUT_MS = 15_000
TTS_UI_SETTLE_TIMEOUT_MS = 8_000
TTS_MAX_WORKERS = 6
ELEVENLABS_VOICE_API_URLS = (
    "https://api.elevenlabs.io/v1/voices?show_legacy=false",
    "https://api.us.elevenlabs.io/v1/voices?show_legacy=false",
    "https://api.eu.elevenlabs.io/v1/voices?show_legacy=false",
)


@dataclass(frozen=True)
class TtsBrowserCandidate:
    name: str
    app_path: Path
    executable_path: Path
    user_data_dir: Path


@dataclass(frozen=True)
class TtsBrowserProfile:
    name: str
    app_path: Path
    executable_path: Path
    user_data_dir: Path
    profile_dir: Path

    @property
    def profile_name(self) -> str:
        return self.profile_dir.name


def _get_browser_candidates() -> list[TtsBrowserCandidate]:
    candidates = []
    if sys.platform == "win32":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
        program_files = Path(os.environ.get("ProgramFiles", "C:\\Program Files"))
        program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"))

        # CocCoc
        for coc_path in (program_files, program_files_x86, local_app_data):
            candidates.append(
                TtsBrowserCandidate(
                    name="CocCoc",
                    app_path=coc_path / "CocCoc/Browser/Application",
                    executable_path=coc_path / "CocCoc/Browser/Application/browser.exe",
                    user_data_dir=local_app_data / "CocCoc/Browser/User Data",
                )
            )
        # Chrome
        chrome_paths = [
            (program_files / "Google/Chrome/Application", program_files / "Google/Chrome/Application/chrome.exe"),
            (program_files_x86 / "Google/Chrome/Application", program_files_x86 / "Google/Chrome/Application/chrome.exe"),
            (local_app_data / "Google/Chrome/Application", local_app_data / "Google/Chrome/Application/chrome.exe"),
        ]
        for app_p, exe_p in chrome_paths:
            candidates.append(
                TtsBrowserCandidate(
                    name="Chrome",
                    app_path=app_p,
                    executable_path=exe_p,
                    user_data_dir=local_app_data / "Google/Chrome/User Data",
                )
            )
        # Edge
        edge_paths = [
            (program_files_x86 / "Microsoft/Edge/Application", program_files_x86 / "Microsoft/Edge/Application/msedge.exe"),
            (program_files / "Microsoft/Edge/Application", program_files / "Microsoft/Edge/Application/msedge.exe"),
        ]
        for app_p, exe_p in edge_paths:
            candidates.append(
                TtsBrowserCandidate(
                    name="Edge",
                    app_path=app_p,
                    executable_path=exe_p,
                    user_data_dir=local_app_data / "Microsoft/Edge/User Data",
                )
            )
    else:
        # macOS paths
        candidates.extend([
            TtsBrowserCandidate(
                name="CocCoc",
                app_path=Path("/Applications/CocCoc.app"),
                executable_path=Path("/Applications/CocCoc.app/Contents/MacOS/CocCoc"),
                user_data_dir=Path.home() / "Library/Application Support/CocCoc/Browser",
            ),
            TtsBrowserCandidate(
                name="Chrome",
                app_path=Path("/Applications/Google Chrome.app"),
                executable_path=Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                user_data_dir=Path.home() / "Library/Application Support/Google/Chrome",
            ),
            TtsBrowserCandidate(
                name="Edge",
                app_path=Path("/Applications/Microsoft Edge.app"),
                executable_path=Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                user_data_dir=Path.home() / "Library/Application Support/Microsoft Edge",
            ),
        ])
    return candidates


TTS_BROWSER_CANDIDATES = _get_browser_candidates()


class ElevenLabsError(RuntimeError):
    pass


class ElevenLabsAuthError(ElevenLabsError):
    pass


def _looks_like_elevenlabs_voice_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9]{16,32}", value.strip()))


def _is_my_voice_entry(voice: dict) -> bool:
    is_owner = voice.get("is_owner")
    if isinstance(is_owner, bool):
        return is_owner
    is_owner_camel = voice.get("isOwner")
    if isinstance(is_owner_camel, bool):
        return is_owner_camel

    category = str(voice.get("category", "")).strip().lower()
    if not category:
        return False
    if category in {"premade", "professional"}:
        return False

    sharing = voice.get("sharing")
    if isinstance(sharing, dict):
        sharing_status = str(sharing.get("status", "")).strip().lower()
        if sharing_status == "copied":
            return True

    return category in {"generated", "cloned", "designed", "voice_design"}


def _is_elevenlabs_api_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.netloc or "").strip().lower()
    if not host:
        return False
    return host.startswith("api") and host.endswith("elevenlabs.io")


def _is_elevenlabs_voices_url(url: str) -> bool:
    if not _is_elevenlabs_api_url(url):
        return False
    try:
        path = urlparse(url).path.lower()
    except Exception:
        return False
    return "/voices" in path


def _voice_query_variants(query: str) -> list[str]:
    raw = query.strip()
    if not raw:
        return []

    variants: list[str] = []

    def add(value: str) -> None:
        normalized = value.strip()
        if normalized and normalized not in variants:
            variants.append(normalized)

    add(raw)

    primary_name = re.split(r"\s*[-–—|•]\s*", raw, maxsplit=1)[0]
    add(primary_name)

    first_clause = raw.split(",", 1)[0]
    add(first_clause)

    tokens = re.findall(r"[A-Za-z0-9]+", raw)
    if tokens:
        add(tokens[0])
        if len(tokens) >= 2:
            add(" ".join(tokens[:2]))

    return variants


def _query_match_patterns(query: str) -> list[re.Pattern[str]]:
    variants = _voice_query_variants(query)
    patterns: list[re.Pattern[str]] = []

    for variant in variants:
        parts = [part for part in re.findall(r"[A-Za-z0-9]+", variant) if part]
        patterns.append(re.compile(re.escape(variant), re.I))
        if len(parts) >= 2:
            patterns.append(re.compile(r"[\s\S]*?".join(re.escape(part) for part in parts), re.I))

    return patterns


def _format_exception_message(exc: Exception) -> str:
    detail = str(exc).strip()
    if detail:
        return detail
    return exc.__class__.__name__


@dataclass
class TtsTake:
    id: str
    take_index: int
    take_label: str
    output_name: str
    status: str = "queued"
    output_path: str | None = None
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


@dataclass
class TtsItem:
    id: str
    sequence_label: str
    row_number: int
    text: str
    status: str = "queued"
    picked_take_id: str | None = None
    takes: list[TtsTake] = field(default_factory=list)
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


@dataclass
class TtsBatch:
    id: str
    created_at: str
    last_updated_at: str
    status: str
    sheet_url: str
    sheet_id: str
    gid: str | None
    sheet_access_mode: str
    text_column: str
    voice_query: str
    voice_id: str | None
    voice_name: str | None
    model_family: str
    tag_text: str
    take_count: int
    retry_count: int
    worker_count: int
    headless: bool
    work_dir: str
    filename_prefix: str | None = None
    channel_prefix: str | None = None
    items: list[TtsItem] = field(default_factory=list)


def _ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _clamp_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _prompt_with_tag(text: str, model_family: str, tag_text: str) -> str:
    if model_family.lower() != "v3":
        return text
    tag = tag_text.strip()
    if not tag:
        return text
    return f"{tag} {text}".strip()


def _format_take_label(sequence_label: str, take_index: int, model_family: str) -> str:
    if model_family.lower() == "v3":
        return f"{sequence_label}.{take_index}"
    return str(take_index)


def _iter_take_outputs(take_count: int, model_family: str) -> list[tuple[int, str]]:
    if model_family.lower() == "v3":
        return [
            (take_index, f"{take_index}.{output_index}")
            for take_index in range(1, take_count + 1)
            for output_index in range(1, _outputs_per_generation(model_family) + 1)
        ]
    return [(take_index, str(take_index)) for take_index in range(1, take_count + 1)]


def _outputs_per_generation(model_family: str) -> int:
    return 2 if model_family.lower() == "v3" else 1


def _generation_download_selector() -> str:
    return (
        '[data-testid="tts-download-latest-button"], '
        '[data-testid*="download"], '
        'button[aria-label*="Download"], '
        'a[download], '
        'a[href*="download"], '
        'a[href*=".mp3"]'
    )


def _build_take_output_name(
    output_base: str,
    *,
    take_index: int,
    take_label: str,
    take_count: int,
    model_family: str,
) -> str:
    if model_family.lower() == "v3":
        if take_count == 1:
            output_suffix = take_label.split(".", 1)[-1]
            return f"{output_base}.{output_suffix}.mp3"
        return f"{output_base}.{take_label}.mp3"
    if take_count == 1:
        return f"{output_base}.mp3"
    return f"{output_base}.{take_index}.mp3"


def _copy_with_unique_name(source: Path, destination_dir: Path, preferred_name: str) -> Path:
    stem = sanitize_file_stem(Path(preferred_name).stem) or "audio"
    suffix = Path(preferred_name).suffix or source.suffix or ".mp3"
    destination = destination_dir / f"{stem}{suffix}"
    counter = 2
    while destination.exists():
        destination = destination_dir / f"{stem}-{counter}{suffix}"
        counter += 1
    shutil.copy2(source, destination)
    return destination


def _tts_debug(message: str) -> None:
    print(f"[TTS] {message}", flush=True)


def _available_browser_candidates() -> list[TtsBrowserCandidate]:
    available = []
    for candidate in TTS_BROWSER_CANDIDATES:
        app_exists = candidate.app_path.exists()
        exe_exists = candidate.executable_path.exists()
        data_exists = candidate.user_data_dir.exists()
        _tts_debug(f"Checking browser {candidate.name}: app={app_exists}, exe={exe_exists}, data={data_exists}")
        _tts_debug(f"  App: {candidate.app_path}")
        _tts_debug(f"  Exe: {candidate.executable_path}")
        _tts_debug(f"  Data: {candidate.user_data_dir}")
        if app_exists and exe_exists and data_exists:
            available.append(candidate)
    return available


def _iter_profile_dirs(user_data_dir: Path) -> list[Path]:
    default_profile = user_data_dir / "Default"
    other_profiles = sorted(path for path in user_data_dir.glob("Profile *") if path.is_dir())
    guest_profile = user_data_dir / "Guest Profile"
    ordered = [default_profile, *other_profiles]
    if guest_profile.is_dir():
        ordered.append(guest_profile)
    return [path for path in ordered if path.is_dir()]


def _cookie_count_for_domain(cookie_path: Path, domain: str) -> int:
    if not cookie_path.exists():
        return 0

    temp_copy: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as handle:
            temp_copy = Path(handle.name)
        shutil.copy2(cookie_path, temp_copy)
        with sqlite3.connect(temp_copy) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM cookies WHERE host_key = ? OR host_key LIKE ?",
                (domain, f"%.{domain}"),
            ).fetchone()
    except Exception:
        return 0
    finally:
        if temp_copy is not None:
            try:
                temp_copy.unlink(missing_ok=True)
            except Exception:
                pass

    return int(row[0]) if row else 0


def _choose_profile_dir(user_data_dir: Path, domain: str = TTS_AUTH_DOMAIN) -> Path | None:
    profile_dirs = _iter_profile_dirs(user_data_dir)
    if not profile_dirs:
        return None

    def profile_cookie_count(profile_dir: Path) -> int:
        # Chromium cookie DB may exist at either:
        # - <profile>/Network/Cookies (modern)
        # - <profile>/Cookies (legacy)
        return max(
            _cookie_count_for_domain(profile_dir / "Network" / "Cookies", domain),
            _cookie_count_for_domain(profile_dir / "Cookies", domain),
        )

    ranked_profiles: list[tuple[int, Path]] = []
    for profile_dir in profile_dirs:
        ranked_profiles.append((profile_cookie_count(profile_dir), profile_dir))

    ranked_profiles.sort(key=lambda item: item[0], reverse=True)
    if ranked_profiles and ranked_profiles[0][0] > 0:
        return ranked_profiles[0][1]

    for profile_dir in profile_dirs:
        if profile_dir.name == "Default":
            return profile_dir
    return profile_dirs[0]


def detect_tts_browser_profile() -> TtsBrowserProfile:
    ranked_candidates: list[tuple[int, TtsBrowserProfile]] = []
    fallback_profiles: list[TtsBrowserProfile] = []

    for candidate in _available_browser_candidates():
        profile_dir = _choose_profile_dir(candidate.user_data_dir)
        if profile_dir is None:
            continue
        profile = TtsBrowserProfile(
            name=candidate.name,
            app_path=candidate.app_path,
            executable_path=candidate.executable_path,
            user_data_dir=candidate.user_data_dir,
            profile_dir=profile_dir,
        )
        cookie_count = max(
            _cookie_count_for_domain(profile_dir / "Network" / "Cookies", TTS_AUTH_DOMAIN),
            _cookie_count_for_domain(profile_dir / "Cookies", TTS_AUTH_DOMAIN),
        )
        if cookie_count > 0:
            ranked_candidates.append((cookie_count, profile))
        else:
            fallback_profiles.append(profile)

    if ranked_candidates:
        ranked_candidates.sort(key=lambda item: item[0], reverse=True)
        return ranked_candidates[0][1]

    if fallback_profiles:
        return fallback_profiles[0]

    raise ElevenLabsError(
        "Khong tim thay CocCoc/Chrome/Edge co the dung cho ElevenLabs tren may nay."
    )


def detect_tts_login_browser() -> TtsBrowserCandidate:
    candidates = _available_browser_candidates()
    if candidates:
        return candidates[0]
    raise ElevenLabsError(
        "Khong tim thay CocCoc/Chrome/Edge de mo ElevenLabs login."
    )


def _copy_profile_item(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def build_tts_runtime_profile(browser_profile: TtsBrowserProfile, runtime_id: str) -> Path:
    runtime_root = TTS_RUNTIME_ROOT / runtime_id
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    runtime_root.mkdir(parents=True, exist_ok=True)

    for item in TTS_PROFILE_ROOT_ITEMS:
        source = browser_profile.user_data_dir / item
        if source.exists():
            _copy_profile_item(source, runtime_root / item)

    runtime_profile_dir = runtime_root / browser_profile.profile_name
    runtime_profile_dir.mkdir(parents=True, exist_ok=True)
    for item in TTS_PROFILE_ITEMS:
        source = browser_profile.profile_dir / item
        if source.exists():
            _copy_profile_item(source, runtime_profile_dir / item)

    return runtime_root


class ElevenLabsAutomation:
    def __init__(self, downloads_dir: Path, *, headless: bool = False) -> None:
        self._downloads_dir = _ensure_directory(downloads_dir)
        self._headless = headless
        self._playwright = None
        self._context = None
        self._page = None
        self._browser_name = "Local browser"
        self._runtime_profile_dir: Path | None = None
        self._browser_profile: TtsBrowserProfile | None = None
        self._xi_api_key: str | None = None  # Captured from ElevenLabs request headers
        self._cached_custom_voices: list[dict] = []  # Captured directly from JSON responses during page load
    def __enter__(self) -> "ElevenLabsAutomation":
        try:
            from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, sync_playwright
        except ImportError as exc:  # pragma: no cover - dependency error
            if sys.platform == "win32":
                msg = (
                    f"Chua cai Playwright (Loi: {exc}). Hay chay `.venv\\Scripts\\pip install -r requirements.txt` "
                    "va `.venv\\Scripts\\python -m playwright install chromium`.\n"
                    "Luu y: Ban phai chay app bang python trong .venv (vi du: .venv\\Scripts\\python main.py)."
                )
            else:
                msg = (
                    f"Chua cai Playwright (Loi: {exc}). Hay chay `./.venv/bin/pip install -r requirements.txt` "
                    "va `./.venv/bin/python -m playwright install chromium`."
                )
            raise ElevenLabsError(msg) from exc

        self._playwright_error = PlaywrightError
        self._playwright_timeout = PlaywrightTimeoutError
        self._playwright = sync_playwright().start()
        self._browser_profile = detect_tts_browser_profile()
        runtime_id = f"{self._downloads_dir.name}-{uuid.uuid4().hex[:8]}"
        self._runtime_profile_dir = build_tts_runtime_profile(self._browser_profile, runtime_id)
        runtime_root = self._runtime_profile_dir
        runtime_selected_profile = runtime_root / self._browser_profile.profile_name

        def _launch_context(user_data_dir: Path, args: list[str] | None = None):
            launch_args = args if args is not None else []
            return self._playwright.chromium.launch_persistent_context(
                str(user_data_dir),
                headless=self._headless,
                accept_downloads=True,
                executable_path=str(self._browser_profile.executable_path),
                args=launch_args,
            )
        try:
            self._context = _launch_context(
                runtime_root,
                args=[f"--profile-directory={self._browser_profile.profile_name}"],
            )
            browser_name = self._browser_profile.name
        except PlaywrightError as primary_exc:
            # Some Chromium builds/profiles crash immediately when combining
            # --profile-directory with a copied runtime user-data-dir.
            # Retry by launching directly from the copied profile folder.
            try:
                if not runtime_selected_profile.exists():
                    raise primary_exc
                self._context = _launch_context(runtime_selected_profile, args=[])
                browser_name = self._browser_profile.name
                print(
                    f"[TTS] Retried launch without --profile-directory for {browser_name} and succeeded.",
                    flush=True,
                )
            except PlaywrightError as fallback_exc:
                self._playwright.stop()
                self._playwright = None
                raise ElevenLabsError(
                    f"{_format_exception_message(primary_exc)} | fallback failed: {_format_exception_message(fallback_exc)}"
                ) from fallback_exc

        self._browser_name = browser_name
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._page.set_default_timeout(20_000)

        # Capture xi-api-key from any ElevenLabs API request header
        def _capture_xi_key(request) -> None:
            if self._xi_api_key:
                return
            if _is_elevenlabs_api_url(request.url):
                key = request.headers.get("xi-api-key", "")
                if key and len(key) > 10:
                    self._xi_api_key = key
        self._context.on("request", _capture_xi_key)

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()
        if self._runtime_profile_dir is not None:
            shutil.rmtree(self._runtime_profile_dir, ignore_errors=True)

    def ensure_authenticated(self, wait_for_workspace: bool = True) -> None:
        assert self._page is not None
        print(f"[TTS] Accessing ElevenLabs TTS page (Browser: {self.browser_name})...", flush=True)

        # Attach request listener BEFORE navigation to capture xi-api-key from API calls during page load
        def _capture_key_on_load(request) -> None:
            if self._xi_api_key:
                return
            if _is_elevenlabs_api_url(request.url):
                key = request.headers.get("xi-api-key", "")
                if key and len(key) > 10:
                    self._xi_api_key = key
                    print(f"[TTS] Captured xi-api-key from page load.", flush=True)

        def _capture_voices_on_load(response) -> None:
            try:
                if response.status == 200 and response.request.resource_type in ["fetch", "xhr"]:
                    if _is_elevenlabs_voices_url(response.url):
                        body = response.json()
                        if isinstance(body, dict) and "voices" in body:
                            voices = body["voices"]
                            # Only capture custom voices (not premade) to simulate "My Voices"
                            custom_voices = [v for v in voices if _is_my_voice_entry(v)]
                            if custom_voices:
                                self._cached_custom_voices = custom_voices
                                print(f"[TTS] Captured {len(custom_voices)} custom voices from network.", flush=True)
            except Exception:
                pass

        self._page.on("request", _capture_key_on_load)
        self._page.on("response", _capture_voices_on_load)
        try:
            self._page.goto(ELEVENLABS_TTS_URL, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            print(f"[TTS] Page load warning: {exc}", flush=True)

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            current_url = self._page.url
            if "/sign-in" in current_url:
                raise ElevenLabsAuthError(
                    f"Chưa tìm thấy phiên ElevenLabs trong {self.browser_name}. Hãy đăng nhập ElevenLabs trong {self.browser_name} rồi bấm Làm mới phiên."
                )
            
            if hasattr(self, "_cached_custom_voices") and self._cached_custom_voices:
                if not wait_for_workspace:
                    print("[TTS] ElevenLabs cached voices ready, bypassing workspace wait.", flush=True)
                    return

            if self._has_ready_tts_workspace():
                if wait_for_workspace:
                    self._wait_for_idle_ui(timeout_ms=1000)
                    print("[TTS] ElevenLabs workspace ready.", flush=True)
                    return
                # If we are just fetching voices, wait a bit longer for the network to finish
                # but if we run out of time, we'll return anyway.
            
            self._page.wait_for_timeout(1000)
        
        # On failure, try to capture what happened
        try:
            title = self._page.title()
            print(f"[TTS] Failed to find workspace. Page title: '{title}', URL: {self._page.url}", flush=True)
            # You could save a screenshot here for local debugging if needed
        except Exception:
            pass
            
        raise ElevenLabsError("Khong mo duoc giao dien Text to Speech cua ElevenLabs. Co the do mang cham hoac trang web thay doi giao dien.")

    @property
    def browser_name(self) -> str:
        return self._browser_name

    def select_model(self, query: str) -> None:
        if not query.strip():
            return
        assert self._page is not None
        model_query = query.strip()
        self._ensure_settings_tab_open()
        self._wait_for_idle_ui()

        deadline = time.monotonic() + 10
        trigger = None
        while time.monotonic() < deadline:
            trigger = self._locate_model_trigger()
            if trigger is not None:
                break
            self._page.wait_for_timeout(300)
        if trigger is None:
            raise ElevenLabsError("Khong tim thay nut chon model tren ElevenLabs.")

        current_text = (trigger.inner_text() or "").strip().lower()
        current_aria = (trigger.get_attribute("aria-label") or "").strip().lower()
        if model_query.lower() in f"{current_text} {current_aria}".strip():
            return

        self._click_with_retries(trigger, description="model selector")
        self._page.wait_for_timeout(300)
        self._select_visible_option(model_query)
        self._wait_for_idle_ui()

    def select_voice(self, query: str) -> None:
        if not query.strip():
            return
        assert self._page is not None
        voice_query = query.strip()
        self._ensure_settings_tab_open()
        trigger = self._locate_voice_trigger()
        if trigger is None:
            raise ElevenLabsError("Khong tim thay nut chon voice tren ElevenLabs.")
        trigger.wait_for(state="visible")
        current_label = (trigger.inner_text() or "").strip().lower()
        if voice_query.lower() in current_label:
            return

        self._open_voice_picker(trigger)
        voices = self._fetch_available_voices(open_picker=False)
        resolved_query = self._resolve_voice_query(voice_query, voices=voices)
        if resolved_query.lower() in current_label:
            return

        search_input = self._find_voice_search_input()

        selection_queries: list[str] = []
        for candidate in [resolved_query, voice_query]:
            for variant in _voice_query_variants(candidate):
                if variant not in selection_queries:
                    selection_queries.append(variant)

        last_error: ElevenLabsError | None = None
        for selection_query in selection_queries:
            if search_input is not None:
                try:
                    search_input.fill(selection_query)
                    self._page.wait_for_timeout(500)
                except Exception:
                    pass
            try:
                self._select_visible_option(selection_query)
            except ElevenLabsError as exc:
                last_error = exc
                continue
            return

        if last_error is not None:
            raise last_error
        raise ElevenLabsError(f"Khong tim thay option `{resolved_query}` trong ElevenLabs picker.")

    def fill_text(self, text: str) -> None:
        assert self._page is not None
        editor = self._page.locator('[data-testid="tts-editor"]').first
        editor.wait_for(state="visible")
        editor.click()
        modifier = "Meta+A" if sys.platform == "darwin" else "Control+A"
        self._page.keyboard.press(modifier)
        self._page.keyboard.press("Backspace")
        self._page.keyboard.type(text, delay=5)

    def generate_and_download(self, output_path: Path) -> None:
        self.generate_and_download_many([output_path])

    def generate_and_download_many(self, output_paths: list[Path]) -> None:
        if not output_paths:
            return
        assert self._page is not None
        generate_button = self._locate_generate_button()
        if generate_button is None:
            raise ElevenLabsError("Khong tim thay nut generate tren ElevenLabs.")
        generate_button.wait_for(state="visible")
        self._click_with_retries(generate_button, description="generate button")

        try:
            self._page.wait_for_function(
                """
                () => {
                  const button = document.querySelector('[data-testid="tts-generate"]');
                  return !!button && button.disabled;
                }
                """,
                timeout=TTS_GENERATE_DISABLE_TIMEOUT_MS,
            )
        except self._playwright_timeout:
            pass

        try:
            self._page.wait_for_function(
                """
                () => {
                  const selectors = [
                    '[data-testid="tts-generate"]',
                    'button[aria-label*="Generate"]',
                    'button[data-slot="button"]',
                  ];
                  const generateButton = selectors
                    .flatMap((selector) => Array.from(document.querySelectorAll(selector)))
                    .find((el) => {
                      const text = (el.innerText || el.textContent || '').toLowerCase();
                      return text.includes('generate') || text.includes('regenerate') || (el.getAttribute('aria-label') || '').toLowerCase().includes('generate');
                    });
                  const downloadButtons = Array.from(
                    document.querySelectorAll(
                      '[data-testid="tts-download-latest-button"], [data-testid*="download"], button[aria-label*="Download"], a[download], a[href*="download"], a[href*=".mp3"]'
                    )
                  ).filter((el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                  });
                  const hasDownload = downloadButtons.length > 0;
                  const hasError = Array.from(document.querySelectorAll('body *')).some((el) => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) return false;
                    const text = (el.innerText || el.textContent || '').toLowerCase().trim();
                    if (!text || text.length > 240) return false;
                    return text.includes('error') || text.includes('failed') || text.includes('unable to') || text.includes('try again');
                  });
                  const generateReadyAgain = !!generateButton && !generateButton.disabled;
                  return hasDownload || hasError || generateReadyAgain;
                }
                """,
                timeout=TTS_GENERATE_COMPLETE_TIMEOUT_MS,
            )
        except self._playwright_timeout as exc:
            raise ElevenLabsError("Het thoi gian cho ElevenLabs gen audio.") from exc

        self._page.wait_for_timeout(800)
        download_buttons = self._wait_for_generation_download_buttons(expected_count=len(output_paths))
        if not download_buttons:
            fallback_button = self._locate_download_button()
            if fallback_button is not None:
                download_buttons = [fallback_button]

        if not download_buttons:
            page_error = self._extract_generation_error()
            if page_error:
                raise ElevenLabsError(page_error)
            raise ElevenLabsError("Da gen xong nhung khong tim thay nut download tren ElevenLabs.")

        if len(download_buttons) < len(output_paths):
            page_error = self._extract_generation_error()
            if page_error:
                raise ElevenLabsError(page_error)
            raise ElevenLabsError(
                f"Chi tim thay {len(download_buttons)} nut download cho {len(output_paths)} take."
            )

        for output_path, download_button in zip(output_paths, download_buttons):
            try:
                download_button.wait_for(state="visible", timeout=TTS_DOWNLOAD_WAIT_TIMEOUT_MS)
            except Exception:
                page_error = self._extract_generation_error()
                if page_error:
                    raise ElevenLabsError(page_error)
                raise ElevenLabsError("Khong tim thay nut download trong thoi gian cho phep.")

            with self._page.expect_download(timeout=TTS_EXPECT_DOWNLOAD_TIMEOUT_MS) as download_info:
                self._click_with_retries(download_button, description="download button")
            download = download_info.value
            _ensure_directory(output_path.parent)
            download.save_as(str(output_path))
            self._page.wait_for_timeout(250)

    def _select_visible_option(self, query: str) -> None:
        assert self._page is not None
        patterns = _query_match_patterns(query)
        candidates = [
            self._page.get_by_role("option"),
            self._page.locator("[cmdk-item]"),
            self._page.locator('[data-slot="command-item"]'),
            self._page.locator('[data-slot="item"]'),
            self._page.locator('[role="option"]'),
            self._page.locator('[role="listitem"]'),
            self._page.locator('[role="menuitem"]'),
            self._page.locator("li"),
            self._page.get_by_role("button"),
            self._page.locator("button, [role='option'], [role='menuitem'], [role='listitem'], [cmdk-item], [data-slot='command-item'], [data-slot='item'], li"),
        ]
        for pattern in patterns:
            for locator in candidates:
                try:
                    filtered = locator.filter(has_text=pattern)
                    if filtered.count() == 0:
                        continue
                    option = filtered.first
                    if option.is_visible():
                        self._click_with_retries(option, description=f"option `{query}`")
                        self._page.wait_for_timeout(300)
                        self._wait_for_idle_ui()
                        return
                except Exception:
                    continue

        # JavaScript fallback: scan all visible elements containing the query text
        query_lower = query.lower()
        tokens = [t for t in re.findall(r"[A-Za-z0-9]+", query_lower) if t]
        for token_subset in ([query_lower] + [tokens[0]] if tokens else [query_lower]):
            try:
                clicked = self._page.evaluate(
                    """(searchText) => {
                        const walkable = ['button', 'li', 'div', 'span', '[role]', 'a'];
                        const all = document.querySelectorAll(
                            'button, li, [role="option"], [role="menuitem"], [role="listitem"], [cmdk-item], [data-slot]'
                        );
                        for (const el of all) {
                            const text = (el.innerText || el.textContent || '').toLowerCase();
                            if (text.includes(searchText)) {
                                const rect = el.getBoundingClientRect();
                                if (rect.width > 0 && rect.height > 0) {
                                    el.click();
                                    return true;
                                }
                            }
                        }
                        return false;
                    }""",
                    token_subset,
                )
                if clicked:
                    self._page.wait_for_timeout(300)
                    self._wait_for_idle_ui()
                    return
            except Exception:
                continue

        raise ElevenLabsError(f"Khong tim thay option `{query}` trong ElevenLabs picker.")

    def _locate_model_trigger(self):
        assert self._page is not None
        candidates = [
            self._page.locator('[data-testid="tts-model-selector"]'),
            self._page.locator('[role="combobox"][aria-label*="model" i]'),
            self._page.locator('button[aria-haspopup="dialog"][aria-label*="model" i]'),
            self._page.locator('button[aria-haspopup="listbox"][aria-label*="model" i]'),
            self._page.get_by_role("button", name=re.compile(r"select model", re.I)),
            self._page.get_by_role("combobox", name=re.compile(r"select model|model", re.I)),
            self._page.locator('button[aria-label*="Select model"]'),
            self._page.locator('button, [role="button"], [role="combobox"]').filter(
                has_text=re.compile(
                    r"select a model|select model|eleven .*v[23]|multilingual v2|flash v2(?:\\.5)?|turbo v2(?:\\.5)?|\\bv2\\b|\\bv3\\b",
                    re.I,
                )
            ),
            self._page.get_by_role("button").filter(
                has_text=re.compile(r"select a model|eleven .*v[23]|multilingual v2|flash v2(?:\\.5)?|\\bv2\\b|\\bv3\\b", re.I)
            ),
        ]
        for locator in candidates:
            if locator.count() == 0:
                continue
            candidate = locator.first
            if candidate.is_visible():
                return candidate
        return None

    def _ensure_settings_tab_open(self) -> None:
        assert self._page is not None
        candidates = [
            self._page.locator('[data-testid="tts-settings-tab"]'),
            self._page.get_by_role("tab", name=re.compile(r"settings", re.I)),
            self._page.get_by_role("button", name=re.compile(r"settings", re.I)),
        ]
        for locator in candidates:
            try:
                if locator.count() == 0:
                    continue
                candidate = locator.first
                if not candidate.is_visible():
                    continue
                state = (candidate.get_attribute("data-state") or "").strip().lower()
                aria_selected = (candidate.get_attribute("aria-selected") or "").strip().lower()
                if state == "active" or aria_selected == "true":
                    return
                candidate.click()
                self._page.wait_for_timeout(300)
                return
            except Exception:
                continue

    def _locate_generate_button(self):
        assert self._page is not None
        candidates = [
            self._page.locator('[data-testid="tts-generate"]'),
            self._page.locator('button[aria-label*="Generate"]'),
            self._page.get_by_role("button", name=re.compile(r"generate|regenerate", re.I)),
            self._page.locator("button"),
        ]
        for locator in candidates:
            try:
                if locator.count() == 0:
                    continue
                candidate = locator.first
                if candidate.is_visible():
                    text = ((candidate.inner_text() or "") + " " + (candidate.get_attribute("aria-label") or "")).lower()
                    if locator != candidates[-1] or "generate" in text or "regenerate" in text:
                        return candidate
            except Exception:
                continue
        return None

    def _locate_download_button(self):
        assert self._page is not None
        candidates = [
            self._page.locator('[data-testid="tts-download-latest-button"]'),
            self._page.locator('[data-testid*="download"]'),
            self._page.locator('button[aria-label*="Download"]'),
            self._page.get_by_role("button", name=re.compile(r"download", re.I)),
            self._page.locator('a[download]'),
            self._page.locator('a[href*="download"]'),
            self._page.locator('a[href*=".mp3"]'),
        ]
        for locator in candidates:
            try:
                if locator.count() == 0:
                    continue
                candidate = locator.first
                if candidate.is_visible():
                    return candidate
            except Exception:
                continue
        return None

    def _locate_generation_download_buttons(self, *, limit: int | None = None):
        assert self._page is not None
        button_locator = self._page.locator(_generation_download_selector())
        buttons = []
        try:
            count = button_locator.count()
        except Exception:
            count = 0
        for index in range(count):
            try:
                candidate = button_locator.nth(index)
                if candidate.is_visible():
                    buttons.append(candidate)
            except Exception:
                continue
        if limit is not None:
            return buttons[:limit]
        return buttons

    def _wait_for_generation_download_buttons(self, *, expected_count: int):
        assert self._page is not None
        if expected_count <= 0:
            return []

        deadline = time.monotonic() + (TTS_DOWNLOAD_WAIT_TIMEOUT_MS / 1000)
        best_buttons = self._locate_generation_download_buttons(limit=expected_count)
        selector = _generation_download_selector()

        while time.monotonic() < deadline:
            buttons = self._locate_generation_download_buttons(limit=expected_count)
            if len(buttons) >= expected_count:
                return buttons
            if len(buttons) > len(best_buttons):
                best_buttons = buttons
            try:
                self._page.wait_for_function(
                    """
                    ({ expectedCount, selector }) => {
                      const isVisible = (el) => {
                        if (!el) return false;
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                      };
                      const buttons = Array.from(document.querySelectorAll(selector))
                        .filter((el) => isVisible(el));
                      return buttons.length >= expectedCount;
                    }
                    """,
                    {"expectedCount": expected_count, "selector": selector},
                    timeout=1_500,
                )
            except Exception:
                self._page.wait_for_timeout(350)
                continue

        return best_buttons

    def _extract_generation_error(self) -> str | None:
        assert self._page is not None
        try:
            message = self._page.evaluate(
                """() => {
                    const nodes = Array.from(document.querySelectorAll('body *'));
                    const isVisible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const matches = [];
                    for (const el of nodes) {
                        if (!isVisible(el)) continue;
                        const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                        if (!text || text.length < 6 || text.length > 220) continue;
                        const lower = text.toLowerCase();
                        if (
                            lower.includes('error') ||
                            lower.includes('failed') ||
                            lower.includes('unable to') ||
                            lower.includes('try again') ||
                            lower.includes('something went wrong')
                        ) {
                            matches.push(text);
                        }
                    }
                    return matches[0] || null;
                }"""
            )
            if message is None:
                return None
            return str(message).strip() or None
        except Exception:
            return None

    def _locate_voice_trigger(self):
        assert self._page is not None
        # Prefer the new UI style: button with data-agent-id containing a voice name
        # (ElevenLabs updated UI - voice button now shows selected voice name)
        try:
            # Strategy 1: Find a button containing a span with class truncate
            # which holds the voice name e.g. "Liam - Energetic..."
            agent_buttons = self._page.locator('button:has(span.truncate)')
            count = agent_buttons.count()
            for i in range(count):
                btn = agent_buttons.nth(i)
                try:
                    if btn.is_visible():
                        return btn
                except Exception:
                    continue
        except Exception:
            pass

        # Fallback: original selectors
        candidates = [
            self._page.locator('[data-testid="tts-voice-selector"]'),
            self._page.locator('button[aria-label*="Select voice"]'),
            self._page.get_by_role("button", name=re.compile(r"select voice", re.I)),
        ]
        for locator in candidates:
            if locator.count() == 0:
                continue
            candidate = locator.first
            if candidate.is_visible():
                return candidate
        return None


    def _open_voice_picker(self, trigger=None) -> None:
        assert self._page is not None
        self._wait_for_idle_ui()
        voice_trigger = trigger or self._locate_voice_trigger()
        if voice_trigger is None:
            raise ElevenLabsError("Khong tim thay nut chon voice tren ElevenLabs.")
        self._click_with_retries(voice_trigger, description="voice selector")
        # Wait for picker to appear and animate
        self._page.wait_for_timeout(1500)
        search_input = self._find_voice_search_input()
        if search_input:
            search_input.wait_for(state="visible", timeout=3000)

    def _find_voice_search_input(self):
        assert self._page is not None
        search_candidates = [
            'input[type="search"]',
            'input[placeholder*="Search"]',
            'input[placeholder*="search"]',
            'input[placeholder*="voice"]',
            'input[placeholder*="Voice"]',
            '[role="searchbox"]',
            '[cmdk-input]',
            '[data-slot="command-input"] input',
            '[data-slot="input"]',
            'input[type="text"]',
        ]
        for selector in search_candidates:
            try:
                locator = self._page.locator(selector).first
                if locator.count() and locator.is_visible():
                    return locator
            except Exception:
                continue
        return None

    def _resolve_voice_query(self, query: str, voices: list[dict] | None = None) -> str:
        voice_query = query.strip()
        if not voice_query:
            return voice_query

        voices = voices if voices is not None else self._fetch_available_voices()
        if not voices:
            return voice_query

        exact_id_match = next((voice for voice in voices if str(voice.get("voice_id", "")).strip() == voice_query), None)
        if exact_id_match:
            return str(exact_id_match.get("name") or voice_query).strip() or voice_query

        lowered_query = voice_query.lower()
        exact_name_match = next(
            (voice for voice in voices if str(voice.get("name", "")).strip().lower() == lowered_query),
            None,
        )
        if exact_name_match:
            return str(exact_name_match.get("name") or voice_query).strip() or voice_query

        patterns = _query_match_patterns(voice_query)
        normalized_tokens = {
            token.lower()
            for token in re.findall(r"[A-Za-z0-9]+", voice_query)
            if token
        }

        best_match: tuple[int, str] | None = None
        for voice in voices:
            name = str(voice.get("name", "")).strip()
            if not name:
                continue
            labels = voice.get("labels") if isinstance(voice.get("labels"), dict) else {}
            haystack_parts = [name, str(voice.get("description", "")).strip()]
            haystack_parts.extend(str(value).strip() for value in labels.values())
            haystack = " | ".join(part for part in haystack_parts if part)
            haystack_lower = haystack.lower()

            if patterns and any(pattern.search(haystack) for pattern in patterns):
                return name

            if normalized_tokens:
                haystack_tokens = {
                    token.lower()
                    for token in re.findall(r"[A-Za-z0-9]+", haystack_lower)
                    if token
                }
                overlap = len(normalized_tokens & haystack_tokens)
                if overlap:
                    score = overlap * 10
                    if name.lower().startswith(voice_query.lower()):
                        score += 5
                    elif voice_query.lower() in haystack_lower:
                        score += 3
                    if best_match is None or score > best_match[0]:
                        best_match = (score, name)

        if best_match is not None:
            return best_match[1]

        if _looks_like_elevenlabs_voice_id(voice_query):
            raise ElevenLabsError(
                f"Khong tim thay voice ID `{voice_query}` trong danh sach voice hien co cua session ElevenLabs nay."
            )

        return voice_query

    def _fetch_available_voices(self, open_picker: bool = True) -> list[dict]:
        assert self._page is not None

        # --- Strategy 0: Use cached custom voices intercepted during page load ---
        # Keep intercepted data as fallback only. Do not return early because
        # first intercepted payload can be partial and miss voices.
        intercepted_fallback: list[dict] = []
        if hasattr(self, "_cached_custom_voices") and self._cached_custom_voices:
            intercepted_fallback = [
                voice for voice in self._cached_custom_voices if isinstance(voice, dict)
            ]

        # --- Strategy 1: Direct API call using xi-api-key captured from browser request headers ---
        # This is the most reliable and gets ALL voices including My Voices (cloned/generated)
        if self._xi_api_key:
            try:
                import urllib.request as _req
                import json as _json
                for url in ELEVENLABS_VOICE_API_URLS:
                    request = _req.Request(url, headers={
                        "xi-api-key": self._xi_api_key,
                        "Accept": "application/json",
                    })
                    with _req.urlopen(request, timeout=15) as resp:
                        data = _json.loads(resp.read().decode())
                        voices = data.get("voices", [])
                        custom_voices = [v for v in voices if _is_my_voice_entry(v)]
                        if custom_voices:
                            print(f"[TTS] Fetched {len(custom_voices)} custom voices via API (My Voices).", flush=True)
                            return custom_voices
            except Exception as exc:
                print(f"[TTS] API call with xi-api-key failed: {exc}", flush=True)

        # --- Strategy 2: Navigate page, intercept network, extract xi-api-key + voice data ---
        try:
            import json as _json
            captured: list = []
            captured_key: list[str] = []

            def handle_request(request) -> None:
                if not captured_key and _is_elevenlabs_api_url(request.url):
                    key = request.headers.get("xi-api-key", "")
                    if key and len(key) > 10:
                        captured_key.append(key)
                        self._xi_api_key = key

            def handle_response(response) -> None:
                try:
                    if _is_elevenlabs_voices_url(response.url):
                        if response.status == 200:
                            body = response.json()
                            if isinstance(body, dict) and "voices" in body:
                                custom_voices = [v for v in body["voices"] if _is_my_voice_entry(v)]
                                captured.extend(custom_voices)
                except Exception:
                    pass

            self._page.on("request", handle_request)
            self._page.on("response", handle_response)
            try:
                # Force a fresh load by navigating away first (prevents browser cache serving old data)
                self._page.goto("about:blank", wait_until="load", timeout=5_000)
                self._page.goto("https://elevenlabs.io/app/speech-synthesis/text-to-speech",
                                wait_until="networkidle", timeout=25_000)
                self._page.wait_for_timeout(2000)
            except Exception:
                pass
            finally:
                self._page.remove_listener("request", handle_request)
                self._page.remove_listener("response", handle_response)

            # If we captured the key, try a direct API call to get ALL voices including My Voices
            if captured_key:
                try:
                    import urllib.request as _req2
                    for url in ELEVENLABS_VOICE_API_URLS:
                        req2 = _req2.Request(url, headers={
                            "xi-api-key": captured_key[0],
                            "Accept": "application/json",
                        })
                        with _req2.urlopen(req2, timeout=15) as resp:
                            data = _json.loads(resp.read().decode())
                            voices = data.get("voices", [])
                            custom_voices = [v for v in voices if _is_my_voice_entry(v)]
                            if custom_voices:
                                print(f"[TTS] Fetched {len(custom_voices)} custom voices via API (My Voices).", flush=True)
                                return custom_voices
                except Exception:
                    pass

            if captured:
                return captured
        except Exception:
            pass

        if intercepted_fallback:
            print(
                f"[TTS] Using {len(intercepted_fallback)} intercepted custom voices fallback (My Voices).",
                flush=True,
            )
            return intercepted_fallback

        # --- Fallback: DOM scraping (original method) ---
        try:
            if open_picker:
                self._open_voice_picker()
            else:
                self._page.wait_for_timeout(500)

            search_input = self._find_voice_search_input()
            if search_input is not None:
                try:
                    search_input.wait_for(state="visible", timeout=2000)
                    search_input.fill("")
                    self._page.wait_for_timeout(500)
                except Exception:
                    pass
            voices = self._page.evaluate(
                """() => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const normalizeText = (value) => (value || '')
                        .replace(/\u00a0/g, ' ')
                        .split(/\n+/)
                        .map((line) => line.trim())
                        .filter(Boolean);
                    const searchSelectors = [
                        'input[type="search"]', 'input[placeholder*="Search"]',
                        'input[placeholder*="search"]', 'input[placeholder*="voice"]',
                        'input[placeholder*="Voice"]', '[role="searchbox"]',
                        '[cmdk-input]', '[data-slot="command-input"] input',
                        '[data-slot="input"]', 'input[type="text"]',
                    ];
                    const searchInput = searchSelectors
                        .flatMap((selector) => Array.from(document.querySelectorAll(selector)))
                        .find((el) => isVisible(el));
                    const roots = [];
                    if (searchInput) {
                        const root = searchInput.closest('[role="dialog"], [cmdk-root], [data-slot="popover-content"], [data-radix-popper-content-wrapper]');
                        if (root) roots.push(root);
                    }
                    if (!roots.length) roots.push(document.body);
                    const candidateSelectors = [
                        '[cmdk-item]', '[data-slot="command-item"]', '[data-slot="item"]',
                        '[role="option"]', '[role="listitem"]', '[role="menuitem"]', 'li', 'button',
                    ];
                    const results = [];
                    const seen = new Set();
                    for (const root of roots) {
                        const candidates = root.querySelectorAll(candidateSelectors.join(', '));
                        for (const el of candidates) {
                            if (!isVisible(el)) continue;
                            if (el.matches('[data-testid="tts-voice-selector"]')) continue;
                            const lines = normalizeText(el.innerText || el.textContent || '');
                            if (!lines.length) continue;
                            const fullText = lines.join(' | ');
                            const name = lines[0];
                            if (!name) continue;
                            const dedupeKey = fullText.toLowerCase();
                            if (seen.has(dedupeKey)) continue;
                            seen.add(dedupeKey);
                            const voiceId = (
                                el.getAttribute('data-value') || el.getAttribute('data-id') ||
                                el.getAttribute('data-key') || el.getAttribute('aria-label') || name
                            ).trim();
                            const description = lines.slice(1).join(', ');
                            results.push({ voice_id: voiceId || name, name, labels: description ? { description } : {} });
                        }
                    }
                    return results;
                }"""
            )
            return voices if isinstance(voices, list) else []
        except Exception:
            return []


    def _has_ready_tts_workspace(self) -> bool:
        assert self._page is not None
        selectors = [
            '[data-testid="tts-editor"]',
            '[data-testid="tts-voice-selector"]',
            '[data-testid="tts-generate"]',
            'button[aria-label*="Generate"]',
            'textarea',
        ]
        for selector in selectors:
            try:
                locator = self._page.locator(selector).first
                if locator.count() and locator.is_visible():
                    return True
            except Exception:
                continue
        return False

    def _wait_for_idle_ui(self, timeout_ms: int = TTS_UI_SETTLE_TIMEOUT_MS) -> None:
        assert self._page is not None
        try:
            self._page.wait_for_function(
                """
                () => {
                  const isVisible = (el) => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return (
                      rect.width > 0 &&
                      rect.height > 0 &&
                      style.visibility !== 'hidden' &&
                      style.display !== 'none' &&
                      style.pointerEvents !== 'none' &&
                      style.opacity !== '0'
                    );
                  };

                  const overlays = Array.from(document.querySelectorAll(
                    '[data-state="open"][aria-hidden="true"], [data-state="open"][data-aria-hidden="true"], [data-radix-popper-content-wrapper] > div[aria-hidden="true"]'
                  ));
                  return !overlays.some((el) => isVisible(el));
                }
                """,
                timeout=timeout_ms,
            )
        except Exception:
            pass

    def _click_with_retries(self, locator, *, description: str, attempts: int = 4) -> None:
        assert self._page is not None
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            self._wait_for_idle_ui(timeout_ms=2_500)
            try:
                locator.wait_for(state="visible", timeout=4_000)
                locator.scroll_into_view_if_needed(timeout=2_000)
                locator.click(timeout=4_000, force=attempt == attempts)
                self._page.wait_for_timeout(250)
                return
            except Exception as exc:
                last_error = exc
                try:
                    self._page.keyboard.press("Escape")
                    self._page.wait_for_timeout(200)
                except Exception:
                    pass
        if last_error is not None:
            raise ElevenLabsError(
                f"Khong click duoc {description}: {_format_exception_message(last_error)}"
            ) from last_error
        raise ElevenLabsError(f"Khong click duoc {description}.")

    def _build_cookie(self, cookie_payload: dict) -> Cookie:
        domain = str(cookie_payload.get("domain", ""))
        expires = cookie_payload.get("expires")
        if expires is not None:
            try:
                expires = int(expires)
            except (TypeError, ValueError):
                expires = None
        return Cookie(
            version=0,
            name=str(cookie_payload.get("name", "")),
            value=str(cookie_payload.get("value", "")),
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=bool(domain),
            domain_initial_dot=domain.startswith("."),
            path=str(cookie_payload.get("path", "/")),
            path_specified=True,
            secure=bool(cookie_payload.get("secure", False)),
            expires=expires,
            discard=False,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": bool(cookie_payload.get("httpOnly", False))},
            rfc2109=False,
        )


class ElevenLabsSessionManager:
    def __init__(self) -> None:
        self._last_status: dict | None = None

    def status(self) -> dict:
        return self.validate_session(cache_only=True)

    def validate_session(self, cache_only: bool = False) -> dict:
        if cache_only and self._last_status is not None:
            return self._last_status

        status = {
            "dependencies_ready": True,
            "authenticated": False,
            "profileLocked": False,
            "browser": "Local browser",
            "profileDir": "",
            "message": "",
            "checkedAt": utc_now(),
        }
        try:
            profile = detect_tts_browser_profile()
        except Exception as exc:  # noqa: BLE001
            status["dependencies_ready"] = False
            status["message"] = str(exc)
            self._last_status = status
            return status

        status["browser"] = profile.name
        status["profileDir"] = str(profile.profile_dir)

        cookie_count = max(
            _cookie_count_for_domain(profile.profile_dir / "Network" / "Cookies", TTS_AUTH_DOMAIN),
            _cookie_count_for_domain(profile.profile_dir / "Cookies", TTS_AUTH_DOMAIN),
        )
        if cookie_count > 0:
            status["authenticated"] = True
            status["message"] = f"Đã kết nối qua phiên {profile.name}."
        elif profile.name.lower() == "coccoc":
            # CocCoc may lock/decrypt cookies differently; treat detected active profile as ready.
            status["authenticated"] = True
            status["message"] = (
                "Đã kết nối qua phiên CocCoc. "
                "Nếu gặp lỗi khi chạy TTS, hãy mở ElevenLabs trong CocCoc rồi bấm Làm mới phiên."
            )
        else:
            status["message"] = (
                f"Chưa tìm thấy phiên ElevenLabs trong {profile.name}. "
                f"Hãy đăng nhập ElevenLabs trong {profile.name} rồi bấm Làm mới phiên."
            )

        self._last_status = status
        return status

    def open_login(self) -> dict:
        browser_name = "browser local"
        profile_dir = ""
        warning_message: str | None = None
        opened = False

        try:
            profile = detect_tts_browser_profile()
            browser_name = profile.name
            profile_dir = str(profile.profile_dir)

            launch_command = [str(profile.executable_path)]
            if profile.profile_name:
                launch_command.append(f"--profile-directory={profile.profile_name}")
            launch_command.append(ELEVENLABS_LOGIN_URL)

            popen_kwargs: dict[str, object] = {}
            if sys.platform == "win32":
                popen_kwargs["creationflags"] = (
                    getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                )
            subprocess.Popen(launch_command, **popen_kwargs)
            opened = True
        except Exception as exc:
            warning_message = _format_exception_message(exc)
            try:
                opened_payload = browser_session.open_login(ELEVENLABS_LOGIN_URL)
                opened = bool(opened_payload.get("opened", True))
            except Exception as fallback_exc:  # noqa: BLE001
                raise ElevenLabsError(
                    f"Khong mo duoc cua so dang nhap ElevenLabs: {fallback_exc}"
                ) from fallback_exc

        message = (
            f"Da mo ElevenLabs tren {browser_name}. Dang nhap trong {browser_name}, "
            "roi quay lai app bam Lam moi phien."
        )
        if warning_message:
            message += f" (Fallback default browser: {warning_message})"

        return {
            "opened": opened,
            "url": ELEVENLABS_LOGIN_URL,
            "browser": browser_name,
            "profileDir": profile_dir,
            "message": message,
        }

    def _dependencies_ready(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            return False
        return True


class TtsManager:
    def __init__(self, *, state_file: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._batches: dict[str, TtsBatch] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._session = ElevenLabsSessionManager()
        self._state_file = state_file or TTS_STATE_FILE
        self._voice_cache: list[dict] | None = None
        self._voice_cache_time: float = 0
        self._load_state()

    def get_bootstrap(self) -> dict:
        return {
            "sessionStatus": self._session.status(),
            "batchSummaries": self.list_batch_summaries(),
            "activeBatchId": self.get_active_batch_id(),
        }

    def get_session_status(self, refresh: bool = False) -> dict:
        return self._session.validate_session(cache_only=not refresh)

    def list_available_voices(self, refresh: bool = False) -> list[dict]:
        import time
        import json
        
        cache_file = TTS_BATCH_ROOT.parent / "voices_cache.json"
        
        if refresh:
            self._voice_cache = None
            self._voice_cache_time = 0
        elif self._voice_cache:
            cache_has_ownership_flag = any(
                isinstance(voice, dict) and ("isOwner" in voice or "is_owner" in voice)
                for voice in self._voice_cache
            )
            if not cache_has_ownership_flag:
                self._voice_cache = None
                self._voice_cache_time = 0
        
        # Load from memory or disk cache
        if self._voice_cache is None and cache_file.exists():
            try:
                cached_data = json.loads(cache_file.read_text(encoding="utf-8"))
                if isinstance(cached_data, dict) and "voices" in cached_data and "time" in cached_data:
                    cached_voices = cached_data["voices"] if isinstance(cached_data["voices"], list) else []
                    cache_has_ownership_flag = any(
                        isinstance(voice, dict) and ("isOwner" in voice or "is_owner" in voice)
                        for voice in cached_voices
                    )
                    if cached_voices and not cache_has_ownership_flag:
                        self._voice_cache = None
                        self._voice_cache_time = 0
                    else:
                        self._voice_cache = [
                            voice
                            for voice in cached_voices
                            if isinstance(voice, dict) and _is_my_voice_entry(voice)
                        ]
                        self._voice_cache_time = cached_data["time"]
            except Exception:
                pass

        if not refresh and self._voice_cache is not None and (time.time() - self._voice_cache_time) < 3600:
            return self._voice_cache

        voices: list[dict] | None = None
        last_error: Exception | None = None
        for headless_mode in (True, False):
            try:
                with ElevenLabsAutomation(
                    TTS_BATCH_ROOT / "_scratch",
                    headless=headless_mode,
                ) as automation:
                    automation.ensure_authenticated(wait_for_workspace=False)
                    fetched = automation._fetch_available_voices(open_picker=False)
                voices = fetched
                if fetched:
                    break
            except Exception as exc:
                last_error = exc
                safe_error = ascii(_format_exception_message(exc))
                print(
                    f"[TTS] Failed to fetch voices (headless={headless_mode}): {safe_error}",
                    flush=True,
                )

        if voices is None:
            if last_error is not None:
                safe_error = ascii(_format_exception_message(last_error))
                print(f"[TTS] Failed to fetch voices: {safe_error}", flush=True)
            return self._voice_cache or []

        results: list[dict] = []
        for voice in voices:
            if not _is_my_voice_entry(voice):
                continue
            voice_id = str(voice.get("voice_id") or voice.get("voiceId") or "").strip()
            name = str(voice.get("name", "")).strip()
            if not voice_id or not name:
                continue
            raw_labels = voice.get("labels") if isinstance(voice.get("labels"), dict) else {}
            labels = {str(key): value for key, value in raw_labels.items()}
            description = str(voice.get("description", "")).strip()
            if description and not labels.get("description"):
                labels["description"] = description
            payload = {
                "voiceId": voice_id,
                "name": name,
                "labels": labels,
            }
            preview_url = str(voice.get("preview_url") or voice.get("previewUrl") or "").strip()
            if preview_url:
                payload["previewUrl"] = preview_url
            category = str(voice.get("category", "")).strip()
            if category:
                payload["category"] = category
            is_owner = voice.get("is_owner")
            if not isinstance(is_owner, bool):
                is_owner = voice.get("isOwner")
            if isinstance(is_owner, bool):
                payload["isOwner"] = is_owner
            results.append(payload)
        
        self._voice_cache = results
        self._voice_cache_time = time.time()
        
        # Persist to disk
        try:
            cache_file.write_text(
                json.dumps({"time": self._voice_cache_time, "voices": self._voice_cache}, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass
            
        return results

    def open_login(self) -> dict:
        return self._session.open_login()

    def preview_sheet(self, sheet_url: str, text_column: str | None = None) -> dict:
        scan_result = scan_text_sheet(sheet_url, preferred_text_column=text_column)
        warnings: list[str] = []
        if not scan_result.entries:
            warnings.append("Khong tim thay dong nao co text de gen voice.")
        if scan_result.skipped_rows > 0:
            warnings.append(f"Bo qua {scan_result.skipped_rows} dong vi cot text dang trong.")
        return {
            "sheetId": scan_result.sheet_id,
            "gid": scan_result.gid,
            "accessMode": scan_result.access_mode,
            "sheetTitle": scan_result.sheet_title,
            "textColumn": scan_result.text_column,
            "availableColumns": scan_result.available_columns,
            "rowCount": len(scan_result.entries),
            "skippedRowCount": scan_result.skipped_rows,
            "warnings": warnings,
            "rows": [
                {
                    "sequenceLabel": entry.sequence_label,
                    "rowNumber": entry.row_index + 1,
                    "text": entry.text,
                }
                for entry in scan_result.entries[:120]
            ],
        }

    def create_batch(
        self,
        sheet_url: str,
        voice_query: str,
        voice_id: str | None,
        voice_name: str | None,
        model_family: str,
        take_count: int,
        retry_count: int = 1,
        worker_count: int = 1,
        headless: bool = False,
        filename_prefix: str | None = None,
        channel_prefix: str | None = None,
        tag_text: str = "",
        text_column: str | None = None,
    ) -> dict:
        if not voice_query.strip():
            raise ValueError("voice_query is required.")
        normalized_voice_id = (voice_id or "").strip()
        if not normalized_voice_id:
            raise ValueError("Chi cho phep dung voice trong My Voice. Hay chon voice tu danh sach My Voice.")
        allowed_voices = self.list_available_voices(refresh=False)
        allowed_map = {str(voice.get("voiceId", "")).strip(): voice for voice in allowed_voices if isinstance(voice, dict)}
        selected_voice = allowed_map.get(normalized_voice_id)
        if selected_voice is None:
            raise ValueError("Voice da chon khong thuoc My Voice cua phien hien tai. Hay Lam moi phien va chon lai.")
        if model_family.strip().lower() not in {"v2", "v3"}:
            raise ValueError("model_family phai la `v2` hoac `v3`.")
        take_count = _clamp_int(take_count, default=1, minimum=1, maximum=5)
        retry_count = _clamp_int(retry_count, default=1, minimum=0, maximum=5)
        worker_count = _clamp_int(worker_count, default=1, minimum=1, maximum=TTS_MAX_WORKERS)

        scan_result = scan_text_sheet(sheet_url, preferred_text_column=text_column)
        if not scan_result.entries:
            raise ValueError("Khong tim thay dong nao co text de gen voice.")

        batch_id = str(uuid.uuid4())
        batch_dir = _ensure_directory(TTS_BATCH_ROOT / batch_id)
        batch = TtsBatch(
            id=batch_id,
            created_at=utc_now(),
            last_updated_at=utc_now(),
            status="queued",
            sheet_url=sheet_url,
            sheet_id=scan_result.sheet_id,
            gid=scan_result.gid,
            sheet_access_mode=scan_result.access_mode,
            text_column=scan_result.text_column,
            voice_query=normalized_voice_id,
            voice_id=normalized_voice_id,
            voice_name=str(selected_voice.get("name", "")).strip() or (voice_name or "").strip() or None,
            model_family=model_family.strip().lower(),
            tag_text=tag_text.strip(),
            take_count=take_count,
            retry_count=retry_count,
            worker_count=worker_count,
            headless=bool(headless),
            work_dir=str(batch_dir),
            filename_prefix=filename_prefix,
            channel_prefix=(channel_prefix or "").strip() or None,
            items=self._build_items(
                scan_result.entries,
                filename_prefix or scan_result.sheet_title,
                (channel_prefix or "").strip() or None,
                batch_dir,
                take_count,
                model_family=model_family.strip().lower(),
            ),
        )

        with self._lock:
            self._batches[batch.id] = batch
            self._cancel_events[batch.id] = threading.Event()
            self._persist_state_locked()

        self._start_batch_worker(batch.id)
        return self.get_batch_detail(batch.id) or {}

    def list_batch_summaries(self) -> list[dict]:
        with self._lock:
            summaries = [self._serialize_batch_summary(batch) for batch in self._batches.values()]
        summaries.sort(key=lambda summary: summary["createdAt"], reverse=True)
        return summaries

    def get_batch_detail(self, batch_id: str) -> dict | None:
        with self._lock:
            batch = self._batches.get(batch_id)
            return None if batch is None else self._serialize_batch_detail(batch)

    def get_active_batch_id(self) -> str | None:
        with self._lock:
            active = [batch for batch in self._batches.values() if batch.status in {"queued", "running", "cancelling"}]
            if active:
                active.sort(key=lambda batch: batch.last_updated_at, reverse=True)
                return active[0].id
            return None

    def cancel_batch(self, batch_id: str) -> dict:
        with self._lock:
            batch = self._require_batch(batch_id)
            if batch.status in FINAL_BATCH_STATUSES:
                return self._serialize_batch_detail(batch)
            batch.status = "cancelling"
            batch.last_updated_at = utc_now()
            self._cancel_events.setdefault(batch_id, threading.Event()).set()
            self._persist_state_locked()
            return self._serialize_batch_detail(batch)

    def pick_take(self, batch_id: str, item_id: str, take_id: str) -> dict:
        with self._lock:
            batch = self._require_batch(batch_id)
            item = self._require_item(batch, item_id)
            take = self._require_take(item, take_id)
            if take.status != "completed":
                raise ValueError("Chi co the chon take da gen xong.")
            item.picked_take_id = take.id
            batch.last_updated_at = utc_now()
            self._persist_state_locked()
            return self._serialize_batch_detail(batch)

    def retry_failed(self, batch_id: str) -> dict:
        with self._lock:
            batch = self._require_batch(batch_id)
            if batch.status in ACTIVE_BATCH_STATUSES:
                raise ValueError("TTS batch dang chay.")

            failed_items = [item for item in batch.items if item.status == "failed"]
            if not failed_items:
                raise ValueError("Khong co row loi de retry.")

            now = utc_now()
            for item in failed_items:
                self._reset_item_for_retry(item)

            cancel_event = threading.Event()
            self._cancel_events[batch_id] = cancel_event
            batch.status = "queued"
            batch.last_updated_at = now
            self._persist_state_locked()
            detail = self._serialize_batch_detail(batch)

        _tts_debug(f"Retry failed rows for batch {batch_id}.")
        self._start_batch_worker(batch_id)
        return detail

    def retry_item(self, batch_id: str, item_id: str) -> dict:
        with self._lock:
            batch = self._require_batch(batch_id)
            if batch.status in ACTIVE_BATCH_STATUSES:
                raise ValueError("TTS batch dang chay.")

            item = self._require_item(batch, item_id)
            if item.status != "failed":
                raise ValueError("Chi co the retry row dang failed.")

            self._reset_item_for_retry(item)
            self._cancel_events[batch_id] = threading.Event()
            batch.status = "queued"
            batch.last_updated_at = utc_now()
            self._persist_state_locked()
            detail = self._serialize_batch_detail(batch)

        _tts_debug(f"Retry row {item_id} in batch {batch_id}.")
        self._start_batch_worker(batch_id)
        return detail

    def export_selected(self, batch_id: str, item_ids: list[str], destination_dir: str) -> dict:
        target_dir = _ensure_directory(Path(destination_dir).expanduser())
        exported: list[str] = []

        with self._lock:
            batch = self._require_batch(batch_id)
            items = [self._require_item(batch, item_id) for item_id in item_ids]

        for item in items:
            take = self._selected_take_for_item(item)
            if take is None or not take.output_path:
                continue
            source = Path(take.output_path)
            if not source.exists():
                continue
            copied = _copy_with_unique_name(source, target_dir, source.name)
            exported.append(str(copied))

        return {
            "exportedCount": len(exported),
            "destinationDir": str(target_dir),
            "files": exported,
        }

    def resolve_take_path(self, batch_id: str, take_id: str) -> Path | None:
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None:
                return None
            for item in batch.items:
                for take in item.takes:
                    if take.id == take_id and take.output_path:
                        path = Path(take.output_path)
                        return path if path.exists() else None
        return None

    def _start_batch_worker(self, batch_id: str) -> None:
        _tts_debug(f"Start worker for batch {batch_id}.")
        worker = threading.Thread(target=self._process_batch, args=(batch_id,), daemon=True)
        worker.start()

    def _process_batch(self, batch_id: str) -> None:
        with self._lock:
            batch = self._require_batch(batch_id)
            batch.status = "running"
            batch.last_updated_at = utc_now()
            cancel_event = self._cancel_events.setdefault(batch_id, threading.Event())
            self._persist_state_locked()

        item_queue: Queue[str] = Queue()
        with self._lock:
            batch = self._require_batch(batch_id)
            pending_item_ids = [
                item.id
                for item in batch.items
                if item.status in {"queued", "running"}
            ]
            worker_count = min(max(1, batch.worker_count), max(1, len(pending_item_ids)))
            for item_id in pending_item_ids:
                item_queue.put(item_id)

        auth_errors: list[str] = []
        fatal_errors: list[str] = []
        workers: list[threading.Thread] = []

        try:
            for worker_index in range(worker_count):
                worker = threading.Thread(
                    target=self._process_batch_worker,
                    args=(batch_id, worker_index + 1, item_queue, cancel_event, auth_errors, fatal_errors),
                    daemon=True,
                )
                workers.append(worker)
                worker.start()

            for worker in workers:
                worker.join()
        except ElevenLabsAuthError as exc:
            _tts_debug(f"Batch {batch_id}: auth error: {exc}")
            with self._lock:
                for item in batch.items:
                    if item.status == "queued":
                        item.status = "failed"
                        item.error = str(exc)
                        item.completed_at = utc_now()
                        for take in item.takes:
                            if take.status == "queued":
                                take.status = "failed"
                                take.error = str(exc)
                                take.completed_at = utc_now()
                batch.status = "completed_with_errors"
                batch.last_updated_at = utc_now()
                self._persist_state_locked()
            return
        except Exception as exc:  # noqa: BLE001
            _tts_debug(f"Batch {batch_id}: worker crashed: {exc}")
            with self._lock:
                for item in batch.items:
                    if item.status in {"queued", "running"}:
                        item.status = "failed"
                        item.error = str(exc)
                        item.completed_at = utc_now()
                        for take in item.takes:
                            if take.status in {"queued", "running"}:
                                take.status = "failed"
                                take.error = str(exc)
                                take.completed_at = utc_now()
                batch.status = "completed_with_errors"
                batch.last_updated_at = utc_now()
                self._persist_state_locked()
            return

        with self._lock:
            batch = self._require_batch(batch_id)
            if auth_errors:
                error_message = auth_errors[0]
                for item in batch.items:
                    if item.status in {"queued", "running"}:
                        item.status = "failed"
                        item.error = error_message
                        item.completed_at = utc_now()
                        for take in item.takes:
                            if take.status in {"queued", "running"}:
                                take.status = "failed"
                                take.error = error_message
                                take.completed_at = utc_now()
                batch.status = "completed_with_errors"
                batch.last_updated_at = utc_now()
            elif fatal_errors:
                error_message = fatal_errors[0]
                for item in batch.items:
                    if item.status in {"queued", "running"}:
                        item.status = "failed"
                        item.error = error_message
                        item.completed_at = utc_now()
                        for take in item.takes:
                            if take.status in {"queued", "running"}:
                                take.status = "failed"
                                take.error = error_message
                                take.completed_at = utc_now()
                batch.status = "completed_with_errors"
                batch.last_updated_at = utc_now()
            else:
                self._finalize_batch(batch, cancel_event.is_set())
            self._persist_state_locked()
        _tts_debug(f"Batch {batch_id}: finished with status {batch.status}.")

    def _process_batch_worker(
        self,
        batch_id: str,
        worker_index: int,
        item_queue: Queue[str],
        cancel_event: threading.Event,
        auth_errors: list[str],
        fatal_errors: list[str],
    ) -> None:
        with self._lock:
            batch = self._require_batch(batch_id)
            headless = batch.headless
            work_dir = Path(batch.work_dir)

        try:
            with ElevenLabsAutomation(work_dir / f"_worker_{worker_index}", headless=headless) as automation:
                _tts_debug(
                    f"Batch {batch_id}: worker {worker_index} ready in {automation.browser_name} "
                    f"(headless={headless})."
                )
                with self._lock:
                    batch = self._require_batch(batch_id)
                    model_family = batch.model_family
                    voice_query = batch.voice_name or batch.voice_query
                for setup_attempt in range(1, 4):
                    try:
                        automation.ensure_authenticated()
                        automation.select_model(model_family)
                        automation.select_voice(voice_query)
                        break
                    except Exception as exc:  # noqa: BLE001
                        _tts_debug(
                            f"Batch {batch_id}: worker {worker_index} setup attempt "
                            f"{setup_attempt}/3 failed: {_format_exception_message(exc)}"
                        )
                        if setup_attempt >= 3:
                            raise
                        try:
                            automation._page.goto(ELEVENLABS_TTS_URL, wait_until="domcontentloaded")
                        except Exception:
                            pass
                        time.sleep(0.8)

                while not cancel_event.is_set():
                    if auth_errors or fatal_errors:
                        return
                    try:
                        item_id = item_queue.get_nowait()
                    except Empty:
                        return

                    try:
                        self._process_batch_item(batch_id, item_id, automation, cancel_event)
                    finally:
                        item_queue.task_done()
        except ElevenLabsAuthError as exc:
            _tts_debug(f"Batch {batch_id}: worker {worker_index} auth error: {exc}")
            auth_errors.append(str(exc))
            cancel_event.set()
        except Exception as exc:  # noqa: BLE001
            message = _format_exception_message(exc)
            _tts_debug(f"Batch {batch_id}: worker {worker_index} crashed: {message}")
            fatal_errors.append(message)
            cancel_event.set()

    def _process_batch_item(
        self,
        batch_id: str,
        item_id: str,
        automation: ElevenLabsAutomation,
        cancel_event: threading.Event,
    ) -> None:
        with self._lock:
            batch = self._require_batch(batch_id)
            item = self._require_item(batch, item_id)
            if item.status not in {"queued", "running"}:
                return
            item.status = "running"
            item.started_at = item.started_at or utc_now()
            batch.last_updated_at = utc_now()
            prompt_text = _prompt_with_tag(item.text, batch.model_family, batch.tag_text)
            retry_count = batch.retry_count
            model_family = batch.model_family
            self._persist_state_locked()

        _tts_debug(
            f"Batch {batch_id}: worker item row {item.row_number} "
            f"({item.sequence_label}) with {batch.take_count} take(s) "
            f"and {len(item.takes)} output(s)."
        )

        outputs_per_generation = _outputs_per_generation(model_family)
        pending_take_ids = [
            take.id
            for take in item.takes
            if take.status in {"queued", "running"}
        ]

        for group_start in range(0, len(pending_take_ids), outputs_per_generation):
            if cancel_event.is_set():
                break
            take_group_ids = pending_take_ids[group_start : group_start + outputs_per_generation]

            with self._lock:
                batch = self._require_batch(batch_id)
                item = self._require_item(batch, item_id)
                take_group = [self._require_take(item, take_id) for take_id in take_group_ids]
                for take in take_group:
                    take.status = "running"
                    take.started_at = utc_now()
                    take.completed_at = None
                    take.error = None
                item.error = None
                batch.last_updated_at = utc_now()
                self._persist_state_locked()

            max_attempts = retry_count + 1
            for attempt in range(1, max_attempts + 1):
                target_paths: list[Path] = []
                for take in take_group:
                    target_path = Path(take.output_path or "")
                    if take.output_path:
                        target_path.unlink(missing_ok=True)
                    target_paths.append(target_path)

                try:
                    _tts_debug(
                        f"Batch {batch_id}: row {item.row_number} takes "
                        f"{', '.join(take.take_label for take in take_group)} "
                        f"attempt {attempt}/{max_attempts}."
                    )
                    automation.fill_text(prompt_text)
                    automation.generate_and_download_many(target_paths)
                except Exception as exc:  # noqa: BLE001
                    message = _format_exception_message(exc)
                    _tts_debug(
                        f"Batch {batch_id}: row {item.row_number} takes "
                        f"{', '.join(take.take_label for take in take_group)} failed: {message}"
                    )
                    should_retry = attempt < max_attempts and not cancel_event.is_set()
                    with self._lock:
                        batch = self._require_batch(batch_id)
                        item = self._require_item(batch, item_id)
                        refreshed_group = [self._require_take(item, take_id) for take_id in take_group_ids]
                        group_error = (
                            f"{message} Retrying {attempt}/{retry_count}..."
                            if should_retry and retry_count > 0
                            else message
                        )
                        for take in refreshed_group:
                            take.error = group_error
                            if not should_retry:
                                take.status = "failed"
                                take.completed_at = utc_now()
                        item.error = group_error
                        batch.last_updated_at = utc_now()
                        self._persist_state_locked()
                    if should_retry:
                        continue
                else:
                    _tts_debug(
                        f"Batch {batch_id}: row {item.row_number} takes "
                        f"{', '.join(take.take_label for take in take_group)} completed."
                    )
                    with self._lock:
                        batch = self._require_batch(batch_id)
                        item = self._require_item(batch, item_id)
                        refreshed_group = [self._require_take(item, take_id) for take_id in take_group_ids]
                        for take in refreshed_group:
                            take.status = "completed"
                            take.error = None
                            take.completed_at = utc_now()
                        if item.picked_take_id is None and refreshed_group:
                            item.picked_take_id = refreshed_group[0].id
                        item.error = None
                        batch.last_updated_at = utc_now()
                        self._persist_state_locked()
                    break
                break

        with self._lock:
            batch = self._require_batch(batch_id)
            item = self._require_item(batch, item_id)
            completed_takes = [take for take in item.takes if take.status == "completed"]
            failed_takes = [take for take in item.takes if take.status == "failed"]
            if cancel_event.is_set() and not completed_takes and not failed_takes:
                item.status = "cancelled"
            elif completed_takes:
                item.status = "completed"
            elif failed_takes:
                item.status = "failed"
            else:
                item.status = "cancelled" if cancel_event.is_set() else "queued"
            item.completed_at = utc_now()
            batch.last_updated_at = utc_now()
            self._persist_state_locked()

    def _finalize_batch(self, batch: TtsBatch, cancelled: bool) -> None:
        if cancelled:
            for item in batch.items:
                for take in item.takes:
                    if take.status in {"queued", "running"}:
                        take.status = "cancelled"
                        take.error = None
                        take.completed_at = take.completed_at or utc_now()

                if item.status in {"queued", "running"}:
                    item.status = "cancelled"
                    item.error = None
                    item.completed_at = item.completed_at or utc_now()
            batch.status = "cancelled"
        elif any(item.status == "failed" for item in batch.items):
            batch.status = "completed_with_errors"
        else:
            batch.status = "completed"
        batch.last_updated_at = utc_now()

    def _build_items(
        self,
        entries: list[SheetTextEntry],
        sheet_title: str,
        channel_prefix: str | None,
        batch_dir: Path,
        take_count: int,
        *,
        model_family: str,
    ) -> list[TtsItem]:
        items: list[TtsItem] = []
        used_names: dict[str, int] = {}
        for entry in entries:
            base_name = build_sheet_sequence_stem(sheet_title, entry.sequence_label, channel_prefix)
            suffix = used_names.get(base_name, 0) + 1
            used_names[base_name] = suffix
            output_base = base_name if suffix == 1 else f"{base_name}-{suffix}"
            takes = []
            for take_index, take_label in _iter_take_outputs(take_count, model_family):
                output_name = _build_take_output_name(
                    output_base,
                    take_index=take_index,
                    take_label=take_label,
                    take_count=take_count,
                    model_family=model_family,
                )
                takes.append(
                    TtsTake(
                        id=str(uuid.uuid4()),
                        take_index=take_index,
                        take_label=take_label,
                        output_name=output_name,
                        output_path=str(batch_dir / output_name),
                    )
                )
            items.append(
                TtsItem(
                    id=str(uuid.uuid4()),
                    sequence_label=entry.sequence_label,
                    row_number=entry.row_index + 1,
                    text=entry.text,
                    takes=takes,
                )
            )
        return items

    def _serialize_batch_summary(self, batch: TtsBatch) -> dict:
        stats = self._batch_stats(batch)
        return {
            "id": batch.id,
            "createdAt": batch.created_at,
            "lastUpdatedAt": batch.last_updated_at,
            "status": batch.status,
            "sheetUrl": batch.sheet_url,
            "textColumn": batch.text_column,
            "filenamePrefix": batch.filename_prefix,
            "channelPrefix": batch.channel_prefix,
            "voiceQuery": batch.voice_query,
            "voiceId": batch.voice_id,
            "voiceName": batch.voice_name,
            "voiceLabel": batch.voice_name or batch.voice_query,
            "modelFamily": batch.model_family,
            "takeCount": batch.take_count,
            "retryCount": batch.retry_count,
            "workerCount": batch.worker_count,
            "headless": batch.headless,
            "stats": stats,
        }

    def _serialize_batch_detail(self, batch: TtsBatch) -> dict:
        return {
            **self._serialize_batch_summary(batch),
            "sheetId": batch.sheet_id,
            "gid": batch.gid,
            "sheetAccessMode": batch.sheet_access_mode,
            "tagText": batch.tag_text,
            "workDir": batch.work_dir,
            "items": [self._serialize_item(batch, item) for item in batch.items],
        }

    def _serialize_item(self, batch: TtsBatch, item: TtsItem) -> dict:
        return {
            "id": item.id,
            "sequenceLabel": item.sequence_label,
            "rowNumber": item.row_number,
            "text": item.text,
            "status": item.status,
            "pickedTakeId": item.picked_take_id,
            "message": item.error or self._item_message(item),
            "startedAt": item.started_at,
            "completedAt": item.completed_at,
            "takes": [
                {
                    "id": take.id,
                    "takeIndex": take.take_index,
                    "takeLabel": take.take_label,
                    "status": take.status,
                    "outputName": take.output_name,
                    "outputPath": take.output_path,
                    "error": take.error,
                    "startedAt": take.started_at,
                    "completedAt": take.completed_at,
                    "previewUrl": f"/api/tts/audio/{batch.id}/{take.id}" if take.output_path and Path(take.output_path).exists() else None,
                }
                for take in item.takes
            ],
        }

    def _item_message(self, item: TtsItem) -> str:
        if item.status == "completed":
            selected = self._selected_take_for_item(item)
            return selected.output_name if selected is not None else "Da gen xong."
        if item.status == "running":
            return "Dang gen voice..."
        if item.status == "queued":
            return "Dang cho den luot."
        if item.status == "cancelled":
            return "Da dung batch."
        return "Take nay chua san sang."

    def _selected_take_for_item(self, item: TtsItem) -> TtsTake | None:
        if item.picked_take_id:
            for take in item.takes:
                if take.id == item.picked_take_id and take.status == "completed":
                    return take
        for take in item.takes:
            if take.status == "completed":
                return take
        return None

    def _batch_stats(self, batch: TtsBatch) -> dict:
        return {
            "queued": sum(1 for item in batch.items if item.status == "queued"),
            "running": sum(1 for item in batch.items if item.status == "running"),
            "completed": sum(1 for item in batch.items if item.status == "completed"),
            "failed": sum(1 for item in batch.items if item.status == "failed"),
            "cancelled": sum(1 for item in batch.items if item.status == "cancelled"),
            "total": len(batch.items),
        }

    def _require_batch(self, batch_id: str) -> TtsBatch:
        batch = self._batches.get(batch_id)
        if batch is None:
            raise ValueError("TTS batch not found.")
        return batch

    def _require_item(self, batch: TtsBatch, item_id: str) -> TtsItem:
        for item in batch.items:
            if item.id == item_id:
                return item
        raise ValueError("TTS item not found.")

    def _require_take(self, item: TtsItem, take_id: str) -> TtsTake:
        for take in item.takes:
            if take.id == take_id:
                return take
        raise ValueError("TTS take not found.")

    def _persist_state_locked(self) -> None:
        payload = {
            "batches": [
                self._serialize_batch_detail(batch)
                for batch in sorted(self._batches.values(), key=lambda current: current.created_at)
            ]
        }
        _ensure_directory(self._state_file.parent)
        self._state_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_state(self) -> None:
        if not self._state_file.exists():
            return
        try:
            payload = json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        loaded_batches: dict[str, TtsBatch] = {}
        cancel_events: dict[str, threading.Event] = {}
        for raw_batch in payload.get("batches", []):
            try:
                batch = self._deserialize_batch(raw_batch)
            except (KeyError, TypeError, ValueError):
                continue
            self._normalize_loaded_batch(batch)
            loaded_batches[batch.id] = batch
            cancel_events[batch.id] = threading.Event()

        self._batches = loaded_batches
        self._cancel_events = cancel_events

    def _deserialize_batch(self, payload: dict) -> TtsBatch:
        return TtsBatch(
            id=str(payload["id"]),
            created_at=str(payload["createdAt"]),
            last_updated_at=str(payload.get("lastUpdatedAt") or payload["createdAt"]),
            status=str(payload["status"]),
            sheet_url=str(payload["sheetUrl"]),
            sheet_id=str(payload["sheetId"]),
            gid=None if payload.get("gid") is None else str(payload.get("gid")),
            sheet_access_mode=str(payload.get("sheetAccessMode", "")),
            text_column=str(payload.get("textColumn", "")),
            voice_query=str(payload["voiceQuery"]),
            voice_id=None if payload.get("voiceId") is None else str(payload.get("voiceId")),
            voice_name=None if payload.get("voiceName") is None else str(payload.get("voiceName")),
            model_family=str(payload["modelFamily"]),
            tag_text=str(payload.get("tagText", "")),
            take_count=int(payload.get("takeCount", 1)),
            retry_count=int(payload.get("retryCount", 0)),
            worker_count=int(payload.get("workerCount", 1)),
            headless=bool(payload.get("headless", False)),
            work_dir=str(payload["workDir"]),
            filename_prefix=None if payload.get("filenamePrefix") is None else str(payload.get("filenamePrefix")),
            channel_prefix=None if payload.get("channelPrefix") is None else str(payload.get("channelPrefix")),
            items=[
                self._deserialize_item(item_payload, model_family=str(payload["modelFamily"]))
                for item_payload in payload.get("items", [])
            ],
        )

    def _deserialize_item(self, payload: dict, *, model_family: str) -> TtsItem:
        message = str(payload.get("message") or "")
        sequence_label = str(payload["sequenceLabel"])
        item = TtsItem(
            id=str(payload["id"]),
            sequence_label=sequence_label,
            row_number=int(payload["rowNumber"]),
            text=str(payload["text"]),
            status=str(payload["status"]),
            picked_take_id=None if payload.get("pickedTakeId") is None else str(payload.get("pickedTakeId")),
            error=message if str(payload["status"]) == "failed" and message else None,
            started_at=None if payload.get("startedAt") is None else str(payload.get("startedAt")),
            completed_at=None if payload.get("completedAt") is None else str(payload.get("completedAt")),
            takes=[
                self._deserialize_take(
                    take_payload,
                    sequence_label=sequence_label,
                    model_family=model_family,
                )
                for take_payload in payload.get("takes", [])
            ],
        )
        if item.error is None:
            item.error = next((take.error for take in item.takes if take.error), None)
        return item

    def _deserialize_take(self, payload: dict, *, sequence_label: str, model_family: str) -> TtsTake:
        take_index = int(payload["takeIndex"])
        return TtsTake(
            id=str(payload["id"]),
            take_index=take_index,
            take_label=str(payload.get("takeLabel") or _format_take_label(sequence_label, take_index, model_family)),
            output_name=str(payload["outputName"]),
            status=str(payload["status"]),
            output_path=None if payload.get("outputPath") is None else str(payload.get("outputPath")),
            error=None if payload.get("error") is None else str(payload.get("error")),
            started_at=None if payload.get("startedAt") is None else str(payload.get("startedAt")),
            completed_at=None if payload.get("completedAt") is None else str(payload.get("completedAt")),
        )

    def _normalize_loaded_batch(self, batch: TtsBatch) -> None:
        if batch.status not in ACTIVE_BATCH_STATUSES:
            return

        now = utc_now()
        error_message = "TTS batch dang chay thi app bi restart. Hay bam Retry Failed de gen lai."
        for item in batch.items:
            if item.status in {"queued", "running"}:
                item.status = "failed"
                item.error = error_message
                item.completed_at = now
            for take in item.takes:
                if take.status in {"queued", "running"}:
                    take.status = "failed"
                    take.error = error_message
                    take.completed_at = now

        batch.status = "completed_with_errors"
        batch.last_updated_at = now

    def _reset_item_for_retry(self, item: TtsItem) -> None:
        item.status = "queued"
        item.error = None
        item.started_at = None
        item.completed_at = None
        item.picked_take_id = None
        for take in item.takes:
            take.status = "queued"
            take.error = None
            take.started_at = None
            take.completed_at = None


def run_login_window() -> None:
    browser = detect_tts_login_browser()
    if sys.platform == "win32":
        command = [str(browser.executable_path), ELEVENLABS_LOGIN_URL]
    else:
        command = ["open", "-a", str(browser.app_path), ELEVENLABS_LOGIN_URL]

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "Khong mo duoc ElevenLabs login.").strip()
        raise ElevenLabsError(message)


tts_manager = TtsManager()
