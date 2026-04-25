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
from urllib.parse import urlparse

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
    "threads": ["threads.net", "threads.com", "instagram.com"],
    "reddit": ["reddit.com", "redd.it"],
    "telegram": ["t.me", "telegram.me", "telegram.dog"],
    "dailymotion": ["dailymotion.com", "dai.ly"],
    "yandex": ["yandex.ru", "yandex.com", "yandex.by", "yandex.kz", "yandex.ua", "yandex.com.tr"],
    "nicovideo": ["nicovideo.jp", "nico.ms"],
    "28lab": ["28lab.com"],
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


def build_sheet_sequence_stem(
    sheet_title: str | None,
    sequence_label: str | None,
    channel_prefix: str | None = None,
) -> str:
    raw_channel_prefix = (channel_prefix or "").strip()
    channel_stem = sanitize_file_stem(raw_channel_prefix) if raw_channel_prefix else ""
    sequence_stem = sanitize_file_stem(sequence_label or "item")
    if channel_stem:
        return f"{channel_stem}.{sequence_stem}"
    return sequence_stem


@dataclass
class DownloadSettings:
    output_dir: str
    quality: str = "auto"
    concurrent_downloads: int = MAX_CONCURRENT_DOWNLOADS
    retry_count: int = 1
    use_browser_cookies: bool = True
    channel_prefix: str = ""
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
    channel_prefix: str
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
    use_impersonation: bool = True
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
        self._direct_url_cache: dict[str, str] = {}
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
                channel_prefix=batch.channel_prefix,
                cookies_map=self._batch_cookie_map.get(batch.id, {}),
            )
            batch.output_dir = settings.output_dir
            batch.quality = settings.quality
            batch.concurrent_downloads = settings.concurrent_downloads
            batch.retry_count = settings.retry_count
            batch.use_browser_cookies = settings.use_browser_cookies
            batch.channel_prefix = settings.channel_prefix
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
                    "sourceUrl": match.normalized_url,
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
            base_name = build_sheet_sequence_stem(
                scan_result.sheet_title,
                entry.sequence_label,
                settings.channel_prefix,
            )
            suffix = used_names.get(base_name, 0) + 1
            used_names[base_name] = suffix
            output_name = base_name if suffix == 1 else f"{base_name}-{suffix}"

            items.append(
                DownloadItem(
                    id=str(uuid.uuid4()),
                    source_url=match.normalized_url,
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
            channel_prefix=settings.channel_prefix,
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
        processing_error: str | None = None

        try:
            # Build ONE shared cookie file for the entire batch — avoids 20x redundant
            # browser cookie reads when running concurrent worker threads.
            shared_cookie_path: str | None = None
            with self._lock:
                batch_obj = self._batches.get(batch_id)
            if batch_obj is not None:
                try:
                    shared_cookie_path = self._prepare_batch_cookie_file(batch_obj)
                except Exception as exc:
                    print(f"[DEBUG] Failed to prepare shared cookie file for batch {batch_id}: {exc}", flush=True)
                    shared_cookie_path = None
            self._batch_shared_cookie[batch_id] = shared_cookie_path

            def run_worker() -> None:
                while not cancel_event.is_set():
                    try:
                        item_id = queue.get_nowait()
                    except Empty:
                        return

                    try:
                        self._process_item(batch_id, item_id, cancel_event)
                    except Exception as exc:
                        if cancel_event.is_set():
                            self._mark_item_cancelled(batch_id, item_id)
                        else:
                            self._update_item(
                                batch_id,
                                item_id,
                                status="failed",
                                completed_at=utc_now(),
                                error=f"Worker crashed while processing item: {exc}",
                            )
                    finally:
                        queue.task_done()

            for _ in range(worker_count):
                worker = threading.Thread(target=run_worker, daemon=True)
                workers.append(worker)
                worker.start()

            for worker in workers:
                worker.join()
        except Exception as exc:
            processing_error = str(exc) or exc.__class__.__name__
            print(f"[DEBUG] Batch worker crashed for batch {batch_id}: {processing_error}", flush=True)
        finally:
            # Cleanup shared cookie file
            shared = self._batch_shared_cookie.pop(batch_id, None)
            if shared:
                Path(shared).unlink(missing_ok=True)

            with self._lock:
                batch = self._batches.get(batch_id)
                if batch is not None:
                    if processing_error:
                        for item in batch.items:
                            if item.supported and item.status == "queued":
                                item.status = "failed"
                                item.error = f"Batch worker crashed before processing item: {processing_error}"
                                item.completed_at = utc_now()
                    elif cancel_event.is_set():
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
            except Exception as exc:
                print(f"[DEBUG] Browser cookie export failed for batch {batch.id}: {exc}", flush=True)
            finally:
                Path(browser_temp.name).unlink(missing_ok=True)

        for platform, cookies_text in batch_cookie_map.items():
            if not cookies_text.strip():
                continue
            manual_path, should_cleanup = self._materialize_manual_cookie_file(cookies_text)
            try:
                cookie_count += self._merge_cookie_file(merged, manual_path)
            except Exception as exc:
                print(f"[DEBUG] Ignoring invalid manual cookies for platform {platform}: {exc}", flush=True)
            finally:
                if should_cleanup:
                    Path(manual_path).unlink(missing_ok=True)

        if cookie_count <= 0:
            Path(target_file.name).unlink(missing_ok=True)
            return None

        try:
            merged.save(ignore_discard=True, ignore_expires=True)
        except Exception as exc:
            print(f"[DEBUG] Failed to save merged cookie file for batch {batch.id}: {exc}", flush=True)
            Path(target_file.name).unlink(missing_ok=True)
            return None
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
                        direct_url = self._resolve_dumpert_direct_url(
                            item.source_url,
                            cookie_file_path=cookie_file_path,
                        )
                        if not direct_url:
                            last_error = "Could not scrape direct MP4 URL from Dumpert HTML."
                            continue
                        attempt_url = direct_url
                        print(f"[DEBUG] Dumpert scraper found direct URL: {attempt_url}", flush=True)

                    if attempt.label == "threads_html_scraping_fallback":
                        direct_url = self._resolve_threads_direct_url(item.source_url, cookie_file_path=cookie_file_path)
                        if not direct_url:
                            last_error = "Could not scrape direct MP4 URL from Threads HTML."
                            continue
                        attempt_url = direct_url
                        print(f"[DEBUG] Threads scraper found direct URL: {attempt_url}", flush=True)

                    if attempt.label == "dailymotion_no_impersonate_fallback":
                        # This is a standard yt-dlp attempt but with no-impersonate
                        attempt_url = item.source_url

                    if attempt.label == "dailymotion_html_scraping_fallback":
                        direct_url = self._resolve_dailymotion_direct_url(item.source_url, cookie_file_path=cookie_file_path)
                        if not direct_url:
                            last_error = "Could not scrape direct stream from Dailymotion metadata."
                            continue
                        attempt_url = direct_url
                        print(f"[DEBUG] Dailymotion scraper found direct URL: {attempt_url}", flush=True)
                        
                    if attempt.label == "yandex_html_scraping_fallback":
                        direct_url = self._resolve_yandex_direct_url(item.source_url, cookie_file_path=cookie_file_path)
                        if not direct_url:
                            last_error = "Could not scrape direct/embed URL from Yandex page."
                            continue
                        attempt_url = direct_url
                        print(f"[DEBUG] Yandex scraper found embedded URL: {attempt_url}", flush=True)

                    if attempt.label == "28lab_html_scraping_fallback":
                        direct_url = self._resolve_28lab_direct_url(
                            item.source_url,
                            cookie_file_path=cookie_file_path,
                        )
                        if not direct_url:
                            last_error = "Could not scrape direct MP4 URL from 28lab page."
                            continue
                        attempt_url = direct_url
                        print(f"[DEBUG] 28lab scraper found direct URL: {attempt_url}", flush=True)

                    command = self._build_yt_dlp_command(
                        item=item,
                        attempt_url=attempt_url,
                        output_template=output_template,
                        cookie_file_path=cookie_file_path,
                        quality=quality,
                        use_cookie_file=attempt.use_cookie_file,
                        use_impersonation=attempt.use_impersonation,
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
                        final_output_path = self._resolve_final_output_path(
                            target_dir=target_dir,
                            output_name=item.output_name,
                            yt_dlp_lines=lines,
                        )
                        final_output_path = self._ensure_h264_output(batch_id, item, final_output_path, cancel_event)
                        return self._auto_cut_file(batch_id, item, final_output_path, cancel_event)

                    if attempt.label == "threads_html_scraping_fallback":
                        # If the scraped direct URL also failed in yt-dlp, 
                        # there's not much else we can do with it.
                        pass

                    last_error = (stderr or stdout or "yt-dlp failed").strip()
                    if "could not find firefox cookies database" in last_error.lower():
                        continue

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
                            use_impersonation=attempt.use_impersonation,
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
                            final_output_path = self._resolve_final_output_path(
                                target_dir=target_dir,
                                output_name=item.output_name,
                                yt_dlp_lines=lines,
                            )
                            final_output_path = self._ensure_h264_output(batch_id, item, final_output_path, cancel_event)
                            return self._auto_cut_file(batch_id, item, final_output_path, cancel_event)
                        last_error = (stderr or stdout or "yt-dlp failed").strip()
                        if "could not find firefox cookies database" in last_error.lower():
                            continue

                    if not self._should_retry_yt_dlp_attempt(item, attempt.label, last_error):
                        break
            finally:
                pass

            raise RuntimeError(self._format_download_error(item, last_error))

    def _resolve_final_output_path(
        self,
        target_dir: Path,
        output_name: str,
        yt_dlp_lines: list[str],
    ) -> str:
        expected_mp4 = target_dir / f"{output_name}.mp4"
        if expected_mp4.exists():
            return str(expected_mp4)

        candidates: list[Path] = []
        for line in yt_dlp_lines:
            candidate = Path(line.strip())
            if candidate.exists() and candidate.is_file():
                candidates.append(candidate)

        if not candidates:
            candidates = [path for path in target_dir.glob(f"{output_name}*") if path.is_file()]
        if not candidates:
            return str(expected_mp4)

        def score(path: Path) -> int:
            name = path.name.lower()
            has_video = self._probe_video_codec(path) is not None
            value = 0
            if path == expected_mp4:
                value += 1000
            if has_video:
                value += 500
            if path.suffix.lower() == ".mp4":
                value += 120
            elif path.suffix.lower() in {".mkv", ".webm"}:
                value += 80
            if ".fau" in name or ".fdash-" in name:
                value -= 300
            if ".fvh" in name or ".fhls-" in name:
                value -= 120
            return value

        best = max(candidates, key=score)
        if best.exists() and best != expected_mp4:
            if expected_mp4.exists():
                return str(expected_mp4)
            if self._probe_video_codec(best) is not None:
                try:
                    best.replace(expected_mp4)
                    return str(expected_mp4)
                except OSError:
                    return str(best)
        return str(best)

    def _yt_dlp_attempts_for(self, item: DownloadItem) -> list[YtDlpAttempt]:
        attempts = [YtDlpAttempt(label="default")]
        if item.platform == "youtube":
            # First fallback: Use yt-dlp's native browser extraction which is sometimes better at decrypting YouTube's complex signature cookies
            # yt-dlp doesn't know 'coccoc' by name, but Coc Coc is Chromium-based. 
            # We can use the 'chrome' engine and point it to the Coc Coc User Data directory.
            coccoc_path = os.path.expandvars(r"%LOCALAPPDATA%\CocCoc\Browser\User Data")
            if self._is_chromium_profile_available(coccoc_path):
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
            # Final fallback set: extract cookies directly from common local browsers
            # instead of relying only on the exported batch cookie file.
            for browser in self._available_cookie_browsers(("chrome", "edge", "firefox")):
                attempts.append(
                    YtDlpAttempt(
                        label=f"youtube_{browser}_cookies_fallback",
                        use_cookie_file=False,
                        extra_args=(
                            "--cookies-from-browser",
                            browser,
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
        if item.platform == "threads":
            # Attempt 2: Custom HTML/JSON scraper as a robust fallback
            attempts.append(
                YtDlpAttempt(
                    label="threads_html_scraping_fallback",
                    extra_args=(),
                )
            )
        if item.platform == "dailymotion":
            # High Priority Fallback for Windows dependency issues
            attempts.append(
                YtDlpAttempt(
                    label="dailymotion_no_impersonate_fallback",
                    use_impersonation=False,
                )
            )
            attempts.append(
                YtDlpAttempt(
                    label="dailymotion_html_scraping_fallback",
                    extra_args=(),
                )
            )
        if item.platform == "yandex":
            attempts.append(
                YtDlpAttempt(
                    label="yandex_html_scraping_fallback",
                    extra_args=(),
                )
            )
        if item.platform == "nicovideo":
            # Some Nico links fail with stale/partial cookies; retry without cookie file.
            attempts.append(
                YtDlpAttempt(
                    label="nicovideo_no_cookie_fallback",
                    use_cookie_file=False,
                )
            )
            # Then try browser-native cookie extraction.
            for browser in self._available_cookie_browsers(("chrome", "edge", "firefox")):
                attempts.append(
                    YtDlpAttempt(
                        label=f"nicovideo_{browser}_cookies_fallback",
                        use_cookie_file=False,
                        extra_args=(
                            "--cookies-from-browser",
                            browser,
                        ),
                    )
                )
            # Last retry for environments where impersonation/curl backends are unstable.
            attempts.append(
                YtDlpAttempt(
                    label="nicovideo_no_impersonate_fallback",
                    use_impersonation=False,
                )
            )
        if item.platform == "28lab":
            attempts.append(
                YtDlpAttempt(
                    label="28lab_html_scraping_fallback",
                    extra_args=(),
                )
            )
        return attempts

    def _available_cookie_browsers(self, candidates: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(browser for browser in candidates if self._is_browser_cookie_source_available(browser))

    def _is_browser_cookie_source_available(self, browser: str) -> bool:
        browser_key = (browser or "").strip().lower()
        if browser_key == "chrome":
            return self._is_chromium_profile_available(os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data"))
        if browser_key == "edge":
            return self._is_chromium_profile_available(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data"))
        if browser_key == "firefox":
            profiles_dir = Path(os.path.expandvars(r"%APPDATA%\Mozilla\Firefox\Profiles"))
            if not profiles_dir.exists() or not profiles_dir.is_dir():
                return False
            try:
                for profile in profiles_dir.iterdir():
                    if profile.is_dir() and (profile / "cookies.sqlite").exists():
                        return True
            except OSError:
                return False
            return False
        return False

    def _is_chromium_profile_available(self, user_data_dir: str) -> bool:
        user_data = Path(user_data_dir)
        if not user_data.exists() or not user_data.is_dir():
            return False
        if (user_data / "Local State").exists():
            return True
        try:
            for profile_name in ("Default", "Profile 1", "Profile 2"):
                if (user_data / profile_name / "Network" / "Cookies").exists():
                    return True
                if (user_data / profile_name / "Cookies").exists():
                    return True
        except OSError:
            return False
        return False

    def _build_yt_dlp_command(
        self,
        item: DownloadItem,
        attempt_url: str,
        output_template: str,
        cookie_file_path: str | None,
        quality: str,
        use_cookie_file: bool = True,
        use_impersonation: bool = True,
        extra_args: tuple[str, ...] = (),
    ) -> list[str]:
        command = [*self._yt_dlp_cmd]
        if use_impersonation and self._impersonate_target:
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
        if item.platform == "nicovideo":
            # Nico can throttle aggressively when segment concurrency is high.
            return ["--concurrent-fragments", "2"]
        if item.platform == "28lab":
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

        if item.platform == "threads":
            return attempt_label == "default"

        if item.platform == "dailymotion":
            return attempt_label in {"default", "dailymotion_no_impersonate_fallback"}

        if item.platform == "yandex":
            return attempt_label == "default"

        if item.platform == "28lab":
            return attempt_label == "default"

        if item.platform == "nicovideo":
            return attempt_label in {
                "default",
                "nicovideo_no_cookie_fallback",
                "nicovideo_chrome_cookies_fallback",
                "nicovideo_edge_cookies_fallback",
                "nicovideo_firefox_cookies_fallback",
                "nicovideo_no_impersonate_fallback",
            }

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
            "youtube_android_no_cookie_fallback",
            "youtube_chrome_cookies_fallback",
            "youtube_edge_cookies_fallback",
            "youtube_firefox_cookies_fallback",
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

    def _resolve_dumpert_direct_url(
        self,
        source_url: str,
        cookie_file_path: str | None = None,
    ) -> str | None:
        import re
        import urllib.request

        if "?selectedId=" in source_url:
            video_id = source_url.split("?selectedId=")[-1]
            target_url = f"https://www.dumpert.nl/item/{video_id}"
        else:
            target_url = source_url

        html = self._curl_fetch_text(target_url, cookie_file_path=cookie_file_path, impersonate="chrome")
        if not html:
            try:
                req = urllib.request.Request(
                    target_url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                        ),
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.5",
                    },
                )
                html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="replace")
            except Exception as exc:
                print(f"[DEBUG] Dumpert HTML fallback fetch failed: {exc}", flush=True)
                return None

        html = html.replace("\\/", "/")
        candidate_urls = list(
            re.finditer(
                r'https?://[^\s\"\'\>\\]+?\.(?:mp4|m3u8)(?:\?[^\s\"\'\>\\]+)?',
                html,
            )
        )
        if not candidate_urls:
            return None

        best_url: str | None = None
        best_score = -1
        for match in candidate_urls:
            url = match.group(0)
            if "dumpert.nl" not in url and "media.dumpert.nl" not in url:
                continue
            score = 0
            if url.endswith(".mp4") or ".mp4?" in url:
                score += 10
            if "m3u8" in url:
                score += 20
            quality_match = re.search(r"/(\d{3,4})/index\.m3u8", url)
            if quality_match:
                score += int(quality_match.group(1))
            if score > best_score:
                best_score = score
                best_url = url
        return best_url

    def _resolve_28lab_direct_url(
        self,
        source_url: str,
        cookie_file_path: str | None = None,
    ) -> str | None:
        import html
        import re
        import urllib.request

        page_html = self._curl_fetch_text(source_url, cookie_file_path=cookie_file_path, impersonate="chrome")
        if not page_html:
            try:
                req = urllib.request.Request(
                    source_url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                        ),
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.5",
                        "Referer": "https://28lab.com/",
                    },
                )
                page_html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", errors="replace")
            except Exception as exc:
                print(f"[DEBUG] 28lab HTML fetch failed: {exc}", flush=True)
                return None

        page_html = page_html.replace("\\/", "/")
        # Primary path: <video ... src="...mp4">
        video_src_matches = re.finditer(r"<video[^>]*\bsrc=[\"']([^\"']+)[\"']", page_html, flags=re.IGNORECASE)
        for match in video_src_matches:
            candidate = html.unescape(match.group(1)).strip()
            if not candidate:
                continue
            if candidate.startswith("//"):
                candidate = "https:" + candidate
            if candidate.startswith("/"):
                parsed = urlparse(source_url)
                candidate = f"{parsed.scheme}://{parsed.netloc}{candidate}"
            if candidate.lower().startswith("http") and (".mp4" in candidate.lower() or ".m3u8" in candidate.lower()):
                return candidate

        # Secondary path: generic MP4/M3U8 URL in script blobs.
        generic_matches = re.finditer(
            r'https?://[^\s\"\'\>\\]+?\.(?:mp4|m3u8)(?:\?[^\s\"\'\>\\]+)?',
            page_html,
        )
        for match in generic_matches:
            candidate = match.group(0)
            if "28lab.com" in candidate:
                return candidate
        return None

    def _curl_fetch_text(self, url: str, cookie_file_path: str | None = None, impersonate: str = "chrome") -> str | None:
        try:
            from curl_cffi import requests
        except ImportError:
            return None

        cookies = {}
        if cookie_file_path and os.path.exists(cookie_file_path):
            try:
                import http.cookiejar
                jar = http.cookiejar.MozillaCookieJar(cookie_file_path)
                jar.load(ignore_discard=True, ignore_expires=True)
                for cookie in jar:
                    cookies[cookie.name] = cookie.value
            except Exception as exc:
                print(f"[DEBUG] Failed to load cookies for curl-cffi: {exc}", flush=True)

        try:
            # Use curl-cffi to mimic a real browser perfectly
            response = requests.get(
                url,
                cookies=cookies,
                impersonate=impersonate,
                timeout=20,
                verify=True
            )
            if response.status_code == 200:
                return response.text
            print(f"[DEBUG] curl-cffi fetch failed with status {response.status_code}", flush=True)
        except Exception as exc:
            print(f"[DEBUG] curl-cffi fetch exception: {exc}", flush=True)
        
        return None

    def _is_threads_media_url(self, url: str) -> bool:
        hostname = (urlparse(url).hostname or "").lower()
        return (
            hostname.endswith("fbcdn.net")
            or hostname.endswith("cdninstagram.com")
            or hostname.endswith("instagram.com")
        )

    def _resolve_threads_direct_url(self, source_url: str, cookie_file_path: str | None = None) -> str | None:
        import re
        import json

        # 1. Check Cache first (Threads links usually don't expire for a few hours)
        if source_url in self._direct_url_cache:
            return self._direct_url_cache[source_url]

        # 2. Try curl-cffi first for stealth
        html = self._curl_fetch_text(source_url, cookie_file_path, impersonate="safari_ios")
        
        if not html:
            import urllib.request
            import http.cookiejar
            jar = http.cookiejar.MozillaCookieJar()
            if cookie_file_path and os.path.exists(cookie_file_path):
                try: jar.load(cookie_file_path, ignore_discard=True, ignore_expires=True)
                except Exception: pass
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            try:
                req = urllib.request.Request(source_url, headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"})
                html = opener.open(req, timeout=15).read().decode("utf-8", errors="replace")
            except Exception:
                return None

        # Level 2 — chuẩn bài (detect private posts)
        if "This account is private" in html or "Hãy theo dõi để xem ảnh và video" in html:
            print(f"[DEBUG] Threads post is private. Need fresh cookies and follower access.", flush=True)
            return None

        # Fix JSON escaping in the full HTML
        html_unquoted = html.replace('\\/', '/')
        
        # Level 2 — Standard JSON embedded parsing
        json_blobs = re.findall(
            r'<script type="application/json"[^>]*>(.*?)</script>',
            html,
            flags=re.DOTALL,
        )
        for blob in json_blobs:
            if "video_versions" not in blob:
                continue
            
            try:
                data = json.loads(blob)
                def find_videos(obj):
                    urls = []
                    if isinstance(obj, dict):
                        if "video_versions" in obj and isinstance(obj["video_versions"], list):
                            for v in obj["video_versions"]:
                                if isinstance(v, dict) and "url" in v:
                                    url = str(v["url"]).replace("\\/", "/")
                                    if self._is_threads_media_url(url):
                                        urls.append((int(v.get("width", 0) or 0), url))
                        for k, v in obj.items():
                            urls.extend(find_videos(v))
                    elif isinstance(obj, list):
                        for item in obj:
                            urls.extend(find_videos(item))
                    return urls
                
                all_videos = find_videos(data)
                if all_videos:
                    # Sort by resolution (descending) to get the best quality source
                    all_videos.sort(key=lambda x: x[0], reverse=True)
                    url = all_videos[0][1]
                    self._direct_url_cache[source_url] = url
                    return url
            except Exception:
                pass

            # Level 1 Fallback inside the blob
            video_matches = re.finditer(
                r'"url"\s*:\s*"(https?://[^"]+?\.mp4[^"]*)"',
                blob.replace('\\/', '/'),
            )
            for match in video_matches:
                url = match.group(1)
                if self._is_threads_media_url(url):
                    self._direct_url_cache[source_url] = url
                    return url

        # Level 1.5 Fallback on the whole page when the JSON wrapper changes
        for body_match in re.finditer(
            r'"video_versions"\s*:\s*\[(.*?)\]',
            html_unquoted,
            flags=re.DOTALL,
        ):
            body = body_match.group(1)
            for stream_match in re.finditer(r'"url"\s*:\s*"(https?://[^"]+?\.mp4[^"]*)"', body):
                url = stream_match.group(1)
                if self._is_threads_media_url(url):
                    self._direct_url_cache[source_url] = url
                    return url

        # 2. Fallback to broad regex
        match = re.search(r'https?://[^\s\"\'\>\\]+?\.mp4[^\s\"\'\>\\]*', html_unquoted)
        if match:
            url = match.group(0).split('"')[0].split("'")[0]
            if self._is_threads_media_url(url):
                cleaned = url.rstrip(')"\'\\')
                self._direct_url_cache[source_url] = cleaned
                return cleaned

        return None

    def _resolve_dailymotion_direct_url(self, source_url: str, cookie_file_path: str | None = None) -> str | None:
        import re
        import json

        # Extract ID
        matched = re.search(r'/video/([a-zA-Z0-9]+)', source_url)
        if not matched:
            matched = re.search(r'dai\.ly/([a-zA-Z0-9]+)', source_url)
        
        if not matched: return None
        
        video_id = matched.group(1)
        metadata_url = f"https://www.dailymotion.com/player/metadata/video/{video_id}"

        # Fetch using curl-cffi for impersonation
        content = self._curl_fetch_text(metadata_url, cookie_file_path, impersonate="chrome")
        
        if not content:
            # Fallback to urllib
            import urllib.request
            import http.cookiejar
            jar = http.cookiejar.MozillaCookieJar()
            if cookie_file_path and os.path.exists(cookie_file_path):
                try: jar.load(cookie_file_path, ignore_discard=True, ignore_expires=True)
                except Exception: pass
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            try:
                req = urllib.request.Request(metadata_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"})
                content = opener.open(req, timeout=10).read().decode("utf-8")
            except Exception:
                return None

        try:
            data = json.loads(content)
            qualities = data.get("qualities", {})
            for q_key in ["auto", "1080", "720", "480", "380"]:
                streams = qualities.get(q_key, [])
                for stream in streams:
                    if "url" in stream:
                        return stream["url"]
        except Exception:
            pass
        
        return None

    def _resolve_yandex_direct_url(self, source_url: str, cookie_file_path: str | None = None) -> str | None:
        import urllib.parse
        import html
        
        # Fetch using curl-cffi for stealth
        page_html = self._curl_fetch_text(source_url, cookie_file_path, impersonate="chrome")
        if not page_html:
            # Fallback to urllib
            import urllib.request
            import http.cookiejar
            jar = http.cookiejar.MozillaCookieJar()
            if cookie_file_path and os.path.exists(cookie_file_path):
                try: jar.load(cookie_file_path, ignore_discard=True, ignore_expires=True)
                except Exception: pass
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            try:
                req = urllib.request.Request(source_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"})
                page_html = opener.open(req, timeout=15).read().decode("utf-8", errors="replace")
            except Exception:
                return None

        # Look for iframes
        iframes = re.findall(r'<iframe[^>]*src="([^"]+)"', page_html)
        for src in iframes:
            # Unescape HTML entities
            src = html.unescape(src)
            if src.startswith("//"):
                src = "https:" + src
            
            # 1. Handle Yandex's own video-player wrapper which often embeds the real source
            if "video-player" in src:
                fragment = urllib.parse.urlparse(src).fragment
                params = urllib.parse.parse_qs(fragment)
                if "html" in params:
                    # The fragment contains an inner iframe in 'html' param
                    inner_html = params["html"][0]
                    inner_src_match = re.search(r'src="([^"]+)"', inner_html)
                    if inner_src_match:
                        inner_src = html.unescape(inner_src_match.group(1))
                        if inner_src.startswith("//"):
                            inner_src = "https:" + inner_src
                        return inner_src

            # 2. Check for common external video hosts
            for host in ["youtube.com", "youtu.be", "ok.ru", "rutube.ru", "vimeo.com", "vk.com"]:
                if host in src:
                    return src

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
                f"{source_path.stem}.{clip_index}.mp4"
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
                error_lines = message.splitlines()
                context = "\n".join(error_lines[-3:]) if len(error_lines) >= 3 else message
                raise RuntimeError(f"FFmpeg Auto-cut failed:\n{context}")

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

        if is_frozen():
            packaged = resolve_binary("yt-dlp", env_var="VIDEO_DOWNLOADER_YT_DLP_BIN")
            if packaged:
                return [packaged]
            return [sys.executable, "--run-yt-dlp"]

        if importlib.util.find_spec("yt_dlp") is not None:
            scripts_dir = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")
            script_name = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
            python_name = "python.exe" if os.name == "nt" else "python"

            venv_script = scripts_dir / script_name
            if venv_script.exists():
                return [str(venv_script)]

            venv_python = scripts_dir / python_name
            if venv_python.exists():
                return [str(venv_python), "-m", "yt_dlp"]

            return [sys.executable, "-m", "yt_dlp"]

        packaged = resolve_binary("yt-dlp", env_var="VIDEO_DOWNLOADER_YT_DLP_BIN")
        if packaged:
            return [packaged]

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
            or "sign in to confirm you’re not a bot" in lowered
            or "sign in to confirm you're not a bot" in lowered
        ):
            return (
                "YouTube dang tu choi hoac an bot format cua link nay. App da thu them "
                "fallback Android client, cookie fallback cho Chrome/Edge/Firefox, "
                "va thu ca co/khong cookie browser, nhung mot so "
                "video van can PO token/GVS access nen yt-dlp co the that bai."
            )

        if item.platform == "nicovideo" and (
            "403" in compact
            or "login required" in lowered
            or "forbidden" in lowered
            or "authentication" in lowered
        ):
            return (
                "NicoVideo tu choi request hoac can session hop le. App da thu "
                "fallback khong-cookie va cookies-from-browser (Chrome/Edge/Firefox) "
                "nhung van that bai."
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
        channel_prefix = str(payload.get("channel_prefix", base.channel_prefix)).strip()
        
        cmap = payload.get("cookies_map")
        if cmap is None and "cookies_text" in payload:
            cmap = {"default": str(payload.get("cookies_text", ""))}
        elif cmap is None:
            cmap = base.cookies_map
        cmap = self._normalize_cookie_map(cmap)

        return DownloadSettings(
            output_dir=str(Path(output_dir).expanduser()),
            quality=quality,
            concurrent_downloads=concurrent_downloads,
            retry_count=retry_count,
            use_browser_cookies=use_browser_cookies,
            channel_prefix=channel_prefix,
            cookies_map=cmap,
        )

    def _normalize_cookie_map(self, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}

        normalized: dict[str, str] = {}
        for key, raw_cookie in value.items():
            platform = str(key).strip()
            cookie_text = str(raw_cookie).strip()
            if not platform or not cookie_text:
                continue
            normalized[platform] = str(raw_cookie)
        return normalized

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
            channel_prefix=payload.get("channel_prefix", ""),
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
                "channelPrefix": batch.channel_prefix,
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
