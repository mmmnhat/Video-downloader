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
from dataclasses import asdict, dataclass
from pathlib import Path

from downloader_app.runtime import app_path


BROWSER_CONFIG_FILE = app_path("browser_config.json")
APP_PROFILE_ROOT = app_path("cache", "browser_profiles")
FEATURE_IDS = ("downloader", "tts", "story")
FEATURE_COOKIE_DOMAINS: dict[str, tuple[str, ...]] = {
    "downloader": ("google.com",),
    "tts": ("elevenlabs.io",),
    "story": ("gemini.google.com", "google.com", "accounts.google.com"),
}
DEFAULT_MANAGED_PROFILE_NAME = "Default"
CHROMIUM_PROFILE_DIR_NAME = "Default"
INVALID_PROFILE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class BrowserConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserSpec:
    key: str
    name: str
    loader_name: str
    executable_names: tuple[str, ...]
    windows_path_parts: tuple[str, ...]
    mac_app_name: str
    mac_executable_name: str
    mac_user_data_parts: tuple[str, ...]
    bundle_ids: tuple[str, ...] = ()
    app_aliases: tuple[str, ...] = ()

    def user_data_dir(self) -> Path:
        if sys.platform == "win32":
            local_app_data = Path(
                os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))
            )
            return local_app_data.joinpath(*self.windows_path_parts)

        if sys.platform == "darwin":
            return Path.home().joinpath("Library", "Application Support", *self.mac_user_data_parts)

        raise BrowserConfigError("Chi ho tro browser Chromium tren Windows/macOS.")


@dataclass(frozen=True)
class BrowserInstallation:
    spec: BrowserSpec
    app_path: Path
    executable_path: Path
    user_data_dir: Path

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def loader_name(self) -> str:
        return self.spec.loader_name


@dataclass(frozen=True)
class BrowserProfileOption:
    name: str
    display_name: str
    path: str
    cookie_count: int


@dataclass(frozen=True)
class ManagedProfile:
    feature: str
    name: str
    root_dir: Path
    profile_dir: Path


@dataclass
class FeatureBrowserConfig:
    browser_path: str = ""
    profile_name: str = ""


@dataclass
class BrowserConfigState:
    downloader: FeatureBrowserConfig
    tts: FeatureBrowserConfig
    story: FeatureBrowserConfig


BROWSER_SPECS: tuple[BrowserSpec, ...] = (
    BrowserSpec(
        key="coccoc",
        name="CocCoc",
        loader_name="coccoc",
        executable_names=("browser.exe", "CocCoc"),
        windows_path_parts=("CocCoc", "Browser", "User Data"),
        mac_app_name="CocCoc.app",
        mac_executable_name="CocCoc",
        mac_user_data_parts=("CocCoc", "Browser"),
        bundle_ids=("com.coccoc.Coccoc",),
        app_aliases=("Coc Coc.app",),
    ),
    BrowserSpec(
        key="chrome",
        name="Chrome",
        loader_name="chrome",
        executable_names=("chrome.exe", "Google Chrome"),
        windows_path_parts=("Google", "Chrome", "User Data"),
        mac_app_name="Google Chrome.app",
        mac_executable_name="Google Chrome",
        mac_user_data_parts=("Google", "Chrome"),
        bundle_ids=("com.google.Chrome",),
    ),
    BrowserSpec(
        key="edge",
        name="Edge",
        loader_name="edge",
        executable_names=("msedge.exe", "Microsoft Edge"),
        windows_path_parts=("Microsoft", "Edge", "User Data"),
        mac_app_name="Microsoft Edge.app",
        mac_executable_name="Microsoft Edge",
        mac_user_data_parts=("Microsoft Edge",),
        bundle_ids=("com.microsoft.edgemac",),
    ),
)


def _normalize_feature(feature: str) -> str:
    normalized = str(feature or "").strip().lower()
    if normalized not in FEATURE_IDS:
        raise BrowserConfigError(f"Feature khong hop le: {feature}")
    return normalized


def _feature_domains(feature: str) -> tuple[str, ...]:
    return FEATURE_COOKIE_DOMAINS[_normalize_feature(feature)]


