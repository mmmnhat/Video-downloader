from __future__ import annotations

import http.cookiejar
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue

from downloader_app.browser_session import BrowserSessionError, browser_session
from downloader_app.platforms import detect_platform
from downloader_app.runtime import app_path, is_frozen, resolve_binary
from downloader_app.sheets import ClipRange, SheetScanResult, SheetUrlEntry, scan_sheet

SUBPROCESS_KWARGS = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)} if os.name == "nt" else {}

DEFAULT_OUTPUT_DIR = app_path("downloads")
STATE_FILE = app_path("app_state.json")
QUALITY_OPTIONS = {"auto", "1080", "720", "480", "360"}
COOKIE_DOMAIN_HINTS = {
    "youtube": ["youtube.com", "google.com", "youtu.be"],
    "facebook": ["facebook.com", "fb.watch"],
    "instagram": ["instagram.com"],
    "tiktok": ["tiktok.com"],
    "pinterest": ["pinterest.com", "pin.it"],
    "dumpert": ["dumpert.nl"],
    "x": ["x.com", "twitter.com"],
    "threads": ["threads.net", "instagram.com"],
    "reddit": ["reddit.com", "redd.it"],
}
FINAL_BATCH_STATUSES = {"completed", "completed_with_errors", "cancelled"}
MAX_EVENT_BACKLOG = 500
MAX_CONCURRENT_DOWNLOADS = 20
TIKTOK_APP_INFO_FALLBACK = "1234567890123456789/trill/40.2.5/2024002050/1180"
def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def sanitize_file_stem(value: str) -> str:
    stem = re.sub(r"[^\w.\-]+", "_", value.strip(), flags=re.ASCII)
    stem = stem.strip("._")
    return stem or "video"


@dataclass
class DownloadSettings:
    output_dir: str
    quality: str = "auto"
    concurrent_downloads: int = MAX_CONCURRENT_DOWNLOADS
    retry_count: int = 1
    use_browser_cookies: bool = True
    cookies_map: dict[str, str] = field(default_factory=dict)


@dataclass
class DownloadItem:
    id: str
    source_url: str
    platform: str
    domain: str
    status: str
    supported: bool
    sequence_label: str
    output_name: str
    sheet_row_number: int
    clip_ranges: tuple[ClipRange, ...] = ()
    attempt_count: int = 0
    output_path: str | None = None
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    @property
    def clip_range_label(self) -> str | None:
        if not self.clip_ranges:
            return None
        return "; ".join(clip_range.label for clip_range in self.clip_ranges)


@dataclass
class DownloadBatch:
    id: str
    sheet_url: str
    created_at: str
    status: str
    sheet_id: str
    gid: str | None
    sheet_access_mode: str
    discovered_url_count: int
    output_dir: str
    quality: str
    concurrent_downloads: int
    retry_count: int
    use_browser_cookies: bool
    has_manual_cookies: bool
    discover_progress: int = 0
    cookies_map: dict[str, str] = field(default_factory=dict)
    last_updated_at: str | None = None
    items: list[DownloadItem] = field(default_factory=list)


class BatchCancelledError(RuntimeError):
    pass


@dataclass(frozen=True)
class YtDlpAttempt:
    label: str
    use_cookie_file: bool = True
    extra_args: tuple[str, ...] = ()


