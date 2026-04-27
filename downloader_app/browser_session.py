from __future__ import annotations

import http.cookiejar
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from downloader_app.browser_config import launch_browser_with_profile, resolve_feature_browser_profile


GOOGLE_LOGIN_URL = "https://docs.google.com/spreadsheets/u/0/"


class BrowserSessionError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserCandidate:
    name: str
    loader_name: str


class BrowserSessionManager:
    def __init__(self) -> None:
        self._session_cache: dict | None = None
        self._session_cache_time: float = 0.0
        self._cookiejar_cache: http.cookiejar.CookieJar | None = None
        self._cookiejar_cache_time: float = 0.0
        self._active_candidate: BrowserCandidate | None = None
        self._active_profile_dir: str = ""

    _SESSION_CACHE_TTL = 60

    def _get_cached_status(self) -> dict | None:
        import time

        if self._session_cache is not None and (time.monotonic() - self._session_cache_time) < self._SESSION_CACHE_TTL:
            return self._session_cache
        return None

    def _set_cached_status(self, result: dict) -> None:
        import time

        self._session_cache = result
        self._session_cache_time = time.monotonic()

    def invalidate_cache(self) -> None:
        self._session_cache = None
        self._session_cache_time = 0.0
        self._cookiejar_cache = None
        self._cookiejar_cache_time = 0.0
        self._active_candidate = None
        self._active_profile_dir = ""

    def status(self) -> dict:
        cached = self._get_cached_status()
        if cached is not None:
            return cached

        try:
            result = self._find_working_browser()
        except BrowserSessionError as exc:
            status = {
                "dependencies_ready": "browser-cookie3" not in str(exc).lower(),
                "authenticated": False,
                "cookie_count": 0,
                "browser": self._active_candidate.name if self._active_candidate else None,
                "profileDir": self._active_profile_dir,
                "message": str(exc),
            }
            self._set_cached_status(status)
            return status

        status = {
            "dependencies_ready": True,
            "authenticated": True,
            "cookie_count": result["cookie_count"],
            "browser": result["browser"],
            "profileDir": result["profile_dir"],
            "message": f"Da xac nhan session Google tu profile rieng cua app tren {result['browser']}.",
        }
        self._set_cached_status(status)
        return status

    def has_session(self) -> bool:
        return self.status().get("authenticated", False)

    def export_netscape_cookies(self, file_path: str, domains: list[str] | None = None) -> str:
        import time

        cookiejar_cache_valid = (
            self._cookiejar_cache is not None
            and (time.monotonic() - self._cookiejar_cache_time) < self._SESSION_CACHE_TTL
        )
        if not cookiejar_cache_valid:
            self._find_working_browser()

        source_jar = self._cookiejar_cache
        if source_jar is None:
            raise BrowserSessionError("Khong xac dinh duoc profile trinh duyet de xuat cookie.")

        requested_domains = domains or [""]
        cookie_file = http.cookiejar.MozillaCookieJar(file_path)
        seen: set[tuple[str, str, str]] = set()

        for cookie in source_jar:
            if requested_domains != [""]:
                if not any(cookie.domain.lstrip(".").endswith(d.lstrip(".")) for d in requested_domains):
                    continue
            key = (cookie.domain, cookie.path, cookie.name)
            if key in seen:
                continue
            seen.add(key)
            cookie_file.set_cookie(cookie)

        if not seen:
            for cookie in source_jar:
                key = (cookie.domain, cookie.path, cookie.name)
                if key in seen:
                    continue
                seen.add(key)
                cookie_file.set_cookie(cookie)

        cookie_file.save(ignore_discard=True, ignore_expires=True)
        return file_path

    def extract_platform_cookies(self, platform_id: str) -> str:
        from downloader_app.jobs import COOKIE_DOMAIN_HINTS

        self.status()
        source_jar = self._cookiejar_cache
        if source_jar is None:
            return ""

        domains = COOKIE_DOMAIN_HINTS.get(platform_id, [f"{platform_id}.com"])
        tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        tmp.close()
        try:
            target = http.cookiejar.MozillaCookieJar(tmp.name)
            seen: set[tuple[str, str, str]] = set()
            found_count = 0
            for cookie in source_jar:
                if any(cookie.domain.lstrip(".").endswith(d.lstrip(".")) for d in domains):
                    key = (cookie.domain, cookie.path, cookie.name)
                    if key in seen:
                        continue
                    seen.add(key)
                    target.set_cookie(cookie)
                    found_count += 1
            if found_count <= 0:
                return ""
            target.save(ignore_discard=True, ignore_expires=True)
            return Path(tmp.name).read_text(encoding="utf-8", errors="replace")
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    def fetch_text(self, url: str) -> str:
        import time

        cache_valid = (
            self._cookiejar_cache is not None
            and (time.monotonic() - self._cookiejar_cache_time) < self._SESSION_CACHE_TTL
        )
        if not cache_valid:
            self._find_working_browser()

        cookiejar = self._cookiejar_cache
        if cookiejar is None:
            raise BrowserSessionError("Khong co cookie Google trong profile rieng cua app.")

        opener = build_opener(HTTPCookieProcessor(cookiejar))
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0 Safari/537.36"
                )
            },
        )
        try:
            with opener.open(request, timeout=20) as response:
                final_url = response.geturl()
                payload = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise self._http_error_for_candidate(
                self._active_candidate.name if self._active_candidate else "browser",
                exc,
            ) from exc
        except Exception as exc:
            raise BrowserSessionError(str(exc)) from exc

        if self._is_logged_out_response(final_url, payload):
            self.invalidate_cache()
            raise BrowserSessionError(
                "Google session trong profile rieng cua app chua hop le. "
                "Hay bam Dang nhap Google roi thu lai."
            )

        return payload

    def get_domain_cookies(self, domains: list[str]) -> tuple[str | None, list[http.cookiejar.Cookie]]:
        import time

        normalized_domains = [domain.lstrip(".").lower() for domain in domains if domain]
        if not normalized_domains:
            return None, []

        cache_valid = (
            self._cookiejar_cache is not None
            and self._active_candidate is not None
            and (time.monotonic() - self._cookiejar_cache_time) < self._SESSION_CACHE_TTL
        )
        if not cache_valid:
            self._find_working_browser()

        if self._cookiejar_cache is None or self._active_candidate is None:
            return None, []

        matched = [
            cookie
            for cookie in self._cookiejar_cache
            if any(cookie.domain.lstrip(".").lower().endswith(domain) for domain in normalized_domains)
        ]
        return self._active_candidate.name, matched

    def open_login(self, target_url: str = GOOGLE_LOGIN_URL) -> dict:
        try:
            payload = launch_browser_with_profile(feature="downloader", target_url=target_url)
        except Exception as exc:
            raise BrowserSessionError(str(exc)) from exc
        self.invalidate_cache()
        message = (
            f"Da mo Google bang profile rieng cua app tren {payload.get('browser', 'browser')}. "
            "Dang nhap xong, dong cua so vua mo roi quay lai app bam Lam moi phien."
        )
        return {**payload, "message": message}

    def _find_working_browser(self) -> dict:
        import time

        if (
            self._cookiejar_cache is not None
            and self._active_candidate is not None
            and (time.monotonic() - self._cookiejar_cache_time) < self._SESSION_CACHE_TTL
        ):
            return {
                "browser": self._active_candidate.name,
                "cookie_count": len(list(self._cookiejar_cache)),
                "profile_dir": self._active_profile_dir,
            }

        resolved = resolve_feature_browser_profile("downloader")
        candidate = BrowserCandidate(
            name=str(resolved["browserName"]),
            loader_name=self._loader_name_for_browser(str(resolved["browserName"])),
        )
        cookiejar = self._load_manual_cookiejar(
            candidate,
            profile_dir=Path(str(resolved["profileDir"])),
            user_data_dir=Path(str(resolved["userDataDir"])),
            domain_name="",
        )

        google_cookie_count = sum(1 for cookie in cookiejar if "google.com" in cookie.domain)
        self._active_candidate = candidate
        self._active_profile_dir = str(resolved["profileDir"])
        self._cookiejar_cache = cookiejar
        self._cookiejar_cache_time = time.monotonic()

        if google_cookie_count <= 0:
            raise BrowserSessionError(
                f"Chua tim thay Google session hop le trong profile rieng cua app tren {candidate.name}. "
                "Hay mo Google Sheets trong cua so Dang nhap cua app roi bam Lam moi phien."
            )

        return {
            "browser": candidate.name,
            "cookie_count": len(list(cookiejar)),
            "profile_dir": str(resolved["profileDir"]),
        }

    def _load_manual_cookiejar(
        self,
        candidate: BrowserCandidate,
        *,
        profile_dir: Path,
        user_data_dir: Path,
        domain_name: str,
    ):
        try:
            import browser_cookie3
        except ImportError as exc:
            raise BrowserSessionError(
                "Thieu thu vien browser-cookie3. Hay chay pip install -r requirements.txt."
            ) from exc

        cookie_paths = [
            profile_dir / "Network" / "Cookies",
            profile_dir / "Cookies",
        ]
        cookie_path = next((path for path in cookie_paths if path.exists()), None)
        if cookie_path is None:
            return http.cookiejar.CookieJar()

        key_file = user_data_dir / "Local State"
        if not key_file.exists():
            return http.cookiejar.CookieJar()

        try:
            if candidate.loader_name == "coccoc":
                class CocCoc(browser_cookie3.ChromiumBased):
                    def __init__(self, c_file, k_file, d_name):
                        super().__init__(
                            browser="CocCoc",
                            cookie_file=c_file,
                            domain_name=d_name,
                            key_file=k_file,
                            os_crypt_name="coccoc",
                            osx_key_service="CocCoc Safe Storage",
                            osx_key_user="CocCoc",
                        )

                return CocCoc(
                    c_file=str(cookie_path),
                    k_file=str(key_file),
                    d_name=domain_name,
                ).load()

            loader = getattr(browser_cookie3, candidate.loader_name, None)
            if loader is None:
                raise BrowserSessionError(f"Khong ho tro loader cho {candidate.name}.")
            return loader(
                cookie_file=str(cookie_path),
                key_file=str(key_file),
                domain_name=domain_name,
            )
        except Exception as exc:
            raise BrowserSessionError(
                f"Khong doc duoc cookie tu profile rieng cua app tren {candidate.name}: {exc}"
            ) from exc

    def _loader_name_for_browser(self, browser_name: str) -> str:
        normalized = browser_name.strip().lower()
        mapping = {
            "coccoc": "coccoc",
            "chrome": "chrome",
            "edge": "edge",
        }
        if normalized in mapping:
            return mapping[normalized]
        raise BrowserSessionError(f"Khong ho tro browser `{browser_name}`.")

    def _is_logged_out_response(self, final_url: str, payload: str) -> bool:
        if "accounts.google.com" in final_url or "ServiceLogin" in final_url:
            return True

        sign_in_markers = [
            "<title>Sign in",
            "Google Accounts",
            "identifierId",
        ]
        return any(marker in payload for marker in sign_in_markers)

    def _http_error_for_candidate(self, browser_name: str, error: HTTPError) -> BrowserSessionError:
        if error.code == 404:
            return BrowserSessionError(
                f"Google tra ve 404 khi truy cap sheet bang {browser_name}. "
                "Thuong nghia la link sheet sai hoac tai khoan trong profile nay khong thay sheet do."
            )

        if error.code == 403:
            return BrowserSessionError(
                f"Google tra ve 403 khi truy cap sheet bang {browser_name}. "
                "Tai khoan trong profile nay chua du quyen doc sheet."
            )

        return BrowserSessionError(
            f"Google request that bai trong {browser_name} voi HTTP {error.code}: {error.reason}"
        )


browser_session = BrowserSessionManager()