def _resolve_macos_app_bundle(spec: BrowserSpec) -> Path:
    default_path = Path("/Applications") / spec.mac_app_name
    direct_candidates = [
        default_path,
        Path.home() / "Applications" / spec.mac_app_name,
    ]
    for candidate in direct_candidates:
        if candidate.exists():
            return candidate

    queries: list[str] = []
    for bundle_id in spec.bundle_ids:
        queries.append(f"kMDItemCFBundleIdentifier == '{bundle_id}'")
    for app_name in (spec.mac_app_name, *spec.app_aliases):
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


def _auto_installations() -> list[BrowserInstallation]:
    installations: list[BrowserInstallation] = []
    if sys.platform == "win32":
        local_app_data = Path(
            os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))
        )
        program_files = Path(os.environ.get("ProgramFiles", "C:\\Program Files"))
        program_files_x86 = Path(
            os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        )
        roots = (program_files, program_files_x86, local_app_data)

        for spec in BROWSER_SPECS:
            seen: set[Path] = set()
            for root in roots:
                exe_path = root.joinpath(
                    *spec.windows_path_parts[:-1],
                    "Application",
                    spec.executable_names[0],
                )
                if exe_path in seen:
                    continue
                seen.add(exe_path)
                installations.append(
                    BrowserInstallation(
                        spec=spec,
                        app_path=exe_path.parent,
                        executable_path=exe_path,
                        user_data_dir=spec.user_data_dir(),
                    )
                )
    elif sys.platform == "darwin":
        for spec in BROWSER_SPECS:
            app_path = _resolve_macos_app_bundle(spec)
            installations.append(
                BrowserInstallation(
                    spec=spec,
                    app_path=app_path,
                    executable_path=app_path / "Contents" / "MacOS" / spec.mac_executable_name,
                    user_data_dir=spec.user_data_dir(),
                )
            )
    return installations


def _path_matches_spec(path: Path, spec: BrowserSpec) -> bool:
    lowered = str(path).lower()
    key_hits = (
        spec.key.lower(),
        spec.name.lower(),
        *(name.lower() for name in spec.executable_names),
        spec.mac_app_name.lower(),
        *(alias.lower() for alias in spec.app_aliases),
    )
    return any(hit and hit in lowered for hit in key_hits)


def _spec_from_browser_path(raw_path: str) -> BrowserSpec:
    candidate_path = Path(raw_path).expanduser()
    for spec in BROWSER_SPECS:
        if _path_matches_spec(candidate_path, spec):
            return spec
    supported = ", ".join(spec.name for spec in BROWSER_SPECS)
    raise BrowserConfigError(
        f"Khong nhan ra browser tu duong dan nay. Hien chi ho tro: {supported}."
    )


def resolve_installation_from_browser_path(raw_path: str) -> BrowserInstallation:
    if not raw_path or not str(raw_path).strip():
        raise BrowserConfigError("Can nhap browser path.")

    path = Path(str(raw_path).strip()).expanduser()
    spec = _spec_from_browser_path(path)

    if sys.platform == "darwin":
        app_path = path
        executable_path = path
        if path.suffix.lower() == ".app":
            app_path = path
            executable_path = path / "Contents" / "MacOS" / spec.mac_executable_name
        elif ".app/" in path.as_posix():
            parts = path.as_posix().split(".app/", 1)[0] + ".app"
            app_path = Path(parts)
        else:
            raise BrowserConfigError("Tren macOS hay nhap duong dan `.app` hoac executable trong app.")

        if not app_path.exists():
            raise BrowserConfigError(f"Khong tim thay app: {app_path}")
        if not executable_path.exists():
            executable_path = app_path / "Contents" / "MacOS" / spec.mac_executable_name
        if not executable_path.exists():
            raise BrowserConfigError(f"Khong tim thay executable trong app: {app_path}")
        return BrowserInstallation(
            spec=spec,
            app_path=app_path,
            executable_path=executable_path,
            user_data_dir=spec.user_data_dir(),
        )

    if sys.platform == "win32":
        executable_path = path / spec.executable_names[0] if path.is_dir() else path
        if not executable_path.exists():
            raise BrowserConfigError(f"Khong tim thay executable: {executable_path}")
        return BrowserInstallation(
            spec=spec,
            app_path=executable_path.parent,
            executable_path=executable_path,
            user_data_dir=spec.user_data_dir(),
        )

    raise BrowserConfigError("Chi ho tro browser Chromium tren Windows/macOS.")


def _detect_auto_installation() -> BrowserInstallation:
    for installation in _auto_installations():
        if installation.executable_path.exists():
            return installation
    raise BrowserConfigError("Khong tim thay Chrome/Edge/CocCoc tren may nay.")


