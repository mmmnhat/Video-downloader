from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from downloader_app.browser_session import browser_session


GEMINI_DEFAULT_URL = "https://gemini.google.com/app"
GEMINI_LOGIN_URL = "https://gemini.google.com/app"
GEMINI_AUTH_DOMAINS = ("gemini.google.com", "google.com", "accounts.google.com")

PROFILE_ROOT_ITEMS = ("Local State",)
PROFILE_ITEMS = (
    "Cookies",
    "Local Storage",
    "Session Storage",
    "Preferences",
    "Secure Preferences",
    "Network Persistent State",
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
        candidates.extend(
            [
                GeminiBrowserCandidate(
                    name="CocCoc",
                    app_path=Path("/Applications/CocCoc.app"),
                    executable_path=Path("/Applications/CocCoc.app/Contents/MacOS/CocCoc"),
                    user_data_dir=Path.home() / "Library/Application Support/CocCoc/Browser",
                ),
                GeminiBrowserCandidate(
                    name="Chrome",
                    app_path=Path("/Applications/Google Chrome.app"),
                    executable_path=Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                    user_data_dir=Path.home() / "Library/Application Support/Google/Chrome",
                ),
                GeminiBrowserCandidate(
                    name="Edge",
                    app_path=Path("/Applications/Microsoft Edge.app"),
                    executable_path=Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                    user_data_dir=Path.home() / "Library/Application Support/Microsoft Edge",
                ),
            ]
        )

    return candidates


GEMINI_BROWSER_CANDIDATES = _build_candidates()


def _available_browser_candidates() -> list[GeminiBrowserCandidate]:
    return [
        candidate
        for candidate in GEMINI_BROWSER_CANDIDATES
        if candidate.app_path.exists() and candidate.executable_path.exists() and candidate.user_data_dir.exists()
    ]


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
        shutil.copy2(cookie_path, temp_copy)

        clauses = []
        params: list[str] = []
        for domain in domains:
            clauses.append("host_key = ? OR host_key LIKE ?")
            params.append(domain)
            params.append(f"%.{domain}")
        where = " OR ".join(f"({clause})" for clause in clauses)

        with sqlite3.connect(temp_copy) as connection:
            row = connection.execute(
                f"SELECT COUNT(*) FROM cookies WHERE {where}",
                tuple(params),
            ).fetchone()
    except Exception:
        return 0
    finally:
        if temp_copy is not None:
            temp_copy.unlink(missing_ok=True)

    return int(row[0]) if row else 0


def _choose_profile_dir(user_data_dir: Path, domains: tuple[str, ...]) -> Path | None:
    profile_dirs = _iter_profile_dirs(user_data_dir)
    if not profile_dirs:
        return None

    ranked: list[tuple[int, Path]] = []
    for profile_dir in profile_dirs:
        count = _cookie_count_for_domains(profile_dir / "Cookies", domains)
        ranked.append((count, profile_dir))

    ranked.sort(key=lambda item: item[0], reverse=True)
    if ranked and ranked[0][0] > 0:
        return ranked[0][1]

    for profile_dir in profile_dirs:
        if profile_dir.name == "Default":
            return profile_dir
    return profile_dirs[0]


def detect_gemini_browser_profile(domains: tuple[str, ...] = GEMINI_AUTH_DOMAINS) -> GeminiBrowserProfile:
    for candidate in _available_browser_candidates():
        profile_dir = _choose_profile_dir(candidate.user_data_dir, domains)
        if profile_dir is None:
            continue
        return GeminiBrowserProfile(
            name=candidate.name,
            app_path=candidate.app_path,
            executable_path=candidate.executable_path,
            user_data_dir=candidate.user_data_dir,
            profile_dir=profile_dir,
        )

    raise GeminiWebError("Khong tim thay CocCoc/Chrome/Edge co profile Gemini tren may nay.")


def _copy_profile_item(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def build_gemini_runtime_profile(profile: GeminiBrowserProfile, runtime_root: Path, runtime_id: str) -> Path:
    path = runtime_root / runtime_id
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)

    for item in PROFILE_ROOT_ITEMS:
        source = profile.user_data_dir / item
        if source.exists():
            _copy_profile_item(source, path / item)

    runtime_profile_dir = path / profile.profile_name
    runtime_profile_dir.mkdir(parents=True, exist_ok=True)
    for item in PROFILE_ITEMS:
        source = profile.profile_dir / item
        if source.exists():
            _copy_profile_item(source, runtime_profile_dir / item)

    return path


def open_gemini_login_window() -> dict:
    browser_name = "browser local"
    candidates = _available_browser_candidates()
    if candidates:
        browser_name = candidates[0].name
    try:
        opened_payload = browser_session.open_login(GEMINI_LOGIN_URL)
    except Exception as exc:  # noqa: BLE001
        raise GeminiWebError(f"Khong mo duoc cua so Gemini login: {exc}") from exc

    return {
        "opened": bool(opened_payload.get("opened", True)),
        "url": GEMINI_LOGIN_URL,
        "message": (
            f"Da mo Gemini tren {browser_name}. Dang nhap xong quay lai app de tiep tuc."
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

    cookie_path = profile.profile_dir / "Network" / "Cookies"
    cookie_count = _cookie_count_for_domains(cookie_path, GEMINI_AUTH_DOMAINS)
    if cookie_count > 0:
        return GeminiSessionStatus(
            dependencies_ready=True,
            authenticated=True,
            browser=profile.name,
            profile_dir=str(profile.profile_dir),
            message=f"Đã kết nối qua phiên {profile.name}.",
        )
    if profile.name.lower() == "coccoc":
        return GeminiSessionStatus(
            dependencies_ready=True,
            authenticated=True,
            browser=profile.name,
            profile_dir=str(profile.profile_dir),
            message=(
                "Đã kết nối qua phiên CocCoc. "
                "Nếu gặp lỗi khi tạo ảnh, hãy mở Gemini trong CocCoc rồi bấm Làm mới phiên."
            ),
        )
    return GeminiSessionStatus(
        dependencies_ready=True,
        authenticated=False,
        browser=profile.name,
        profile_dir=str(profile.profile_dir),
        message=f"Chưa tìm thấy phiên Gemini trong {profile.name}. Hãy đăng nhập Gemini rồi bấm Làm mới phiên.",
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

    This adapter intentionally treats preview capture as source-of-truth and then
    normalizes it to a local file before handing control back to the pipeline.
    """

    def __init__(
        self,
        *,
        runtime_root: Path,
        headless: bool = False,
        base_url: str = GEMINI_DEFAULT_URL,
        response_timeout_ms: int = 120_000,
        debug_selector: bool = False,
        debug_root: Path | None = None,
    ) -> None:
        self._runtime_root = runtime_root
        self._headless = headless
        self._base_url = base_url
        self._response_timeout_ms = max(20_000, int(response_timeout_ms))
        self._debug_selector = bool(debug_selector)
        self._debug_root = Path(debug_root) if debug_root is not None else runtime_root / "_selector_debug"

    def generate(
        self,
        *,
        prompt: str,
        input_image_path: Path,
        preview_path: Path,
        normalized_path: Path,
        context: dict,
    ):
        if not input_image_path.exists():
            raise GeminiWebError(f"Khong tim thay input image: {input_image_path}")

        try:
            from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise GeminiWebError(
                "Chua cai Playwright. Hay chay `./.venv/bin/pip install -r requirements.txt` "
                "va `./.venv/bin/python -m playwright install chromium`."
            ) from exc

        profile = detect_gemini_browser_profile()
        runtime_id = f"gemini-{uuid.uuid4().hex[:10]}"
        runtime_profile = build_gemini_runtime_profile(profile, self._runtime_root, runtime_id)
        debug_run_dir = self._prepare_debug_run(context) if self._debug_selector else None

        playwright = None
        browser_context = None
        page = None
        stage = "init"
        baseline_keys: set[str] = set()
        try:
            playwright = sync_playwright().start()
            stage = "launch_context"
            browser_context = playwright.chromium.launch_persistent_context(
                str(runtime_profile),
                headless=self._headless,
                accept_downloads=False,
                executable_path=str(profile.executable_path),
                args=[
                    f"--profile-directory={profile.profile_name}",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            page = browser_context.pages[0] if browser_context.pages else browser_context.new_page()
            page.set_default_timeout(20_000)

            stage = "workspace_ready"
            self._ensure_workspace_ready(page)
            self._dump_debug_state(
                page,
                debug_run_dir=debug_run_dir,
                stage="workspace_ready",
                context=context,
                prompt=prompt,
                baseline_keys=None,
            )
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
            self._capture_preview(page, candidate, preview_path)
            self._normalize_preview(preview_path, normalized_path)
            self._dump_debug_state(
                page,
                debug_run_dir=debug_run_dir,
                stage="normalized_output",
                context=context,
                prompt=prompt,
                baseline_keys=baseline_keys,
                selected_candidate=candidate,
            )

            return GeminiGenerationResult(
                preview_path=str(preview_path),
                normalized_path=str(normalized_path),
            )
        except Exception as exc:
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
            if browser_context is not None:
                try:
                    browser_context.close()
                except Exception:
                    pass
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    pass
            shutil.rmtree(runtime_profile, ignore_errors=True)

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

            screenshot_file = debug_run_dir / f"{stage}.jpg"
            html_file = debug_run_dir / f"{stage}.html"
            try:
                page.screenshot(path=str(screenshot_file), type="jpeg", quality=80, full_page=True)
                state["screenshotPath"] = str(screenshot_file)
            except Exception:
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

    def _ensure_workspace_ready(self, page) -> None:
        page.goto(self._base_url, wait_until="domcontentloaded", timeout=35_000)
        if _looks_like_login_page(page.url):
            raise GeminiWebAuthError(
                "Chua tim thay session Gemini trong browser local. Hay dang nhap Gemini roi thu lai."
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

    def _upload_input_image(self, page, input_image_path: Path) -> None:
        if self._set_file_via_existing_inputs(page, input_image_path):
            return

        composer = self._find_prompt_target(page)
        attach_buttons = self._find_attachment_buttons(page, composer)
        for button in attach_buttons:
            try:
                with page.expect_file_chooser(timeout=1_500) as chooser_info:
                    button.click()
                chooser = chooser_info.value
                chooser.set_files(str(input_image_path))
                page.wait_for_timeout(500)
                return
            except Exception:
                if self._set_file_via_existing_inputs(page, input_image_path):
                    return
                continue

        raise GeminiWebError("Khong tim thay file input de upload anh vao Gemini.")

    def _submit_prompt(self, page, prompt: str) -> None:
        clean_prompt = prompt.strip()
        if not clean_prompt:
            raise GeminiWebError("Prompt rong, khong the gui len Gemini.")

        target = self._find_prompt_target(page)
        if target is None:
            raise GeminiWebError("Khong tim thay o nhap prompt tren Gemini.")

        target.click()
        is_textarea = False
        try:
            tag_name = (target.evaluate("(el) => el.tagName") or "").lower()
            is_textarea = tag_name == "textarea"
        except Exception:
            is_textarea = False

        if is_textarea:
            target.fill(clean_prompt)
        else:
            modifier = "Meta+A" if sys.platform == "darwin" else "Control+A"
            page.keyboard.press(modifier)
            page.keyboard.press("Backspace")
            page.keyboard.insert_text(clean_prompt)

        sent = self._click_send_button(page, target)
        if not sent:
            page.keyboard.press("Enter")

    def _find_prompt_target(self, page):
        selectors = [
            "textarea",
            '[contenteditable="true"][role="textbox"]',
            '[contenteditable="true"]',
            '[role="textbox"][contenteditable="true"]',
            '[role="textbox"]',
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

    def _find_attachment_buttons(self, page, composer) -> list[object]:
        """
        Locates buttons used for attaching files/images.
        Uses both specific ARIA labels and proximity to the prompt composer.
        """
        targeted_selectors = [
            'button[aria-label*="upload" i]',
            'button[aria-label*="attach" i]',
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
                    if btn.is_visible():
                        candidates.append(btn)
            except Exception:
                continue
        
        if candidates:
            return candidates

        attach_tokens = ["upload", "attach", "image", "photo", "file", "tải", "anh", "ảnh", "hình", "đính", "tệp"]
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
                
                label = (btn.get_attribute("aria-label") or "").lower()
                text = (btn.inner_text() or "").lower()
                title = (btn.get_attribute("title") or "").lower()
                combined = f"{label} {text} {title}"
                
                if any(token in combined for token in send_tokens):
                    continue
                
                score = 0.0
                if any(token in combined for token in attach_tokens):
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

    def list_gems(self) -> list[dict]:
        """
        Navigates to the Gems view page and extracts available Gems.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return []

        profile = detect_gemini_browser_profile()
        runtime_id = f"list-gems-{uuid.uuid4().hex[:8]}"
        runtime_profile = build_gemini_runtime_profile(profile, self._runtime_root, runtime_id)

        playwright = None
        context = None
        try:
            playwright = sync_playwright().start()
            context = playwright.chromium.launch_persistent_context(
                str(runtime_profile),
                headless=True,
                executable_path=str(profile.executable_path),
                args=[f"--profile-directory={profile.profile_name}"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(30_000)
            
            # The exact URL provided by user
            page.goto("https://gemini.google.com/gems/view", wait_until="networkidle", timeout=25_000)
            
            # Wait for content to appear
            try:
                page.wait_for_selector('a[href*="/app/gems/"], a[href*="/gems/"]', timeout=8_000)
            except Exception:
                pass

            gems = page.evaluate("""() => {
                const results = [];
                // Find all links that point to a Gem app
                const links = Array.from(document.querySelectorAll('a[href*="/gems/"]'));
                for (const link of links) {
                    const href = link.href;
                    if (href.includes('/view') || href.includes('/list') || href.includes('/manage')) continue;
                    
                    // The Gem name is usually in a prominent text element inside the card/link
                    let name = (link.innerText || link.textContent || '').trim().split('\\n')[0];
                    
                    if (!name || name.length < 2) {
                        name = (link.getAttribute('title') || link.getAttribute('aria-label') || '').trim();
                    }
                    
                    if (href && name && name.length >= 2 && !results.some(g => g.url === href)) {
                        results.push({ name, url: href });
                    }
                }
                return results;
            }""")
            return gems
        except Exception as e:
            print(f"[DEBUG] Failed to list gems: {e}")
            return []
        finally:
            if context: context.close()
            if playwright: playwright.stop()
            shutil.rmtree(runtime_profile, ignore_errors=True)

    def _click_send_button(self, page, composer) -> bool:
        send_selectors = [
            'button[aria-label*="send" i]',
            'button[aria-label*="run" i]',
            '[role="button"][aria-label*="send" i]',
            'button[data-testid*="send" i]',
            'button[data-testid*="submit" i]',
        ]
        for selector in send_selectors:
            try:
                locator = page.locator(selector)
                count = locator.count()
                for index in reversed(range(min(count, 8))):
                    candidate = locator.nth(index)
                    if not candidate.is_visible() or candidate.is_disabled():
                        continue
                    candidate.click()
                    return True
            except Exception:
                continue

        send_tokens = [
            "send",
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

        best = None
        best_score = float("-inf")
        buttons = page.locator("button, [role='button']")
        try:
            count = buttons.count()
        except Exception:
            count = 0
        for index in range(min(count, 140)):
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
                    ]
                ).strip().lower()
                attach_hint = any(token in text_blob for token in attach_tokens)
                if attach_hint:
                    continue

                send_hint = any(token in text_blob for token in send_tokens)
                score = 0.0
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
                """() => {
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

    def _capture_preview(self, page, candidate: _PreviewCandidate, preview_path: Path) -> None:
        try:
            candidate.locator.screenshot(path=str(preview_path), type="jpeg", quality=92)
        except Exception:
            # Fallback: full page screenshot if element screenshot fails.
            page.screenshot(path=str(preview_path), type="jpeg", quality=85, full_page=False)

        if not preview_path.exists() or preview_path.stat().st_size == 0:
            raise GeminiWebError("Khong capture duoc preview image tu Gemini.")

    def _normalize_preview(self, preview_path: Path, normalized_path: Path) -> None:
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(preview_path, normalized_path)
        if normalized_path.stat().st_size == 0:
            raise GeminiWebError("Normalize image that bai: file rong.")

