from __future__ import annotations

import http.cookiejar
import webbrowser
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener


GOOGLE_LOGIN_URL = "https://docs.google.com/spreadsheets/u/0/"


class BrowserSessionError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserCandidate:
    name: str
    loader_name: str


class BrowserSessionManager:
    def __init__(self) -> None:
        self._candidates = [
            BrowserCandidate(name="CocCoc", loader_name="coccoc"),
            BrowserCandidate(name="Chrome", loader_name="chrome"),
            BrowserCandidate(name="Edge", loader_name="edge"),
            BrowserCandidate(name="Firefox", loader_name="firefox"),
            BrowserCandidate(name="Brave", loader_name="brave"),
            BrowserCandidate(name="Opera", loader_name="opera"),
            BrowserCandidate(name="Opera GX", loader_name="opera_gx"),
            BrowserCandidate(name="Vivaldi", loader_name="vivaldi"),
            BrowserCandidate(name="Chromium", loader_name="chromium"),
            BrowserCandidate(name="LibreWolf", loader_name="librewolf"),
            BrowserCandidate(name="Safari", loader_name="safari"),
        ]
        self._active_candidate: BrowserCandidate | None = None
        self._session_cache: dict | None = None
        self._session_cache_time: float = 0.0
        # Cached full cookiejar so export and has_session reuse without re-scanning
        self._cookiejar_cache: http.cookiejar.CookieJar | None = None
        self._cookiejar_cache_time: float = 0.0

    _SESSION_CACHE_TTL = 60  # seconds – applies to both status and cookiejar cache

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
        """Clear cached session so the next status() call re-scans browsers."""
        self._session_cache = None
        self._session_cache_time = 0.0
        self._cookiejar_cache = None
        self._cookiejar_cache_time = 0.0

    def status(self) -> dict:
        cached = self._get_cached_status()
        if cached is not None:
            return cached

        try:
            import browser_cookie3
            dependencies_ready = True
        except ImportError:
            dependencies_ready = False

        status = {
            "dependencies_ready": dependencies_ready,
            "authenticated": False,
            "cookie_count": 0,
            "browser": None,
            "message": "",
        }

        if not dependencies_ready:
            status["message"] = "Thieu thu vien browser-cookie3. Hay chay pip3 install -r requirements.txt."
            self._set_cached_status(status)
            return status

        try:
            result = self._find_working_browser()
        except BrowserSessionError as exc:
            if self._active_candidate is not None:
                status["browser"] = self._active_candidate.name
            elif self._candidates:
                status["browser"] = self._candidates[0].name
            message = str(exc)
            browser_name = status.get("browser")
            if (
                browser_name
                and str(browser_name).lower() == "coccoc"
                and "Chua tim thay Google session hop le trong browser." in message
            ):
                status["authenticated"] = True
                status["cookie_count"] = 0
                status["message"] = (
                    "Da tim thay profile CocCoc. "
                    "Neu gap loi khi doc Google Sheets private, hay mo Google Sheets trong CocCoc "
                    "roi bam Lam moi phien."
                )
                self._set_cached_status(status)
                return status
            if (
                browser_name
                and "Chua tim thay Google session hop le trong browser." in message
            ):
                message = (
                    f"Chua tim thay Google session hop le trong {browser_name}. "
                    f"Hay mo Google Sheets trong {browser_name} co quyen xem roi bam Lam moi phien."
                )
            status["message"] = message
            self._set_cached_status(status)
            return status

        status["dependencies_ready"] = True
        status["authenticated"] = True
        status["cookie_count"] = result["cookie_count"]
        status["browser"] = result["browser"]
        status["message"] = f"Da xac nhan session Google tu {result['browser']}."
        self._set_cached_status(status)
        return status

    def has_session(self) -> bool:
        return self.status().get("authenticated", False)

    def export_netscape_cookies(self, file_path: str, domains: list[str] | None = None) -> str:
        import time
        # Use the cached cookiejar if available — avoids re-scanning all profiles per download item
        cookiejar_cache_valid = (
            self._cookiejar_cache is not None
            and (time.monotonic() - self._cookiejar_cache_time) < self._SESSION_CACHE_TTL
        )
        if not cookiejar_cache_valid:
            # Force a fresh scan and populate the cache
            self._find_working_browser()

        source_jar = self._cookiejar_cache
        if source_jar is None:
            raise BrowserSessionError("Khong xac dinh duoc browser dang active de xuat cookie.")

        requested_domains = domains or [""]
        cookie_file = http.cookiejar.MozillaCookieJar(file_path)
        seen: set[tuple[str, str, str]] = set()

        for cookie in source_jar:
            # Filter by domain if domains are specified
            if requested_domains != [""]:
                if not any(
                    cookie.domain.lstrip(".").endswith(d.lstrip("."))
                    for d in requested_domains
                ):
                    continue
            key = (cookie.domain, cookie.path, cookie.name)
            if key in seen:
                continue
            seen.add(key)
            cookie_file.set_cookie(cookie)

        if not seen:
            # Fall back to full cookiejar without domain filtering
            for cookie in source_jar:
                key = (cookie.domain, cookie.path, cookie.name)
                if key not in seen:
                    seen.add(key)
                    cookie_file.set_cookie(cookie)

        cookie_file.save(ignore_discard=True, ignore_expires=True)
        return file_path

    def extract_platform_cookies(self, platform_id: str) -> str:
        """Find cookies for a specific platform in the browser and return Netscape string."""
        import time
        import io
        from downloader_app.jobs import COOKIE_DOMAIN_HINTS

        # Refresh candidate/cookiejar if needed
        self.status()

        source_jar = self._cookiejar_cache
        if source_jar is None:
            # Try once more to find a working browser if cache is empty
            try:
                self._find_working_browser()
                source_jar = self._cookiejar_cache
            except Exception:
                return ""

        if source_jar is None:
            return ""

        domains = COOKIE_DOMAIN_HINTS.get(platform_id, [f"{platform_id}.com"])
        
        # We need a Netscape format string. 
        # MozillaCookieJar expects a file path to save to. 
        # We'll use a temporary file then delete it.
        import tempfile
        from pathlib import Path

        tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        tmp.close()
        try:
            target = http.cookiejar.MozillaCookieJar(tmp.name)
            seen: set[tuple[str, str, str]] = set()
            found_count = 0

            for cookie in source_jar:
                if any(cookie.domain.lstrip(".").endswith(d.lstrip(".")) for d in domains):
                    key = (cookie.domain, cookie.path, cookie.name)
                    if key not in seen:
                        seen.add(key)
                        target.set_cookie(cookie)
                        found_count += 1

            if found_count > 0:
                target.save(ignore_discard=True, ignore_expires=True)
                return Path(tmp.name).read_text(encoding="utf-8", errors="replace")
            return ""
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    def fetch_text(self, url: str) -> str:
        import time

        # Fast path: use cached cookiejar if still fresh
        cache_valid = (
            self._cookiejar_cache is not None
            and (time.monotonic() - self._cookiejar_cache_time) < self._SESSION_CACHE_TTL
        )
        if cache_valid and self._cookiejar_cache is not None:
            opener = build_opener(HTTPCookieProcessor(self._cookiejar_cache))
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
                if not self._is_logged_out_response(final_url, payload):
                    return payload
                # Session became invalid — invalidate cache and fall through to full scan
                self.invalidate_cache()
            except HTTPError:
                pass
            except Exception:
                pass

        # Slow path: scan all browser candidates
        last_error: Exception | None = None
        primary_error: Exception | None = None

        for candidate in self._ordered_candidates():
            try:
                cookiejar = self._load_cookiejar(candidate)
            except BrowserSessionError as exc:
                last_error = exc
                if candidate == self._active_candidate and primary_error is None:
                    primary_error = exc
                continue

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
                last_error = self._http_error_for_candidate(candidate.name, exc)
                if candidate == self._active_candidate and primary_error is None:
                    primary_error = last_error
                continue
            except Exception as exc:
                last_error = exc
                if candidate == self._active_candidate and primary_error is None:
                    primary_error = exc
                continue

            if self._is_logged_out_response(final_url, payload):
                last_error = BrowserSessionError(
                    f"Google session trong {candidate.name} chua hop le."
                )
                if candidate == self._active_candidate and primary_error is None:
                    primary_error = last_error
                continue

            self._active_candidate = candidate
            # Update cookiejar cache with newly found working cookies
            self._cookiejar_cache = cookiejar
            self._cookiejar_cache_time = time.monotonic()
            return payload

        if isinstance(primary_error, BrowserSessionError):
            raise primary_error

        if isinstance(last_error, BrowserSessionError):
            raise last_error

        raise BrowserSessionError(
            "Khong the dung browser session hien tai de doc Google Sheets private. "
            "Hay mo chinh sheet trong browser dang dung va dam bao tai khoan do co quyen xem."
        ) from last_error

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
        if cache_valid and self._cookiejar_cache is not None:
            matched = [
                cookie
                for cookie in self._cookiejar_cache
                if any(cookie.domain.lstrip(".").lower().endswith(domain) for domain in normalized_domains)
            ]
            if matched:
                return self._active_candidate.name, matched

        for candidate in self._ordered_candidates():
            try:
                cookiejar = self._load_cookiejar(candidate, domain_name="")
            except BrowserSessionError:
                continue

            matched = [
                cookie
                for cookie in cookiejar
                if any(cookie.domain.lstrip(".").lower().endswith(domain) for domain in normalized_domains)
            ]
            if not matched:
                continue

            self._active_candidate = candidate
            self._cookiejar_cache = cookiejar
            self._cookiejar_cache_time = time.monotonic()
            return candidate.name, matched

        return None, []

    def open_login(self, target_url: str = GOOGLE_LOGIN_URL) -> dict:
        opened = webbrowser.open(target_url, new=2)
        return {"opened": bool(opened), "url": target_url}

    def _find_working_browser(self) -> dict:
        import time
        try:
            import browser_cookie3
        except ImportError as exc:
            raise BrowserSessionError(
                "Thieu thu vien browser-cookie3. Hay chay pip3 install -r requirements.txt."
            ) from exc

        # Return cached cookiejar if still fresh
        if (
            self._cookiejar_cache is not None
            and self._active_candidate is not None
            and (time.monotonic() - self._cookiejar_cache_time) < self._SESSION_CACHE_TTL
        ):
            return {
                "browser": self._active_candidate.name,
                "cookie_count": len(list(self._cookiejar_cache)),
            }

        last_error: Exception | None = None

        for candidate in self._candidates:
            try:
                # Load ALL cookies into the cache so we can export any domain later
                cookiejar = self._load_cookiejar(candidate, domain_name="")
            except BrowserSessionError as exc:
                last_error = exc
                continue

            # Verify this profile actually has Google cookies before selecting it
            google_cookie_count = sum(1 for c in cookiejar if "google.com" in c.domain)
            if google_cookie_count <= 0:
                continue

            self._active_candidate = candidate
            self._cookiejar_cache = cookiejar
            self._cookiejar_cache_time = time.monotonic()
            return {
                "browser": candidate.name,
                "cookie_count": len(list(cookiejar)),
            }

        raise BrowserSessionError(
            "Chua tim thay Google session hop le trong browser. "
            "Hay mo Google Sheets trong browser co quyen xem roi bam Refresh Session."
        ) from last_error

    def _load_cookiejar(self, candidate: BrowserCandidate, domain_name: str = "google.com"):
        try:
            import browser_cookie3
        except ImportError as exc:
            raise BrowserSessionError(
                "Thieu thu vien browser-cookie3. Hay chay pip3 install -r requirements.txt."
            ) from exc

        try:
            if candidate.loader_name == "coccoc":
                loader = self._coccoc_cookie_loader(browser_cookie3)
            else:
                loader = getattr(browser_cookie3, candidate.loader_name)
            return loader(domain_name=domain_name)
        except Exception as exc:
            raise BrowserSessionError(
                f"Khong doc duoc cookie tu {candidate.name}. "
                "Neu dung macOS, co the can cap quyen cho Terminal/Codex de doc browser profile."
            ) from exc

    def _coccoc_cookie_loader(self, browser_cookie3_module):
        import glob
        import os
        import sys
        import http.cookiejar

        def load_all_profiles(domain_name=""):
            combined_cj = http.cookiejar.CookieJar()
            base_dirs: list[str] = []
            local_app_data = os.getenv("LOCALAPPDATA")
            if local_app_data:
                base_dirs.append(os.path.join(local_app_data, "CocCoc", "Browser", "User Data"))
            if sys.platform == "darwin":
                base_dirs.append(os.path.expanduser("~/Library/Application Support/CocCoc/Browser"))
            elif sys.platform.startswith("linux"):
                base_dirs.append(os.path.expanduser("~/.config/CocCoc/Browser"))

            class CocCoc(browser_cookie3_module.ChromiumBased):
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

            for base_dir in base_dirs:
                key_file = os.path.join(base_dir, "Local State")
                if not os.path.exists(key_file):
                    continue

                patterns = [
                    os.path.join(base_dir, "Default", "Cookies"),
                    os.path.join(base_dir, "Default", "Network", "Cookies"),
                    os.path.join(base_dir, "Profile *", "Cookies"),
                    os.path.join(base_dir, "Profile *", "Network", "Cookies"),
                    os.path.join(base_dir, "Guest Profile", "Cookies"),
                    os.path.join(base_dir, "Guest Profile", "Network", "Cookies"),
                ]

                found_files = []
                for pat in patterns:
                    found_files.extend(glob.glob(pat))

                for cf in set(found_files):
                    if not os.path.isfile(cf):
                        continue
                    try:
                        extractor = CocCoc(c_file=cf, k_file=key_file, d_name=domain_name)
                        extracted_cj = extractor.load()
                        for cookie in extracted_cj:
                            combined_cj.set_cookie(cookie)
                    except Exception:
                        pass

            return combined_cj

        return load_all_profiles

    def _is_logged_out_response(self, final_url: str, payload: str) -> bool:
        if "accounts.google.com" in final_url or "ServiceLogin" in final_url:
            return True

        sign_in_markers = [
            "<title>Sign in",
            "Google Accounts",
            "identifierId",
        ]
        return any(marker in payload for marker in sign_in_markers)

    def _ordered_candidates(self) -> list[BrowserCandidate]:
        if self._active_candidate is None:
            return list(self._candidates)

        return [self._active_candidate] + [
            candidate
            for candidate in self._candidates
            if candidate != self._active_candidate
        ]

    def _http_error_for_candidate(self, browser_name: str, error: HTTPError) -> BrowserSessionError:
        if error.code == 404:
            return BrowserSessionError(
                f"Google tra ve 404 khi truy cap sheet bang {browser_name}. "
                "Thuong dieu nay co nghia la link sheet dang dan bi sai, bi thieu ky tu, "
                "hoac tai khoan trong browser nay khong nhin thay sheet do. "
                "Hay copy lai full URL truc tiep tu thanh dia chi cua tab sheet dang mo."
            )

        if error.code == 403:
            return BrowserSessionError(
                f"Google tra ve 403 khi truy cap sheet bang {browser_name}. "
                "Tai khoan trong browser nay chua du quyen doc sheet."
            )

        return BrowserSessionError(
            f"Google request that bai trong {browser_name} voi HTTP {error.code}: {error.reason}"
        )


browser_session = BrowserSessionManager()