def _managed_feature_root(feature: str) -> Path:
    return APP_PROFILE_ROOT / _normalize_feature(feature)


def _sanitize_profile_name(profile_name: str) -> str:
    name = " ".join(str(profile_name or "").split()).strip()
    if not name:
        raise BrowserConfigError("Ten profile khong duoc de trong.")
    name = INVALID_PROFILE_CHARS.sub("-", name).strip(" .")
    if not name:
        raise BrowserConfigError("Ten profile khong hop le.")
    return name[:80]


def _profile_sort_key(path: Path) -> tuple[int, str]:
    if path.name == DEFAULT_MANAGED_PROFILE_NAME:
        return (0, path.name.lower())
    return (1, path.name.lower())


def _ensure_managed_profile_dirs(root_dir: Path) -> None:
    root_dir.mkdir(parents=True, exist_ok=True)
    (root_dir / CHROMIUM_PROFILE_DIR_NAME).mkdir(parents=True, exist_ok=True)


def _list_managed_profile_dirs(feature: str) -> list[Path]:
    feature_root = _managed_feature_root(feature)
    feature_root.mkdir(parents=True, exist_ok=True)
    profile_dirs = sorted(
        [path for path in feature_root.iterdir() if path.is_dir()],
        key=_profile_sort_key,
    )
    if not profile_dirs:
        default_root = feature_root / DEFAULT_MANAGED_PROFILE_NAME
        _ensure_managed_profile_dirs(default_root)
        profile_dirs = [default_root]
    else:
        for root_dir in profile_dirs:
            _ensure_managed_profile_dirs(root_dir)
    return profile_dirs


def _managed_profile_from_root(feature: str, root_dir: Path) -> ManagedProfile:
    _ensure_managed_profile_dirs(root_dir)
    return ManagedProfile(
        feature=_normalize_feature(feature),
        name=root_dir.name,
        root_dir=root_dir,
        profile_dir=root_dir / CHROMIUM_PROFILE_DIR_NAME,
    )


def _managed_profile_cookie_count(profile: ManagedProfile, domains: tuple[str, ...]) -> int:
    return count_cookies_for_domains(profile.profile_dir, domains)


def list_managed_profiles(feature: str) -> list[BrowserProfileOption]:
    normalized = _normalize_feature(feature)
    domains = _feature_domains(normalized)
    profiles: list[BrowserProfileOption] = []
    for root_dir in _list_managed_profile_dirs(normalized):
        profile = _managed_profile_from_root(normalized, root_dir)
        profiles.append(
            BrowserProfileOption(
                name=profile.name,
                display_name=profile.name,
                path=str(profile.root_dir),
                cookie_count=_managed_profile_cookie_count(profile, domains),
            )
        )
    return profiles


def choose_managed_profile(feature: str, preferred_name: str = "") -> ManagedProfile:
    normalized = _normalize_feature(feature)
    root_dirs = _list_managed_profile_dirs(normalized)
    preferred = str(preferred_name or "").strip()
    if preferred:
        for root_dir in root_dirs:
            if root_dir.name == preferred:
                return _managed_profile_from_root(normalized, root_dir)
        raise BrowserConfigError(
            f"Khong tim thay profile `{preferred}` trong {_managed_feature_root(normalized)}"
        )
    return _managed_profile_from_root(normalized, root_dirs[0])


def create_managed_profile(feature: str, profile_name: str = "") -> dict:
    normalized = _normalize_feature(feature)
    existing = {profile.name for profile in list_managed_profiles(normalized)}
    requested_name = str(profile_name or "").strip()

    if requested_name:
        final_name = _sanitize_profile_name(requested_name)
    else:
        index = 1
        while True:
            candidate = f"Profile {index}"
            if candidate not in existing:
                final_name = candidate
                break
            index += 1

    if final_name in existing:
        raise BrowserConfigError(f"Profile `{final_name}` da ton tai.")

    root_dir = _managed_feature_root(normalized) / final_name
    _ensure_managed_profile_dirs(root_dir)
    return {
        "created": True,
        "profileName": final_name,
        "profileDir": str(root_dir / CHROMIUM_PROFILE_DIR_NAME),
        "profiles": [asdict(profile) for profile in list_managed_profiles(normalized)],
    }