class DownloadManager:
    def __init__(self) -> None:
        self._batches: dict[str, DownloadBatch] = {}
        self._lock = threading.RLock()
        self._event_condition = threading.Condition()
        self._event_sequence = 0
        self._event_backlog: list[dict] = []
        self._cancel_events: dict[str, threading.Event] = {}
        self._active_processes: dict[str, dict[str, subprocess.Popen[str]]] = {}
        self._batch_cookie_map: dict[str, dict[str, str]] = {}
        self._yt_dlp_cmd = self._resolve_yt_dlp_command()
        self._ffmpeg_cmd = resolve_binary("ffmpeg", env_var="VIDEO_DOWNLOADER_FFMPEG_BIN")
        self._ffprobe_cmd = resolve_binary("ffprobe", env_var="VIDEO_DOWNLOADER_FFPROBE_BIN")
        self._impersonate_target = self._resolve_impersonate_target()
        self._settings = DownloadSettings(output_dir=str(DEFAULT_OUTPUT_DIR))
        # Shared cookie file per batch (built once, reused by all worker threads)
        self._batch_shared_cookie: dict[str, str | None] = {}
        # Locks to prevent multiple threads from trampling on the same output file
        self._file_locks: dict[str, threading.RLock] = {}
        self._load_state()

    def list_batches(self) -> list[dict]:
        with self._lock:
            return [self._serialize_batch(batch) for batch in self._batches.values()]

    def list_batch_summaries(
        self,
        status: str | None = None,
        query: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        with self._lock:
            summaries = [
                self._serialize_batch_summary(batch)
                for batch in self._batches.values()
                if self._batch_matches_filters(batch, status=status, query=query)
            ]

        summaries.sort(key=lambda batch: batch["createdAt"], reverse=True)
        if limit is not None:
            summaries = summaries[:limit]
        return summaries

    def get_batch(self, batch_id: str) -> dict | None:
        with self._lock:
            batch = self._batches.get(batch_id)
            return None if batch is None else self._serialize_batch(batch)

    def get_batch_detail(self, batch_id: str) -> dict | None:
        with self._lock:
            batch = self._batches.get(batch_id)
            return None if batch is None else self._serialize_batch_detail(batch)

    def get_settings(self) -> dict:
        with self._lock:
            return asdict(self._settings)

    def update_settings(self, payload: dict) -> dict:
        with self._lock:
            self._settings = self._normalize_settings(payload, current=self._settings)
            self._persist_state_locked()
            self._record_event_locked("settings.updated", {})
            return asdict(self._settings)

    def get_active_batch_id(self) -> str | None:
        with self._lock:
            active = [
                batch
                for batch in self._batches.values()
                if batch.status in {"queued", "running", "cancelling"}
            ]
            if active:
                active.sort(
                    key=lambda batch: batch.last_updated_at or batch.created_at,
                    reverse=True,
                )
                return active[0].id

            if not self._batches:
                return None

            latest = max(
                self._batches.values(),
                key=lambda batch: batch.last_updated_at or batch.created_at,
            )
            return latest.id

    def wait_for_events(self, after_id: int, timeout: float = 15.0) -> list[dict]:
        deadline = time.time() + timeout
        with self._event_condition:
            while True:
                pending = [
                    event for event in self._event_backlog if int(event["id"]) > after_id
                ]
                if pending:
                    return pending

                remaining = deadline - time.time()
                if remaining <= 0:
                    return []
                self._event_condition.wait(timeout=remaining)

    def create_batch(self, sheet_url: str, settings_payload: dict | None = None) -> DownloadBatch:
        with self._lock:
            if settings_payload is not None:
                self._settings = self._normalize_settings(settings_payload, current=self._settings)
            settings = DownloadSettings(**asdict(self._settings))

        scan_result = scan_sheet(sheet_url)
        batch = self._build_batch(sheet_url, scan_result, settings)

        with self._lock:
            self._batches[batch.id] = batch
            self._cancel_events[batch.id] = threading.Event()
            self._active_processes[batch.id] = {}
            self._batch_cookie_map[batch.id] = settings.cookies_map
            self._persist_state_locked()
            self._record_event_locked("batch.created", {"batchId": batch.id})

        if self._batch_has_pending_items(batch):
            self._start_batch_worker(batch.id)
        return batch

    def cancel_batch(self, batch_id: str) -> dict:
        with self._lock:
            batch = self._require_batch(batch_id)
            if batch.status in FINAL_BATCH_STATUSES:
                return self._serialize_batch(batch)

            batch.status = "cancelling"
            batch.last_updated_at = utc_now()
            cancel_event = self._cancel_events.setdefault(batch_id, threading.Event())
            cancel_event.set()
            processes = list(self._active_processes.get(batch_id, {}).values())
            self._persist_state_locked()
            self._record_event_locked("batch.updated", {"batchId": batch_id})

        for process in processes:
            if process.poll() is None:
                process.terminate()

        return self.get_batch(batch_id) or {}

    def retry_failed(self, batch_id: str) -> dict:
        with self._lock:
            batch = self._require_batch(batch_id)
            if batch.status in {"running", "cancelling"}:
                raise ValueError("Batch dang chay. Hay stop truoc khi retry.")

            retriable = [
                item
                for item in batch.items
                if item.supported and item.status in {"failed", "cancelled"}
            ]
            if not retriable:
                raise ValueError("Khong co item failed/cancelled nao de retry.")

            settings = DownloadSettings(
                output_dir=batch.output_dir,
                quality=batch.quality,
                concurrent_downloads=batch.concurrent_downloads,
                retry_count=batch.retry_count,
                use_browser_cookies=batch.use_browser_cookies,
                cookies_map=self._batch_cookie_map.get(batch.id, {}),
            )
            batch.output_dir = settings.output_dir
            batch.quality = settings.quality
            batch.concurrent_downloads = settings.concurrent_downloads
            batch.retry_count = settings.retry_count
            batch.use_browser_cookies = settings.use_browser_cookies
            batch.has_manual_cookies = bool(settings.cookies_map)

            for item in retriable:
                item.status = "queued"
                item.attempt_count = 0
                item.output_path = None
                item.error = None
                item.started_at = None
                item.completed_at = None

            self._cancel_events[batch_id] = threading.Event()
            self._active_processes[batch_id] = {}
            batch.status = "queued" if self._batch_has_pending_items(batch) else "completed"
            batch.last_updated_at = utc_now()
            self._persist_state_locked()
            self._record_event_locked("batch.updated", {"batchId": batch_id})

        if self._batch_has_pending_items(batch):
            self._start_batch_worker(batch_id)
        return self.get_batch(batch_id) or {}

    def preview_sheet(self, sheet_url: str) -> dict:
        scan_result = scan_sheet(sheet_url)
        rows: list[dict] = []
        platform_counts: dict[str, int] = {}
        supported_count = 0
        clip_count = 0

        for entry in scan_result.entries:
            match = detect_platform(entry.url)
            platform_counts[match.name] = platform_counts.get(match.name, 0) + 1
            if match.supported:
                supported_count += 1
            clip_count += len(entry.clip_ranges)

            rows.append(
                {
                    "sequenceLabel": entry.sequence_label,
                    "rowNumber": entry.row_index + 1,
                    "platform": match.name,
                    "supported": match.supported,
                    "sourceUrl": entry.url,
                    "clipRange": None,
                }
            )
            for i, clip_range in enumerate(entry.clip_ranges, start=1):
                rows.append(
                    {
                        "sequenceLabel": f"{entry.sequence_label}.{i}",
                        "rowNumber": entry.row_index + 1,
                        "platform": match.name,
                        "supported": match.supported,
                        "sourceUrl": entry.url,
                        "clipRange": clip_range.label,
                    }
                )

        unsupported_count = len(rows) - supported_count
        warnings: list[str] = []
        if not rows:
            warnings.append("Sheet khong tim thay URL video nao de tai.")
        if unsupported_count > 0:
            warnings.append(
                f"Co {unsupported_count} link chua map vao platform ho tro."
            )
        if clip_count > 0:
            warnings.append(
                f"Co {clip_count} doan se duoc auto-cut theo cot Time/Thoi luong hoac time range trong dong."
            )

        return {
            "sheetId": scan_result.sheet_id,
            "gid": scan_result.gid,
            "accessMode": scan_result.access_mode,
            "urlCount": len(rows),
            "supportedCount": supported_count,
            "unsupportedCount": unsupported_count,
            "platformCounts": platform_counts,
            "clipCount": clip_count,
            "rows": rows,
            "warnings": warnings,
        }

    def _start_batch_worker(self, batch_id: str) -> None:
        worker = threading.Thread(
            target=self._process_batch,
            args=(batch_id,),
            daemon=True,
        )
        worker.start()

    def _build_batch(
        self,
        sheet_url: str,
        scan_result: SheetScanResult,
        settings: DownloadSettings,
    ) -> DownloadBatch:
        items: list[DownloadItem] = []
        used_names: dict[str, int] = {}

        for entry in scan_result.entries:
            match = detect_platform(entry.url)
            base_name = sanitize_file_stem(entry.sequence_label)
            suffix = used_names.get(base_name, 0) + 1
            used_names[base_name] = suffix
            output_name = base_name if suffix == 1 else f"{base_name}-{suffix}"

            items.append(
                DownloadItem(
                    id=str(uuid.uuid4()),
                    source_url=entry.url,
                    platform=match.name,
                    domain=match.domain,
                    status="queued" if match.supported else "unsupported",
                    supported=match.supported,
                    sequence_label=entry.sequence_label,
                    output_name=output_name,
                    sheet_row_number=entry.row_index + 1,
                    clip_ranges=entry.clip_ranges,
                )
            )

        return DownloadBatch(
            id=str(uuid.uuid4()),
            sheet_url=sheet_url,
            created_at=utc_now(),
            status="queued" if self._has_pending_supported_items(items) else "completed",
            sheet_id=scan_result.sheet_id,
            gid=scan_result.gid,
            sheet_access_mode=scan_result.access_mode,
            discovered_url_count=len(scan_result.entries),
            output_dir=settings.output_dir,
            cookies_map=settings.cookies_map,
            quality=settings.quality,
            concurrent_downloads=settings.concurrent_downloads,
            retry_count=settings.retry_count,
            use_browser_cookies=settings.use_browser_cookies,
            has_manual_cookies=bool(settings.cookies_map),
            last_updated_at=utc_now(),
            items=items,
        )

    def _batch_has_pending_items(self, batch: DownloadBatch) -> bool:
        return self._has_pending_supported_items(batch.items)

    def _has_pending_supported_items(self, items: list[DownloadItem]) -> bool:
        return any(item.supported and item.status == "queued" for item in items)

    def _serialize_batch(self, batch: DownloadBatch) -> dict:
        data = asdict(batch)
        items = data["items"]
        data["stats"] = {
            "queued": sum(1 for item in items if item["status"] == "queued"),
            "downloading": sum(1 for item in items if item["status"] == "downloading"),
            "completed": sum(1 for item in items if item["status"] == "completed"),
            "failed": sum(1 for item in items if item["status"] == "failed"),
            "cancelled": sum(1 for item in items if item["status"] == "cancelled"),
            "unsupported": sum(1 for item in items if item["status"] == "unsupported"),
            "supported_total": sum(1 for item in items if item["supported"]),
        }
        return data

    def _process_batch(self, batch_id: str) -> None:
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None:
                return
            batch.status = "running"
            batch.last_updated_at = utc_now()
            cancel_event = self._cancel_events.setdefault(batch_id, threading.Event())
            queue: Queue[str] = Queue()
            for item in batch.items:
                if item.supported and item.status == "queued":
                    queue.put(item.id)
            self._persist_state_locked()
            self._record_event_locked("batch.updated", {"batchId": batch_id})

        worker_count = max(1, batch.concurrent_downloads)
        workers: list[threading.Thread] = []

        # Build ONE shared cookie file for the entire batch — avoids 20x redundant
        # browser cookie reads when running 20 concurrent worker threads.
        shared_cookie_path: str | None = None
        with self._lock:
            batch_obj = self._batches.get(batch_id)
        if batch_obj is not None:
            shared_cookie_path = self._prepare_batch_cookie_file(batch_obj)
        self._batch_shared_cookie[batch_id] = shared_cookie_path

        def run_worker() -> None:
            while not cancel_event.is_set():
                try:
                    item_id = queue.get_nowait()
                except Empty:
                    return

                try:
                    self._process_item(batch_id, item_id, cancel_event)
                finally:
                    queue.task_done()

        for _ in range(worker_count):
            worker = threading.Thread(target=run_worker, daemon=True)
            workers.append(worker)
            worker.start()

        for worker in workers:
            worker.join()

        # Cleanup shared cookie file
        shared = self._batch_shared_cookie.pop(batch_id, None)
        if shared:
            Path(shared).unlink(missing_ok=True)

        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None:
                return

            if cancel_event.is_set():
                for item in batch.items:
                    if item.supported and item.status == "queued":
                        item.status = "cancelled"
                        item.error = "Batch stopped by user."
                        item.completed_at = utc_now()

            self._refresh_batch_status_locked(batch_id)
            self._persist_state_locked()
            self._record_event_locked("batch.updated", {"batchId": batch_id})

    def _process_item(
        self,
        batch_id: str,
        item_id: str,
        cancel_event: threading.Event,
    ) -> None:
        with self._lock:
            batch = self._require_batch(batch_id)
            item = self._require_item(batch, item_id)
            started_at = item.started_at or utc_now()
            retry_count = batch.retry_count

        for attempt in range(1, retry_count + 2):
            if cancel_event.is_set():
                self._mark_item_cancelled(batch_id, item_id)
                return

            retry_message = None
            if attempt > 1:
                retry_message = f"Retry {attempt - 1}/{retry_count}"

            self._update_item(
                batch_id,
                item_id,
                status="downloading",
                started_at=started_at,
                completed_at=None,
                attempt_count=attempt,
                error=retry_message,
            )

            try:
                output_path = self._download_item(batch_id, item_id, cancel_event)
            except BatchCancelledError:
                self._mark_item_cancelled(batch_id, item_id)
                return
            except Exception as exc:  # pragma: no cover - depends on runtime binaries/network
                if attempt <= retry_count and not cancel_event.is_set():
                    self._update_item(
                        batch_id,
                        item_id,
                        error=f"Attempt {attempt} failed, retrying...",
                    )
                    continue

                self._update_item(
                    batch_id,
                    item_id,
                    status="failed",
                    completed_at=utc_now(),
                    error=str(exc),
                )
                return

            self._update_item(
                batch_id,
                item_id,
                status="completed",
                completed_at=utc_now(),
                output_path=output_path,
                error=None,
            )
            return

    def _prepare_batch_cookie_file(self, batch: "DownloadBatch") -> str | None:
        """Build a single cookie file for the whole batch and return its path."""
        use_browser_cookies = batch.use_browser_cookies
        batch_cookie_map = self._batch_cookie_map.get(batch.id, {})
        
        if not use_browser_cookies and not batch_cookie_map:
            return None

        target_file = tempfile.NamedTemporaryFile(
            prefix="yt-dlp-batch-cookies-",
            suffix=".txt",
            delete=False,
        )
        target_file.close()

        merged = http.cookiejar.MozillaCookieJar(target_file.name)
        cookie_count = 0

        if use_browser_cookies and browser_session.has_session():
            browser_temp = tempfile.NamedTemporaryFile(
                prefix="browser-cookies-",
                suffix=".txt",
                delete=False,
            )
            browser_temp.close()
            try:
                browser_session.export_netscape_cookies(browser_temp.name, domains=None)
                cookie_count += self._merge_cookie_file(merged, browser_temp.name)
            except BrowserSessionError:
                pass
            finally:
                Path(browser_temp.name).unlink(missing_ok=True)

        for platform, cookies_text in batch_cookie_map.items():
            if not cookies_text.strip():
                continue
            manual_path, should_cleanup = self._materialize_manual_cookie_file(cookies_text)
            try:
                cookie_count += self._merge_cookie_file(merged, manual_path)
            finally:
                if should_cleanup:
                    Path(manual_path).unlink(missing_ok=True)

        if cookie_count <= 0:
            Path(target_file.name).unlink(missing_ok=True)
            return None

        merged.save(ignore_discard=True, ignore_expires=True)
        return target_file.name

    def _download_item(
        self,
        batch_id: str,
        item_id: str,
        cancel_event: threading.Event,
    ) -> str:
        with self._lock:
            batch = self._require_batch(batch_id)
            item = self._require_item(batch, item_id)
            target_dir = Path(batch.output_dir).expanduser()
            quality = batch.quality

        target_dir.mkdir(parents=True, exist_ok=True)
        
        expected_base_path = target_dir / f"{item.output_name}.mp4"
        file_key = str(expected_base_path).lower()
        
        with self._lock:
            if file_key not in self._file_locks:
                self._file_locks[file_key] = threading.RLock()
            file_lock = self._file_locks[file_key]

        with file_lock:
            # Determine if we can skip this download because it already exists
            should_skip = False
            
            if not item.clip_ranges:
                if expected_base_path.exists():
                    should_skip = True
            else:
                all_clips_exist = True
                for clip_index in range(1, len(item.clip_ranges) + 1):
                    clip_path = expected_base_path.with_name(f"{expected_base_path.stem}.{clip_index}.mp4")
                    if not clip_path.exists():
                        all_clips_exist = False
                        break
                if all_clips_exist:
                    should_skip = True

            if should_skip:
                print(f"[DEBUG] Skipping {item.id} ({item.output_name}) as output already exists.")
                return str(expected_base_path)

            output_template = str(target_dir / f"{item.output_name}.%(ext)s")
            # Reuse the shared cookie file built once at batch start
            cookie_file_path = self._batch_shared_cookie.get(batch_id)

            last_error = "yt-dlp failed"

            try:
                for attempt in self._yt_dlp_attempts_for(item):
                    if cancel_event.is_set():
                        raise BatchCancelledError("Batch stopped by user.")

                    attempt_url = item.source_url
                    if attempt.label == "dumpert_html_scraping_fallback":
                        direct_url = self._resolve_dumpert_direct_url(item.source_url)
                        if not direct_url:
                            last_error = "Could not scrape direct MP4 URL from Dumpert HTML."
                            continue
                        attempt_url = direct_url
                        print(f"[DEBUG] Dumpert scraper found direct URL: {attempt_url}", flush=True)

                    command = self._build_yt_dlp_command(
                        item=item,
                        attempt_url=attempt_url,
                        output_template=output_template,
                        cookie_file_path=cookie_file_path,
                        quality=quality,
                        use_cookie_file=attempt.use_cookie_file,
                        extra_args=attempt.extra_args,
                    )
                    returncode, stdout, stderr = self._run_yt_dlp_command(
                        batch_id=batch_id,
                        item_id=item_id,
                        command=command,
                    )

                    if cancel_event.is_set():
                        raise BatchCancelledError("Batch stopped by user.")

                    if returncode == 0:
                        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
                        final_output_path = lines[-1] if lines else str(target_dir / item.output_name)
                        final_output_path = self._ensure_h264_output(batch_id, item, final_output_path, cancel_event)
                        return self._auto_cut_file(batch_id, item, final_output_path, cancel_event)

                    last_error = (stderr or stdout or "yt-dlp failed").strip()

                    # If yt-dlp rejected our --impersonate flag, permanently disable
                    # impersonation for this session and retry the same attempt without it.
                    if (
                        self._impersonate_target
                        and "impersonate target" in last_error.lower()
                        and "not available" in last_error.lower()
                    ):
                        self._impersonate_target = None
                        command = self._build_yt_dlp_command(
                            item=item,
                            attempt_url=attempt_url,
                            output_template=output_template,
                            cookie_file_path=cookie_file_path,
                            quality=quality,
                            use_cookie_file=attempt.use_cookie_file,
                            extra_args=attempt.extra_args,
                        )
                        returncode, stdout, stderr = self._run_yt_dlp_command(
                            batch_id=batch_id,
                            item_id=item_id,
                            command=command,
                        )
                        if cancel_event.is_set():
                            raise BatchCancelledError("Batch stopped by user.")
                        if returncode == 0:
                            lines = [line.strip() for line in stdout.splitlines() if line.strip()]
                            final_output_path = lines[-1] if lines else str(target_dir / item.output_name)
                            final_output_path = self._ensure_h264_output(batch_id, item, final_output_path, cancel_event)
                            return self._auto_cut_file(batch_id, item, final_output_path, cancel_event)
                        last_error = (stderr or stdout or "yt-dlp failed").strip()

                    if not self._should_retry_yt_dlp_attempt(item, attempt.label, last_error):
                        break
            finally:
                pass

            raise RuntimeError(self._format_download_error(item, last_error))

    def _yt_dlp_attempts_for(self, item: DownloadItem) -> list[YtDlpAttempt]:
        attempts = [YtDlpAttempt(label="default")]
        if item.platform == "youtube":
            # First fallback: Use yt-dlp's native browser extraction which is sometimes better at decrypting YouTube's complex signature cookies
            # yt-dlp doesn't know 'coccoc' by name, but Coc Coc is Chromium-based. 
            # We can use the 'chrome' engine and point it to the Coc Coc User Data directory.
            coccoc_path = os.path.expandvars(r"%LOCALAPPDATA%\CocCoc\Browser\User Data")
            attempts.append(
                YtDlpAttempt(
                    label="youtube_native_cookie_fallback",
                    use_cookie_file=False,
                    extra_args=(
                        "--cookies-from-browser",
                        f"chrome:{coccoc_path}",
                    ),
                )
            )
            # Try progressively more compatible YouTube player clients
            for client in ("android", "tv_embedded", "mweb"):
                attempts.append(
                    YtDlpAttempt(
                        label=f"youtube_{client}_fallback",
                        extra_args=(
                            "--extractor-args",
                            f"youtube:player_client={client}",
                        ),
                    )
                )
            # Last resort: android client without cookies
            attempts.append(
                YtDlpAttempt(
                    label="youtube_android_no_cookie_fallback",
                    use_cookie_file=False,
                    extra_args=(
                        "--extractor-args",
                        "youtube:player_client=android",
                    ),
                )
            )
        if item.platform == "dumpert":
            # Fallback 1: add typical browser headers to pass CDN anti-leech check
            attempts.append(
                YtDlpAttempt(
                    label="dumpert_browser_fallback",
                    extra_args=(
                        "--user-agent",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                        "--add-header",
                        "Referer:https://www.dumpert.nl/",
                    ),
                )
            )
            # Fallback 2: mobile user agent for the mobile API
            attempts.append(
                YtDlpAttempt(
                    label="dumpert_mobile_fallback",
                    extra_args=(
                        "--user-agent",
                        "Dalvik/2.1.0 (Linux; U; Android 10; SM-G981B Build/QP1A.190711.020)",
                    ),
                )
            )
            # Fallback 3: directly scrape the Dumpert HTML for the raw mp4 file
            attempts.append(
                YtDlpAttempt(
                    label="dumpert_html_scraping_fallback",
                    extra_args=(),
                )
            )
        if item.platform == "tiktok":
            attempts.append(
                YtDlpAttempt(
                    label="tiktok_mobile_api_fallback",
                    extra_args=(
                        "--extractor-args",
                        f"tiktok:app_info={TIKTOK_APP_INFO_FALLBACK}",
                    ),
                )
            )
        return attempts

    def _build_yt_dlp_command(
        self,
        item: DownloadItem,
        attempt_url: str,
        output_template: str,
        cookie_file_path: str | None,
        quality: str,
        use_cookie_file: bool = True,
        extra_args: tuple[str, ...] = (),
    ) -> list[str]:
        command = [*self._yt_dlp_cmd]
        if self._impersonate_target:
            command.extend(["--impersonate", self._impersonate_target])
        # Tell yt-dlp where to find ffmpeg so it can merge separate video/audio streams
        if self._ffmpeg_cmd:
            command.extend(["--ffmpeg-location", str(Path(self._ffmpeg_cmd).parent)])
        if use_cookie_file and cookie_file_path:
            command.extend(["--cookies", cookie_file_path])
        command.extend(self._quality_args(quality))
        command.extend(self._platform_yt_dlp_args(item))
        command.extend(extra_args)
        command.extend(
            [
                "--no-playlist",
                "--force-overwrites",
                "--quiet",
                "--no-warnings",
                "--restrict-filenames",
                "--merge-output-format",
                "mp4",
                "--output-na-placeholder",
                "unknown",
                "--print",
                "after_move:filepath",
                "-o",
                output_template,
                str(attempt_url),
            ]
        )
        return command

    def _platform_yt_dlp_args(self, item: DownloadItem) -> list[str]:
        # Concurrent fragments speeds up downloads but too many can trigger rate limiting
        if item.platform == "youtube":
            # YouTube is sensitive to too many connections - keep lower
            return ["--concurrent-fragments", "2"]
        if item.platform == "dumpert":
            # Dumpert CDN may not support many concurrent range requests
            return []
        return ["--concurrent-fragments", "4"]

    def _run_yt_dlp_command(
        self,
        batch_id: str,
        item_id: str,
        command: list[str],
    ) -> tuple[int, str, str]:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **SUBPROCESS_KWARGS,
        )
        with self._lock:
            self._active_processes.setdefault(batch_id, {})[item_id] = process

        try:
            stdout, stderr = process.communicate()
        finally:
            with self._lock:
                self._active_processes.get(batch_id, {}).pop(item_id, None)

        if process.returncode != 0:
            print(f"[DEBUG yt-dlp] Failed for {item_id}\nSTDERR: {stderr}\nSTDOUT: {stdout}", flush=True)

        return process.returncode, stdout, stderr

    def _should_retry_yt_dlp_attempt(
        self,
        item: DownloadItem,
        attempt_label: str,
        raw_message: str,
    ) -> bool:
        lowered = raw_message.lower()

        if item.platform == "tiktok":
            if attempt_label == "default":
                return (
                    "403" in raw_message
                    or "unable to extract webpage video data" in lowered
                    or "unable to download webpage" in lowered
                )
            return False

        if item.platform == "dumpert":
            return attempt_label in ("default", "dumpert_browser_fallback", "dumpert_mobile_fallback")

        if item.platform != "youtube":
            return False

        # For YouTube: allow chaining through ALL client fallbacks.
        # Stop only if we hit the no-cookie final attempt, or a non-retriable error.
        non_retriable = (
            "video unavailable" in lowered
            or "private video" in lowered
            or "age-restricted" in lowered
            or "copyright" in lowered
        )
        
        youtube_chaining_labels = {
            "default",
            "youtube_native_cookie_fallback",
            "youtube_android_fallback",
            "youtube_tv_embedded_fallback",
            "youtube_mweb_fallback",
        }

        if non_retriable:
            if attempt_label == "youtube_android_no_cookie_fallback":
                return False
            # If the error is auth-related, we MUST continue the chain 
            # to test manual cookies and mobile endpoints.
            if "private video" in lowered or "age-restricted" in lowered or "video unavailable" in lowered:
                return attempt_label in youtube_chaining_labels
            return False

        # Allow chaining for other general errors too
        return attempt_label in youtube_chaining_labels

    def _resolve_dumpert_direct_url(self, source_url: str) -> str | None:
        import urllib.request
        import re

        if "?selectedId=" in source_url:
            video_id = source_url.split("?selectedId=")[-1]
            target_url = f"https://www.dumpert.nl/item/{video_id}"
        else:
            target_url = source_url

        try:
            req = urllib.request.Request(
                target_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                }
            )
            html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
        except Exception as exc:
            print(f"[DEBUG] Dumpert HTML fallback fetch failed: {exc}", flush=True)
            return None

        # Fix JSON escaping if present
        html = html.replace('\\/', '/')
        # Often Dumpert JS contains direct video urls (.mp4 or .m3u8)
        matches = re.finditer(r'https?://[^\s\"\'\>\\]+?\.(?:mp4|m3u8)(?:\?[^\s\"\'\>\\]+)?', html)
        for match in matches:
            url = match.group(0)
            if "dumpert.nl" in url:
                return url
        return None

    def _build_cookie_file(
        self,
        item: DownloadItem,
        use_browser_cookies: bool,
        manual_cookies_text: str,
    ) -> str | None:
        has_manual = bool(manual_cookies_text.strip())
        if not use_browser_cookies and not has_manual:
            return None

        domains = COOKIE_DOMAIN_HINTS.get(item.platform, [item.domain])
        target_file = tempfile.NamedTemporaryFile(
            prefix=f"yt-dlp-cookies-{item.platform}-",
            suffix=".txt",
            delete=False,
        )
        target_file.close()

        merged = http.cookiejar.MozillaCookieJar(target_file.name)
        cookie_count = 0

        browser_export: str | None = None
        if use_browser_cookies and browser_session.has_session():
            browser_temp = tempfile.NamedTemporaryFile(
                prefix="browser-cookies-",
                suffix=".txt",
                delete=False,
            )
            browser_temp.close()
            browser_export = browser_temp.name
            try:
                browser_session.export_netscape_cookies(browser_export, domains=domains)
                cookie_count += self._merge_cookie_file(merged, browser_export)
            except BrowserSessionError:
                pass
            finally:
                Path(browser_export).unlink(missing_ok=True)

        if has_manual:
            manual_path, should_cleanup = self._materialize_manual_cookie_file(manual_cookies_text)
            try:
                cookie_count += self._merge_cookie_file(merged, manual_path)
            finally:
                if should_cleanup:
                    Path(manual_path).unlink(missing_ok=True)

        if cookie_count <= 0:
            Path(target_file.name).unlink(missing_ok=True)
            return None

        merged.save(ignore_discard=True, ignore_expires=True)
        return target_file.name

    def _auto_cut_file(
        self,
        batch_id: str,
        item: DownloadItem,
        output_path: str,
        cancel_event: threading.Event,
    ) -> str:
        if not item.clip_ranges:
            return output_path

        source_path = Path(output_path)
        if not source_path.exists():
            return output_path

        created_paths: list[Path] = []
        for clip_index, clip_range in enumerate(item.clip_ranges, start=1):
            clipped_path = source_path.with_name(
                f"{source_path.stem}.{clip_index}{source_path.suffix}"
            )
            command = [
                self._require_ffmpeg(),
                "-y",
                "-ss",
                self._format_ffmpeg_timestamp(clip_range.start_seconds),
            ]
            if clip_range.end_seconds is not None:
                command.extend(
                    [
                        "-to",
                        self._format_ffmpeg_timestamp(clip_range.end_seconds),
                    ]
                )
            command.extend(
                [
                    "-i",
                    str(source_path),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a?",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "18",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                    str(clipped_path),
                ]
            )

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                **SUBPROCESS_KWARGS,
            )
            with self._lock:
                self._active_processes.setdefault(batch_id, {})[item.id] = process

            try:
                stdout, stderr = process.communicate()
            finally:
                with self._lock:
                    self._active_processes.get(batch_id, {}).pop(item.id, None)

            if cancel_event.is_set():
                clipped_path.unlink(missing_ok=True)
                for created_path in created_paths:
                    created_path.unlink(missing_ok=True)
                raise BatchCancelledError("Batch stopped by user.")

            if process.returncode != 0:
                clipped_path.unlink(missing_ok=True)
                for created_path in created_paths:
                    created_path.unlink(missing_ok=True)
                message = (stderr or stdout or "ffmpeg autocut failed").strip()
                raise RuntimeError(message.splitlines()[-1])

            created_paths.append(clipped_path)

        # Keep the original file. Return the original base path so that
        # `_explode_item_details` can correctly derive clip paths (e.g. 1.1.mp4, 1.2.mp4).
        return str(source_path)

    def _ensure_h264_output(
        self,
        batch_id: str,
        item: DownloadItem,
        output_path: str,
        cancel_event: threading.Event,
    ) -> str:
        source_path = Path(output_path)
        if not source_path.exists():
            return output_path

        if not self._output_requires_h264_transcode(source_path):
            return output_path

        normalized_path = source_path.with_name(f"{source_path.stem}.h264.mp4")
        command = [
            self._require_ffmpeg(),
            "-y",
            "-i",
            str(source_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(normalized_path),
        ]

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **SUBPROCESS_KWARGS,
        )
        with self._lock:
            self._active_processes.setdefault(batch_id, {})[item.id] = process

        try:
            stdout, stderr = process.communicate()
        finally:
            with self._lock:
                self._active_processes.get(batch_id, {}).pop(item.id, None)

        if cancel_event.is_set():
            normalized_path.unlink(missing_ok=True)
            raise BatchCancelledError("Batch stopped by user.")

        if process.returncode != 0:
            normalized_path.unlink(missing_ok=True)
            message = (stderr or stdout or "ffmpeg h264 convert failed").strip()
            raise RuntimeError(message.splitlines()[-1])

        source_path.unlink(missing_ok=True)
        normalized_path.replace(source_path.with_suffix(".mp4"))
        return str(source_path.with_suffix(".mp4"))

    def _output_requires_h264_transcode(self, source_path: Path) -> bool:
        if source_path.suffix.lower() != ".mp4":
            return True

        codec = self._probe_video_codec(source_path)
        if codec is None:
            # ffprobe unavailable — assume the .mp4 from yt-dlp is already
            # H264-compatible rather than triggering a transcode that fails.
            return False

        return codec != "h264"

    def _probe_video_codec(self, source_path: Path) -> str | None:
        if not self._ffprobe_cmd:
            return None

        process = subprocess.run(
            [
                self._ffprobe_cmd,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(source_path),
            ],
            capture_output=True,
            text=True,
            **SUBPROCESS_KWARGS,
        )
        if process.returncode != 0:
            return None

        codec = process.stdout.strip().lower()
        return codec or None

    def _materialize_manual_cookie_file(self, cookies_text: str) -> tuple[str, bool]:
        candidate = Path(cookies_text.strip()).expanduser()
        if candidate.exists():
            return str(candidate), False

        payload = cookies_text.strip()
        if not payload.startswith("# Netscape HTTP Cookie File"):
            payload = "# Netscape HTTP Cookie File\n" + payload

        temp_file = tempfile.NamedTemporaryFile(
            prefix="manual-cookies-",
            suffix=".txt",
            delete=False,
            mode="w",
            encoding="utf-8",
        )
        with temp_file:
            temp_file.write(payload)
            if not payload.endswith("\n"):
                temp_file.write("\n")
        return temp_file.name, True

    def _merge_cookie_file(self, merged: http.cookiejar.MozillaCookieJar, path: str) -> int:
        source = http.cookiejar.MozillaCookieJar(path)
        source.load(ignore_discard=True, ignore_expires=True)

        added = 0
        for cookie in source:
            merged.set_cookie(cookie)
            added += 1
        return added

    def _quality_args(self, quality: str) -> list[str]:
        if quality == "auto":
            return []

        target_height = int(quality)
        return [
            "-f",
            f"bestvideo*[height<={target_height}]+bestaudio/best[height<={target_height}]/best",
        ]

    def _format_ffmpeg_timestamp(self, total_seconds: int) -> str:
        minutes, seconds = divmod(max(0, total_seconds), 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _mark_item_cancelled(self, batch_id: str, item_id: str) -> None:
        self._update_item(
            batch_id,
            item_id,
            status="cancelled",
            completed_at=utc_now(),
            error="Batch stopped by user.",
        )

    def _update_item(self, batch_id: str, item_id: str, **changes: object) -> None:
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None:
                return
            for item in batch.items:
                if item.id != item_id:
                    continue
                for key, value in changes.items():
                    setattr(item, key, value)
                break
            batch.last_updated_at = utc_now()
            self._persist_state_locked()
            self._record_event_locked("batch.updated", {"batchId": batch_id, "itemId": item_id})

    def _refresh_batch_status_locked(self, batch_id: str) -> None:
        batch = self._batches.get(batch_id)
        if batch is None:
            return

        if batch.status == "cancelling" or self._cancel_events.get(batch_id, threading.Event()).is_set():
            batch.status = "cancelled"
            batch.last_updated_at = utc_now()
            return

        if any(item.status == "failed" for item in batch.items if item.supported):
            batch.status = "completed_with_errors"
            batch.last_updated_at = utc_now()
            return

        if any(item.status == "cancelled" for item in batch.items if item.supported):
            batch.status = "completed_with_errors"
            batch.last_updated_at = utc_now()
            return

        batch.status = "completed"
        batch.last_updated_at = utc_now()

    def _resolve_yt_dlp_command(self) -> list[str]:
        forced = os.environ.get("YT_DLP_BIN")
        if forced:
            return [forced]

        packaged = resolve_binary("yt-dlp", env_var="VIDEO_DOWNLOADER_YT_DLP_BIN")
        if packaged:
            return [packaged]

        if is_frozen():
            return [sys.executable, "--run-yt-dlp"]

        if importlib.util.find_spec("yt_dlp") is not None:
            return [sys.executable, "-m", "yt_dlp"]

        binary = shutil.which("yt-dlp")
        if binary:
            return [binary]

        raise RuntimeError(
            "Khong tim thay yt-dlp. Hay chay `python3 -m pip install --user yt-dlp` "
            "hoac cai standalone binary."
        )

    def _resolve_impersonate_target(self) -> str | None:
        forced = os.environ.get("YT_DLP_IMPERSONATE")
        if forced:
            normalized = forced.strip().lower()
            if normalized in {"0", "false", "off", "none", "disable", "disabled"}:
                return None
            return forced.strip()

        # Actually invoke yt-dlp with --impersonate chrome to confirm it works.
        # Importing curl_cffi alone is not sufficient — the yt-dlp binary raises
        # YoutubeDLError on startup if the impersonation backend is unavailable.
        try:
            result = subprocess.run(
                [*self._yt_dlp_cmd, "--impersonate", "chrome", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                **SUBPROCESS_KWARGS,
            )
            if result.returncode == 0:
                return "chrome"
        except Exception:
            pass

        return None

    def _require_ffmpeg(self) -> str:
        if self._ffmpeg_cmd:
            return self._ffmpeg_cmd

        raise RuntimeError(
            "Khong tim thay ffmpeg. Hay cai ffmpeg vao PATH hoac dat "
            "`ffmpeg(.exe)` trong thu muc `bin/` canh app."
        )

    def _format_download_error(self, item: DownloadItem, raw_message: str) -> str:
        compact = " ".join(part.strip() for part in raw_message.splitlines() if part.strip())
        lowered = compact.lower()

        # Strip full Python tracebacks — extract the last exception line instead.
        # e.g. "Traceback ... yt_dlp.utils.YoutubeDLError: message"
        if "traceback (most recent call last)" in lowered:
            lines = [ln.strip() for ln in raw_message.splitlines() if ln.strip()]
            for line in reversed(lines):
                if line and not line.startswith("File ") and "Traceback" not in line and "^^^" not in line:
                    compact = line
                    lowered = compact.lower()
                    break

        # Remove "ClassName: " prefix from exception messages.
        for prefix in ("YoutubeDLError: ", "ERROR: ", "Error: ", "error: "):
            if prefix in compact:
                compact = compact.split(prefix, 1)[-1].strip()
                lowered = compact.lower()
                break

        if "impersonate target" in lowered and "not available" in lowered:
            return (
                "Impersonation (curl-cffi) khong dung voi phien ban nay. "
                "App da tu dong tat impersonation va thu lai nhung van that bai. "
                "Hay gỡ curl-cffi (`pip uninstall curl-cffi`) roi thu lai."
            )

        if item.platform == "tiktok" and (
            "403" in compact
            or "unable to extract webpage video data" in lowered
            or "unable to download webpage" in lowered
        ):
            return (
                "TikTok da thay doi du lieu trang cho link nay. App da thu them "
                "fallback mobile API cua yt-dlp, nhung extractor hien tai van khong "
                "tach duoc video."
            )

        if item.platform == "youtube" and (
            "403" in compact
            or "downloaded file is empty" in lowered
            or "fragment not found" in lowered
            or "requested format is not available" in lowered
        ):
            return (
                "YouTube dang tu choi hoac an bot format cua link nay. App da thu them "
                "fallback Android client, co va khong co cookie browser, nhung mot so "
                "video van can PO token/GVS access nen yt-dlp co the that bai."
            )

        return compact

    def _normalize_settings(
        self,
        payload: dict,
        current: DownloadSettings | None = None,
    ) -> DownloadSettings:
        base = current or self._settings
        output_dir = str(payload.get("output_dir", base.output_dir)).strip() or str(DEFAULT_OUTPUT_DIR)
        quality = str(payload.get("quality", base.quality)).strip() or "auto"
        if quality not in QUALITY_OPTIONS:
            quality = "auto"

        concurrent_downloads = self._clamp_int(
            payload.get("concurrent_downloads", base.concurrent_downloads),
            default=base.concurrent_downloads,
            minimum=1,
            maximum=MAX_CONCURRENT_DOWNLOADS,
        )
        retry_count = self._clamp_int(
            payload.get("retry_count", base.retry_count),
            default=base.retry_count,
            minimum=0,
            maximum=10,
        )
        use_browser_cookies = bool(payload.get("use_browser_cookies", base.use_browser_cookies))
        
        cmap = payload.get("cookies_map")
        if cmap is None and "cookies_text" in payload:
            cmap = {"default": str(payload.get("cookies_text", ""))}
        elif cmap is None:
            cmap = base.cookies_map

        return DownloadSettings(
            output_dir=str(Path(output_dir).expanduser()),
            quality=quality,
            concurrent_downloads=concurrent_downloads,
            retry_count=retry_count,
            use_browser_cookies=use_browser_cookies,
            cookies_map=cmap,
        )

    def _clamp_int(self, value: object, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, parsed))

    def _persist_state_locked(self) -> None:
        state = {
            "settings": asdict(self._settings),
            "batches": [asdict(batch) for batch in self._batches.values()],
        }
        STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_state(self) -> None:
        if not STATE_FILE.exists():
            return

        try:
            payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return

        settings_data = payload.get("settings", {})
        self._settings = self._normalize_settings(settings_data, current=self._settings)
        # Bỏ qua việc load lại "batches" cũ để app luôn bắt đầu với list trống
        self._batches = {}


    def _mark_interrupted_items(self, batch: DownloadBatch) -> None:
        changed = False
        for item in batch.items:
            if item.status == "downloading":
                item.status = "failed"
                item.error = "App restarted while downloading item nay."
                item.completed_at = utc_now()
                changed = True
            elif item.status == "queued" and batch.status in {"running", "cancelling"}:
                item.status = "cancelled"
                item.error = "App restarted truoc khi item nay duoc xu ly."
                item.completed_at = utc_now()
                changed = True

        if batch.status in {"running", "cancelling"}:
            batch.status = "completed_with_errors" if changed else "cancelled"
        if changed or batch.last_updated_at is None:
            batch.last_updated_at = utc_now()

    def _deserialize_batch(self, payload: dict) -> DownloadBatch:
        items: list[DownloadItem] = []
        for index, item_payload in enumerate(payload.get("items", []), start=1):
            sequence_label = str(
                item_payload.get("sequence_label")
                or item_payload.get("output_name")
                or index
            )
            raw_clip_ranges = item_payload.get("clip_ranges") or []
            clip_ranges: list[ClipRange] = []
            for raw_clip_range in raw_clip_ranges:
                label = raw_clip_range.get("label")
                start_seconds = raw_clip_range.get("start_seconds")
                if label is None or start_seconds is None:
                    continue
                clip_ranges.append(
                    ClipRange(
                        label=str(label),
                        start_seconds=int(start_seconds),
                        end_seconds=raw_clip_range.get("end_seconds"),
                    )
                )
            if (
                not clip_ranges
                and item_payload.get("clip_range_label")
                and item_payload.get("clip_start_seconds") is not None
            ):
                clip_ranges.append(
                    ClipRange(
                        label=str(item_payload["clip_range_label"]),
                        start_seconds=int(item_payload["clip_start_seconds"]),
                        end_seconds=item_payload.get("clip_end_seconds"),
                    )
                )
            item = DownloadItem(
                id=item_payload["id"],
                source_url=item_payload["source_url"],
                platform=item_payload["platform"],
                domain=item_payload["domain"],
                status=item_payload["status"],
                supported=item_payload["supported"],
                sequence_label=sequence_label,
                output_name=item_payload.get("output_name", sanitize_file_stem(sequence_label)),
                sheet_row_number=item_payload.get("sheet_row_number", index),
                clip_ranges=tuple(clip_ranges),
                attempt_count=item_payload.get("attempt_count", 0),
                output_path=item_payload.get("output_path"),
                error=item_payload.get("error"),
                started_at=item_payload.get("started_at"),
                completed_at=item_payload.get("completed_at"),
            )
            item.error = self._normalize_loaded_item_error(item)
            items.append(item)
        return DownloadBatch(
            id=payload["id"],
            sheet_url=payload["sheet_url"],
            created_at=payload["created_at"],
            status=payload["status"],
            sheet_id=payload["sheet_id"],
            gid=payload.get("gid"),
            sheet_access_mode=payload.get("sheet_access_mode", "anonymous"),
            discovered_url_count=payload["discovered_url_count"],
            output_dir=payload.get("output_dir", str(DEFAULT_OUTPUT_DIR)),
            cookies_map=payload.get("cookies_map", {}),
            quality=payload.get("quality", "auto"),
            concurrent_downloads=payload.get("concurrent_downloads", MAX_CONCURRENT_DOWNLOADS),
            retry_count=payload.get("retry_count", 1),
            use_browser_cookies=payload.get("use_browser_cookies", True),
            has_manual_cookies=bool(payload.get("cookies_map", {})),
            last_updated_at=payload.get("last_updated_at", payload.get("created_at")),
            items=items,
        )

    def _serialize_batch_summary(self, batch: DownloadBatch) -> dict:
        serialized = self._serialize_batch(batch)
        return {
            "id": batch.id,
            "createdAt": batch.created_at,
            "lastUpdatedAt": batch.last_updated_at or batch.created_at,
            "status": batch.status,
            "sheetUrl": batch.sheet_url,
            "discoveredUrlCount": batch.discovered_url_count,
            "sheetAccessMode": batch.sheet_access_mode,
            "outputDir": batch.output_dir,
            "stats": serialized["stats"],
        }

    def _serialize_batch_detail(self, batch: DownloadBatch) -> dict:
        return {
            "id": batch.id,
            "createdAt": batch.created_at,
            "lastUpdatedAt": batch.last_updated_at or batch.created_at,
            "status": batch.status,
            "sheetUrl": batch.sheet_url,
            "sheetId": batch.sheet_id,
            "gid": batch.gid,
            "sheetAccessMode": batch.sheet_access_mode,
            "discoveredUrlCount": batch.discovered_url_count,
            "outputDir": batch.output_dir,
            "stats": self._serialize_batch(batch)["stats"],
            "settingsSnapshot": {
                "outputDir": batch.output_dir,
                "quality": batch.quality,
                "concurrentDownloads": batch.concurrent_downloads,
                "retryCount": batch.retry_count,
                "useBrowserCookies": batch.use_browser_cookies,
                "hasManualCookies": batch.has_manual_cookies,
                "cookiesMap": batch.cookies_map,
            },
            "items": self._explode_item_details(batch.items),
        }

    def _serialize_item_detail(self, item: DownloadItem) -> dict:
        return {
            "id": item.id,
            "sequenceLabel": item.sequence_label,
            "rowNumber": item.sheet_row_number,
            "platform": self._display_platform_name(item),
            "sourceUrl": item.source_url,
            "clipRange": item.clip_range_label,
            "status": item.status,
            "supported": item.supported,
            "attemptCount": item.attempt_count,
            "message": self._item_message(item),
            "outputPath": item.output_path,
            "startedAt": item.started_at,
            "completedAt": item.completed_at,
        }

    def _explode_item_details(self, items: list[DownloadItem]) -> list[dict]:
        results: list[dict] = []
        for item in items:
            base = self._serialize_item_detail(item)
            base["clipRange"] = None  # Base video row has no specific clip range
            
            if not item.clip_ranges:
                results.append(base)
                continue
                
            results.append(base)
            for i, clip_range in enumerate(item.clip_ranges, start=1):
                clip = base.copy()
                clip["id"] = f"{item.id}-{i}"
                clip["sequenceLabel"] = f"{item.sequence_label}.{i}"
                clip["clipRange"] = clip_range.label
                
                if item.output_path and item.status == "completed":
                    p = Path(item.output_path)
                    clip_path = p.with_name(f"{p.stem}.{i}{p.suffix}")
                    if clip_path.exists():
                        clip["outputPath"] = str(clip_path)
                        clip["message"] = str(clip_path)
                    else:
                        clip["outputPath"] = None
                        clip["message"] = "Clip extraction missing/failed"
                        clip["status"] = "failed"
                else:
                    clip["outputPath"] = None
                    # inherit status from parent
                    if item.status == "completed":
                        clip["status"] = "failed"
                
                results.append(clip)
        return results

    def _item_message(self, item: DownloadItem) -> str:
        if item.error:
            return item.error
        if item.output_path:
            return item.output_path
        if item.supported:
            return "Dang cho downloader xu ly."
        platform_name = self._display_platform_name(item)
        if platform_name != "unsupported":
            return (
                f"Platform {platform_name} da duoc nhan dien, nhung downloader "
                "hien tai chua ho tro."
            )
        return "Link chua map vao platform ho tro."

    def _display_platform_name(self, item: DownloadItem) -> str:
        if item.platform != "unsupported":
            return item.platform

        recovered_match = detect_platform(item.source_url)
        if recovered_match.name != "unsupported":
            return recovered_match.name
        return item.platform

    def _normalize_loaded_item_error(self, item: DownloadItem) -> str | None:
        if not item.error:
            return item.error
        return self._format_download_error(item, item.error)

    def _batch_matches_filters(
        self,
        batch: DownloadBatch,
        status: str | None = None,
        query: str | None = None,
    ) -> bool:
        if status and status != "all" and batch.status != status:
            return False
        if not query:
            return True

        normalized = query.strip().lower()
        if not normalized:
            return True

        haystacks = [batch.sheet_url.lower(), batch.id.lower()]
        return any(normalized in value for value in haystacks)

    def _record_event_locked(self, event_type: str, payload: dict) -> None:
        event = {
            "type": event_type,
            "timestamp": utc_now(),
            **payload,
        }
        with self._event_condition:
            self._event_sequence += 1
            event["id"] = self._event_sequence
            self._event_backlog.append(event)
            if len(self._event_backlog) > MAX_EVENT_BACKLOG:
                self._event_backlog = self._event_backlog[-MAX_EVENT_BACKLOG:]
            self._event_condition.notify_all()

    def _require_batch(self, batch_id: str) -> DownloadBatch:
        batch = self._batches.get(batch_id)
        if batch is None:
            raise ValueError("Batch not found.")
        return batch

    def _require_item(self, batch: DownloadBatch, item_id: str) -> DownloadItem:
        for item in batch.items:
            if item.id == item_id:
                return item
        raise ValueError("Item not found.")


manager = DownloadManager()
