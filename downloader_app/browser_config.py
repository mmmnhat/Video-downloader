from __future__ import annotations

import json
import os
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
FEATURE_IDS = ("downloader", "tts", "story")
FEATURE_COOKIE_DOMAINS: dict[str, tuple[str, ...]] = {
    "downloader": ("google.com",),
    "tts": ("elevenlabs.io",),
    "story": ("gemini.google.com", "google.com", "accounts.google.com"),
}


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

        raise BrowserConfigError("Chỉ hỗ trợ manual browser settings trên Windows/macOS.")


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
        app_aliases=("Cốc Cốc.app",),
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


def _feature_domains(feature: str) -> tuple[str, ...]:
    normalized = str(feature or "").strip().lower()
    if normalized not in FEATURE_IDS:
        raise BrowserConfigError(f"Feature không hợp lệ: {feature}")
    return FEATURE_COOKIE_DOMAINS[normalized]


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
                exe_path = root.joinpath(*spec.windows_path_parts[:-1], "Application", spec.executable_names[0])
                app_path = exe_path.parent
                if exe_path in seen:
                    continue
                seen.add(exe_path)
                installations.append(
                    BrowserInstallation(
                        spec=spec,
                        app_path=app_path,
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
        f"Không nhận ra browser từ đường dẫn này. Hiện chỉ hỗ trợ: {supported}."
    )


def resolve_installation_from_browser_path(raw_path: str) -> BrowserInstallation:
    if not raw_path or not str(raw_path).strip():
        raise BrowserConfigError("Cần nhập browser path.")

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
            raise BrowserConfigError("Trên macOS hãy nhập đường dẫn `.app` hoặc file executable bên trong app.")

        if not app_path.exists():
            raise BrowserConfigError(f"Không tìm thấy app: {app_path}")
        if not executable_path.exists():
            executable_path = app_path / "Contents" / "MacOS" / spec.mac_executable_name
        if not executable_path.exists():
            raise BrowserConfigError(f"Không tìm thấy executable trong app: {app_path}")
        return BrowserInstallation(
            spec=spec,
            app_path=app_path,
            executable_path=executable_path,
            user_data_dir=spec.user_data_dir(),
        )

    if sys.platform == "win32":
        if path.is_dir():
            executable_path = path / spec.executable_names[0]
            app_path = path
        else:
            executable_path = path
            app_path = path.parent
        if not executable_path.exists():
            raise BrowserConfigError(f"Không tìm thấy executable: {executable_path}")
        return BrowserInstallation(
            spec=spec,
            app_path=app_path,
            executable_path=executable_path,
            user_data_dir=spec.user_data_dir(),
        )

    raise BrowserConfigError("Chỉ hỗ trợ manual browser settings trên Windows/macOS.")


def iter_profile_dirs(user_data_dir: Path) -> list[Path]:
    default_profile = user_data_dir / "Default"
    other_profiles = sorted(
        path for path in user_data_dir.glob("Profile *") if path.is_dir()
    )
    guest_profile = user_data_dir / "Guest Profile"
    ordered = [default_profile, *other_profiles]
    if guest_profile.is_dir():
        ordered.append(guest_profile)
    return [path for path in ordered if path.is_dir()]


def _chromium_cookie_paths(profile_dir: Path) -> list[Path]:
    return [
        profile_dir / "Network" / "Cookies",
        profile_dir / "Cookies",
    ]


def _get_profile_display_names(user_data_dir: Path) -> dict[str, str]:
    local_state_path = user_data_dir / "Local State"
    if not local_state_path.exists():
        return {}

    try:
        data = json.loads(local_state_path.read_text(encoding="utf-8"))
        info_cache = data.get("profile", {}).get("info_cache", {})
        names = {}
        for dir_name, info in info_cache.items():
            name = info.get("name", "")
            given_name = info.get("gaia_given_name", "")
            if given_name and name:
                display = f"{given_name} ({name})"
            else:
                display = name or given_name or dir_name
            names[dir_name] = display
        return names
    except Exception:
        return {}


def count_cookies_for_domains(profile_dir: Path, domains: tuple[str, ...]) -> int:
    counts = [
        _cookie_count_from_db(cookie_path, domains)
        for cookie_path in _chromium_cookie_paths(profile_dir)
    ]
    return max(counts, default=0)


def _cookie_count_from_db(cookie_path: Path, domains: tuple[str, ...]) -> int:
    if not cookie_path.exists():
        return 0

    temp_copy: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as handle:
            temp_copy = Path(handle.name)
        
        # Robust copy for locked files on Windows
        try:
            shutil.copyfile(cookie_path, temp_copy)
        except Exception:
            # Fallback 1: win32file (most robust)
            if sys.platform == "win32":
                try:
                    import win32file
                    import win32con
                    handle = win32file.CreateFile(
                        str(cookie_path),
                        win32con.GENERIC_READ,
                        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
                        None,
                        win32con.OPEN_EXISTING,
                        win32con.FILE_ATTRIBUTE_NORMAL,
                        None
                    )
                    try:
                        with open(temp_copy, "wb") as fdst:
                            while True:
                                res, data = win32file.ReadFile(handle, 1024 * 1024)
                                if not data: break
                                fdst.write(data)
                    finally:
                        handle.Close()
                except Exception:
                    pass

            if not temp_copy.exists() or temp_copy.stat().st_size == 0:
                try:
                    src_p = str(cookie_path.absolute())
                    if sys.platform == "win32":
                        src_p = src_p.replace("\\", "/")
                        if not src_p.startswith("/"):
                            src_p = "/" + src_p
                    
                    # nolock=1 and immutable=1 are key for reading locked SQLite files
                    src_uri = f"file://{src_p}?mode=ro&nolock=1&immutable=1"
                    
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
                    # Fallback 3: cmd copy
                    if sys.platform == "win32":
                        try:
                            subprocess.run(["cmd", "/c", "copy", "/y", str(cookie_path), str(temp_copy)], 
                                           capture_output=True, timeout=2, check=False)
                        except Exception:
                            pass
        
        if not temp_copy.exists() or temp_copy.stat().st_size == 0:
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


def choose_profile_dir(
    user_data_dir: Path,
    *,
    feature: str,
    preferred_name: str = "",
) -> Path:
    profile_dirs = iter_profile_dirs(user_data_dir)
    if not profile_dirs:
        raise BrowserConfigError(
            f"Không tìm thấy profile trong thư mục dữ liệu: {user_data_dir}"
        )

    preferred_name = str(preferred_name or "").strip()
    if preferred_name:
        for profile_dir in profile_dirs:
            if profile_dir.name == preferred_name:
                return profile_dir
        raise BrowserConfigError(
            f"Không tìm thấy profile `{preferred_name}` trong {user_data_dir}"
        )

    domains = _feature_domains(feature)
    ranked = [
        (count_cookies_for_domains(profile_dir, domains), profile_dir)
        for profile_dir in profile_dirs
    ]
    ranked.sort(key=lambda item: item[0], reverse=True)
    if ranked and ranked[0][0] > 0:
        return ranked[0][1]

    for profile_dir in profile_dirs:
        if profile_dir.name == "Default":
            return profile_dir
    return profile_dirs[0]


def detect_profiles_for_browser_path(
    *,
    feature: str,
    browser_path: str,
    profile_name: str = "",
) -> dict:
    installation = resolve_installation_from_browser_path(browser_path)
    if not installation.user_data_dir.exists():
        raise BrowserConfigError(
            f"Không tìm thấy user data dir cho {installation.name}: {installation.user_data_dir}"
        )

    domains = _feature_domains(feature)
    display_names = _get_profile_display_names(installation.user_data_dir)
    profiles = [
        BrowserProfileOption(
            name=profile_dir.name,
            display_name=display_names.get(profile_dir.name, profile_dir.name),
            path=str(profile_dir),
            cookie_count=count_cookies_for_domains(profile_dir, domains),
        )
        for profile_dir in iter_profile_dirs(installation.user_data_dir)
    ]
    selected_profile = choose_profile_dir(
        installation.user_data_dir,
        feature=feature,
        preferred_name=profile_name,
    )

    return {
        "browserName": installation.name,
        "appPath": str(installation.app_path),
        "executablePath": str(installation.executable_path),
        "userDataDir": str(installation.user_data_dir),
        "profiles": [asdict(profile) for profile in profiles],
        "selectedProfileName": selected_profile.name,
        "selectedProfileDir": str(selected_profile),
        "message": f"Đã nhận diện {len(profiles)} profile cho {installation.name}.",
    }


def detect_auto_browser_profile(*, feature: str) -> dict:
    last_error: Exception | None = None
    for installation in _auto_installations():
        if not installation.executable_path.exists() or not installation.user_data_dir.exists():
            continue
        try:
            profile_dir = choose_profile_dir(installation.user_data_dir, feature=feature)
        except BrowserConfigError as exc:
            last_error = exc
            continue
        return {
            "browserName": installation.name,
            "appPath": str(installation.app_path),
            "executablePath": str(installation.executable_path),
            "userDataDir": str(installation.user_data_dir),
            "profileName": profile_dir.name,
            "profileDir": str(profile_dir),
        }

    if last_error is not None:
        raise BrowserConfigError(str(last_error)) from last_error
    raise BrowserConfigError("Không tìm thấy browser/profile phù hợp trên máy này.")


def launch_browser_with_profile(*, feature: str, target_url: str) -> dict:
    config = browser_config_manager.get_feature(feature)
    if config.browser_path:
        detected = detect_profiles_for_browser_path(
            feature=feature,
            browser_path=config.browser_path,
            profile_name=config.profile_name,
        )
        executable_path = Path(detected["executablePath"])
        profile_name = str(detected["selectedProfileName"])
        browser_name = str(detected["browserName"])
        popen_kwargs: dict[str, object] = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        subprocess.Popen(
            [
                str(executable_path),
                *( [f"--profile-directory={profile_name}"] if profile_name else [] ),
                target_url,
            ],
            **popen_kwargs,
        )
        return {
            "opened": True,
            "url": target_url,
            "browser": browser_name,
            "profileDir": str(detected["selectedProfileDir"]),
        }

    auto = detect_auto_browser_profile(feature=feature)
    popen_kwargs = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    subprocess.Popen(
        [
            auto["executablePath"],
            f"--profile-directory={auto['profileName']}",
            target_url,
        ],
        **popen_kwargs,
    )
    return {
        "opened": True,
        "url": target_url,
        "browser": auto["browserName"],
        "profileDir": auto["profileDir"],
    }


class BrowserConfigManager:
    def __init__(self, state_file: Path | None = None) -> None:
        self._state_file = state_file or BROWSER_CONFIG_FILE
        self._lock = threading.RLock()
        self._state = BrowserConfigState(
            downloader=FeatureBrowserConfig(),
            tts=FeatureBrowserConfig(),
            story=FeatureBrowserConfig(),
        )
        self._load()

    def get_all(self) -> dict:
        with self._lock:
            return asdict(self._state)

    def get_feature(self, feature: str) -> FeatureBrowserConfig:
        if feature not in FEATURE_IDS:
            raise BrowserConfigError(f"Feature không hợp lệ: {feature}")
        with self._lock:
            current = getattr(self._state, feature)
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
                setattr(
                    self._state,
                    feature,
                    FeatureBrowserConfig(
                        browser_path=str(raw_feature.get("browser_path", "")).strip(),
                        profile_name=str(raw_feature.get("profile_name", "")).strip(),
                    ),
                )
            self._persist_locked()
            return asdict(self._state)

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
        self.update(payload)


browser_config_manager = BrowserConfigManager()