def delete_managed_profile(feature: str, profile_name: str) -> dict:
    normalized = _normalize_feature(feature)
    target_name = str(profile_name or "").strip()
    if not target_name:
        raise BrowserConfigError("profile_name is required.")

    profiles = list_managed_profiles(normalized)
    if len(profiles) <= 1:
        raise BrowserConfigError("Phai giu lai it nhat 1 profile cho moi khu vuc.")

    root_dir = _managed_feature_root(normalized) / target_name
    if not root_dir.exists() or not root_dir.is_dir():
        raise BrowserConfigError(f"Khong tim thay profile `{target_name}`.")

    shutil.rmtree(root_dir, ignore_errors=True)
    browser_config_manager.ensure_profile_selected(normalized)
    return {
        "deleted": True,
        "profileName": target_name,
        "profiles": [asdict(profile) for profile in list_managed_profiles(normalized)],
        "config": browser_config_manager.get_all(),
    }


def _cookie_count_from_db(cookie_path: Path, domains: tuple[str, ...]) -> int:
    if not cookie_path.exists():
        return 0

    temp_copy: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as handle:
            temp_copy = Path(handle.name)

        try:
            shutil.copyfile(cookie_path, temp_copy)
        except Exception:
            try:
                src_path = str(cookie_path.absolute())
                if sys.platform == "win32":
                    src_path = src_path.replace("\\", "/")
                    if not src_path.startswith("/"):
                        src_path = "/" + src_path
                src_uri = f"file://{src_path}?mode=ro&nolock=1&immutable=1"
                src_conn = sqlite3.connect(src_uri, uri=True)
                try:
                    dst_conn = sqlite3.connect(temp_copy)
                    try:
                        src_conn.backup(dst_conn)
                    finally:
                        dst_conn.close()
                finally:
                    src_conn.close()
            except Exception:
                return 0

        clauses: list[str] = []
        params: list[str] = []
        for domain in domains:
            clauses.append("(host_key = ? OR host_key LIKE ?)")
            params.append(domain)
            params.append(f"%.{domain}")
        if not clauses:
            return 0

        connection = sqlite3.connect(temp_copy)
        try:
            row = connection.execute(
                f"SELECT COUNT(*) FROM cookies WHERE {' OR '.join(clauses)}",
                tuple(params),
            ).fetchone()
        finally:
            connection.close()
    except Exception:
        return 0
    finally:
        if temp_copy is not None:
            temp_copy.unlink(missing_ok=True)

    return int(row[0]) if row else 0


def _chromium_cookie_paths(profile_dir: Path) -> list[Path]:
    return [
        profile_dir / "Network" / "Cookies",
        profile_dir / "Cookies",
    ]


def count_cookies_for_domains(profile_dir: Path, domains: tuple[str, ...]) -> int:
    counts = [
        _cookie_count_from_db(cookie_path, domains)
        for cookie_path in _chromium_cookie_paths(profile_dir)
    ]
    return max(counts, default=0)


def _runtime_profile_payload(
    *,
    feature: str,
    installation: BrowserInstallation,
    managed_profile: ManagedProfile,
) -> dict:
    return {
        "browserName": installation.name,
        "appPath": str(installation.app_path),
        "executablePath": str(installation.executable_path),
        "userDataDir": str(managed_profile.root_dir),
        "profileName": managed_profile.profile_dir.name,
        "profileDir": str(managed_profile.profile_dir),
        "appProfileName": managed_profile.name,
    }


def detect_profiles_for_browser_path(
    *,
    feature: str,
    browser_path: str,
    profile_name: str = "",
) -> dict:
    normalized = _normalize_feature(feature)
    installation = (
        resolve_installation_from_browser_path(browser_path)
        if str(browser_path or "").strip()
        else _detect_auto_installation()
    )
    profiles = list_managed_profiles(normalized)
    selected_profile = choose_managed_profile(normalized, preferred_name=profile_name)
    payload = _runtime_profile_payload(
        feature=normalized,
        installation=installation,
        managed_profile=selected_profile,
    )
    payload.update(
        {
            "profiles": [asdict(profile) for profile in profiles],
            "selectedProfileName": selected_profile.name,
            "selectedProfileDir": str(selected_profile.profile_dir),
            "message": f"Da nhan dien {len(profiles)} profile rieng cua app cho {installation.name}.",
        }
    )
    return payload


def detect_auto_browser_profile(*, feature: str, profile_name: str = "") -> dict:
    normalized = _normalize_feature(feature)
    installation = _detect_auto_installation()
    managed_profile = choose_managed_profile(normalized, preferred_name=profile_name)
    return _runtime_profile_payload(
        feature=normalized,
        installation=installation,
        managed_profile=managed_profile,
    )


def resolve_feature_browser_profile(feature: str) -> dict:
    normalized = _normalize_feature(feature)
    config = browser_config_manager.get_feature(normalized)
    if config.browser_path:
        return detect_profiles_for_browser_path(
            feature=normalized,
            browser_path=config.browser_path,
            profile_name=config.profile_name,
        )
    return detect_auto_browser_profile(
        feature=normalized,
        profile_name=config.profile_name,
    )


def launch_browser_with_profile(*, feature: str, target_url: str) -> dict:
    resolved = resolve_feature_browser_profile(feature)
    executable_path = Path(str(resolved["executablePath"]))
    user_data_dir = str(resolved["userDataDir"])
    profile_name = str(resolved["profileName"])
    popen_kwargs: dict[str, object] = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    subprocess.Popen(
        [
            str(executable_path),
            f"--user-data-dir={user_data_dir}",
            f"--profile-directory={profile_name}",
            "--new-window",
            "--no-first-run",
            "--no-default-browser-check",
            target_url,
        ],
        **popen_kwargs,
    )
    return {
        "opened": True,
        "url": target_url,
        "browser": str(resolved["browserName"]),
        "profileDir": str(resolved["profileDir"]),
        "appProfileName": str(resolved["appProfileName"]),
    }


class BrowserConfigManager:
    def __init__(self, state_file: Path | None = None) -> None:
        self._state_file = state_file or BROWSER_CONFIG_FILE
        self._lock = threading.RLock()
        self._state = BrowserConfigState(
            downloader=FeatureBrowserConfig(profile_name=DEFAULT_MANAGED_PROFILE_NAME),
            tts=FeatureBrowserConfig(profile_name=DEFAULT_MANAGED_PROFILE_NAME),
            story=FeatureBrowserConfig(profile_name=DEFAULT_MANAGED_PROFILE_NAME),
        )
        self._load()
        with self._lock:
            for feature in FEATURE_IDS:
                self._ensure_profile_selected_locked(feature)
            self._persist_locked()

    def get_all(self) -> dict:
        with self._lock:
            return asdict(self._state)

    def get_feature(self, feature: str) -> FeatureBrowserConfig:
        normalized = _normalize_feature(feature)
        with self._lock:
            current = getattr(self._state, normalized)
            return FeatureBrowserConfig(
                browser_path=current.browser_path,
                profile_name=current.profile_name,
            )

    def update(self, payload: dict) -> dict:
        with self._lock:
            for feature in FEATURE_IDS:
                raw_feature = payload.get(feature)
                if not isinstance(raw_feature, dict):
                    continue
                profile_name = str(raw_feature.get("profile_name", "")).strip()
                setattr(
                    self._state,
                    feature,
                    FeatureBrowserConfig(
                        browser_path=str(raw_feature.get("browser_path", "")).strip(),
                        profile_name=profile_name,
                    ),
                )
                self._ensure_profile_selected_locked(feature)
            self._persist_locked()
            return asdict(self._state)

    def ensure_profile_selected(self, feature: str) -> dict:
        normalized = _normalize_feature(feature)
        with self._lock:
            self._ensure_profile_selected_locked(normalized)
            self._persist_locked()
            return asdict(self._state)

    def _ensure_profile_selected_locked(self, feature: str) -> None:
        current = getattr(self._state, feature)
        available_names = [profile.name for profile in list_managed_profiles(feature)]
        if current.profile_name in available_names:
            return
        current.profile_name = available_names[0] if available_names else DEFAULT_MANAGED_PROFILE_NAME

    def _persist_locked(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(
            json.dumps(asdict(self._state), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> None:
        if not self._state_file.exists():
            return
        try:
            payload = json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        for feature in FEATURE_IDS:
            raw_feature = payload.get(feature)
            if not isinstance(raw_feature, dict):
                continue
            setattr(
                self._state,
                feature,
                FeatureBrowserConfig(
                    browser_path=str(raw_feature.get("browser_path", "")).strip(),
                    profile_name=str(raw_feature.get("profile_name", "")).strip() or DEFAULT_MANAGED_PROFILE_NAME,
                ),
            )


browser_config_manager = BrowserConfigManager()
