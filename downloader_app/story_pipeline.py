from __future__ import annotations

import asyncio
import json
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Empty, PriorityQueue, Queue
from typing import Protocol

from downloader_app.gemini_web_adapter import (
    GEMINI_DEFAULT_URL,
    GeminiWebAdapter,
    GeminiWebError,
    check_gemini_session,
    open_gemini_login_window,
)
from downloader_app.jobs import sanitize_file_stem
from downloader_app.runtime import app_path, cache_path
from downloader_app.xmp_scanner import xmp_scanner


STORY_STATE_FILE = cache_path("story_pipeline", "state.json")
STORY_EXPORT_ROOT = cache_path("story_pipeline", "exports")
STORY_CACHE_ROOT = cache_path("story_pipeline")
MAX_EVENT_BACKLOG = 500
SESSION_STATUS_TTL_SECONDS = 45.0


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def story_debug_root() -> Path:
    return STORY_CACHE_ROOT / "debug" / "gemini_selector"


def story_generated_root() -> Path:
    return STORY_CACHE_ROOT / "generated"


def story_gemini_runtime_root() -> Path:
    return STORY_CACHE_ROOT / "gemini_runtime"


def story_accepted_root() -> Path:
    """Thu muc persistent de luu anh da duoc user accept. Khong bi xoa khi restart."""
    return STORY_CACHE_ROOT / "accepted"


def story_gem_scan_runtime_root() -> Path:
    return STORY_CACHE_ROOT / "gem_scan_runtime"


class StoryPipelineError(RuntimeError):
    pass


@dataclass
class StorySettings:
    output_root: str
    max_parallel_videos: int = 2
    generation_backend: str = "gemini_web"
    gemini_headless: bool = False
    gemini_base_url: str = GEMINI_DEFAULT_URL
    gemini_response_timeout_ms: int = 120_000
    gemini_model: str = "gemini-1.5-flash"


@dataclass
class StoryAttempt:
    id: str
    index: int
    mode: str
    status: str
    prompt: str
    input_image_path: str
    thread_url: str | None = None
    preview_path: str | None = None
    normalized_path: str | None = None
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


@dataclass
class StoryStep:
    id: str
    index: int
    title: str
    modifier_prompt: str
    status: str = "queued"
    selected_attempt_id: str | None = None
    pending_mode: str = "auto"
    pending_input_path: str | None = None
    pending_thread_url: str | None = None
    pending_prompt_override: str | None = None
    attempts: list[StoryAttempt] = field(default_factory=list)


@dataclass
class StoryMarker:
    id: str
    index: int
    label: str
    timestamp_ms: int
    input_frame_path: str
    seed_prompt: str
    status: str = "queued"
    steps: list[StoryStep] = field(default_factory=list)
    parent_marker_id: str | None = None  # None = goc, co gia tri = variant refine
    variant_index: int = 0              # 0 = goc, 1/2/3... = bien the refine


@dataclass
class StoryVideo:
    id: str
    name: str
    source_video_path: str
    mode: str
    video_prompt: str
    status: str
    created_at: str
    last_updated_at: str
    error: str | None = None
    markers: list[StoryMarker] = field(default_factory=list)


@dataclass
class GenerationResult:
    preview_path: str
    normalized_path: str
    thread_url: str | None = None


class StoryGenerationAdapter(Protocol):
    def generate(
        self,
        *,
        prompt: str,
        input_image_path: Path,
        preview_path: Path,
        normalized_path: Path,
        context: dict,
    ) -> GenerationResult: ...





class StoryPipelineManager:
    def __init__(
        self,
        *,
        state_file: Path | None = None,
        output_root: Path | None = None,
        adapter: StoryGenerationAdapter | None = None,
    ) -> None:
        self._state_file = Path(state_file or STORY_STATE_FILE)
        self._lock = threading.RLock()
        self._event_condition = threading.Condition()
        self._event_sequence = 0
        self._event_backlog: list[dict] = []

        self._settings = StorySettings(output_root=str(output_root or STORY_EXPORT_ROOT))
        self._global_prompt = ""
        self._videos: dict[str, StoryVideo] = {}
        self._active_video_id: str | None = None
        self._injected_adapter = adapter
        self._adapter: StoryGenerationAdapter | None = None
        self._queue = PriorityQueue()
        self._queued_marker_ids: set[str] = set()   # marker_id đang trong queue
        self._shutdown_event = threading.Event()
        self._workers: list[threading.Thread] = []
        self._session_status_cache: dict | None = None
        self._session_status_cache_time: float = 0.0

        # Reset thu muc hinh anh generated (cache) khi restart app de tranh rác
        shutil.rmtree(story_generated_root(), ignore_errors=True)

        self._load_state()
        self._reset_runtime_state_for_restart()
        self._refresh_adapter_locked()
        self._start_workers()

    def get_bootstrap(self) -> dict:
        with self._lock:
            return {
                "settings": asdict(self._settings),
                "globalPrompt": self._global_prompt,
                "videoSummaries": [self._serialize_video_summary(video) for video in self._videos.values()],
                "activeVideoId": self._active_video_id,
                "sessionStatus": self._bootstrap_session_status_locked(),
            }

    def _bootstrap_session_status_locked(self) -> dict:
        if self._session_status_cache is not None:
            return dict(self._session_status_cache)

        if False: # Removed local preview
            return {
                "backend": self._settings.generation_backend,
                "dependencies_ready": True,
                "authenticated": True,
                "browser": None,
                "profile_dir": "",
                "message": "Dang dung local preview adapter (khong can Gemini session).",
            }

        return {
            "backend": self._settings.generation_backend,
            "dependencies_ready": False,
            "authenticated": False,
            "browser": None,
            "profile_dir": "",
            "message": "Dang kiem tra phien Gemini...",
        }

    def list_video_summaries(self, *, status: str | None = None, limit: int | None = None) -> list[dict]:
        with self._lock:
            items = [
                self._serialize_video_summary(video)
                for video in self._videos.values()
                if status is None or video.status == status
            ]

        items.sort(key=lambda item: item["createdAt"], reverse=True)
        if limit is not None:
            return items[:limit]
        return items

    def clear_videos(self) -> dict:
        with self._lock:
            self._videos.clear()
            self._active_video_id = None
            self._persist_state_locked()
            self._record_event_locked("story.videos.cleared", {})
        return {"ok": True}

    def get_video_detail(self, video_id: str) -> dict | None:
        with self._lock:
            video = self._videos.get(video_id)
            if video is None:
                return None
            return self._serialize_video_detail(video)

    def export_selected(self, video_id: str, destination_dir: str, step_ids: list[str] | None = None) -> dict:
        target_dir = Path(destination_dir).expanduser()
        target_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            video = self._require_video(video_id)
            selected_attempts: list[tuple[StoryMarker, StoryStep, StoryAttempt]] = []
            for marker in marker_order(video.markers):
                for step in step_order(marker.steps):
                    if not step.selected_attempt_id:
                        continue
                    if step_ids is not None and step.id not in step_ids:
                        continue
                    attempt = next(
                        (candidate for candidate in step.attempts if candidate.id == step.selected_attempt_id),
                        None,
                    )
                    if attempt is None:
                        continue
                    selected_attempts.append((marker, step, attempt))

        if not selected_attempts:
            raise StoryPipelineError("Video nay chua co anh nao duoc chon de export.")

        exported: list[str] = []
        skipped = 0
        for marker, step, attempt in selected_attempts:
            source_path_raw = attempt.normalized_path or attempt.preview_path
            if not source_path_raw:
                skipped += 1
                continue
            source_path = Path(source_path_raw)
            if not source_path.exists():
                skipped += 1
                continue
            suffix = source_path.suffix or ".jpg"
            preferred_name = f"{self._build_attempt_stem(video, marker, step, attempt.index)}{suffix}"
            copied = _copy_with_unique_name(source_path, target_dir, preferred_name)
            exported.append(str(copied))

        if not exported:
            raise StoryPipelineError("Khong tim thay file anh hop le de export.")

        return {
            "exportedCount": len(exported),
            "skippedCount": skipped,
            "destinationDir": str(target_dir),
            "files": exported,
        }

    def get_session_status(self, refresh: bool = False) -> dict:
        with self._lock:
            backend = self._settings.generation_backend
            headless = self._settings.gemini_headless
            base_url = self._settings.gemini_base_url
            runtime_root = story_gemini_runtime_root()
            cache = self._session_status_cache
            cache_time = self._session_status_cache_time

        if (
            not refresh
            and cache is not None
            and (time.monotonic() - cache_time) < SESSION_STATUS_TTL_SECONDS
        ):
            return cache

        if False: # Removed local preview
            status = {
                "backend": backend,
                "dependencies_ready": True,
                "authenticated": True,
                "browser": None,
                "profile_dir": "",
                "message": "Dang dung local preview adapter (khong can Gemini session).",
            }
        else:
            runtime_root.mkdir(parents=True, exist_ok=True)
            checked = check_gemini_session(
                headless=headless,
                base_url=base_url,
                runtime_root=runtime_root,
            )
            status = {
                "backend": backend,
                **asdict(checked),
            }

        with self._lock:
            self._session_status_cache = status
            self._session_status_cache_time = time.monotonic()
        return status

    def open_login(self) -> dict:
        try:
            payload = open_gemini_login_window()
        except GeminiWebError as exc:
            raise StoryPipelineError(str(exc)) from exc
        with self._lock:
            self._invalidate_session_status_cache_locked()
        return payload

    def list_available_gems(self) -> list[dict]:
        if False: # Removed local preview
            return []
        runtime_root = story_gem_scan_runtime_root()
        runtime_root.mkdir(parents=True, exist_ok=True)
        adapter = GeminiWebAdapter(
            runtime_root=runtime_root,
            headless=True,
            base_url=self._settings.gemini_base_url,
            response_timeout_ms=self._settings.gemini_response_timeout_ms,
            model_name=self._settings.gemini_model,
            debug_selector=False,
        )
        return adapter.list_gems()

    def update_settings(self, payload: dict) -> dict:
        with self._lock:
            max_parallel = payload.get("max_parallel_videos", self._settings.max_parallel_videos)
            try:
                max_parallel_videos = int(max_parallel)
            except (TypeError, ValueError):
                raise StoryPipelineError("max_parallel_videos khong hop le")

            output_root = str(payload.get("output_root", self._settings.output_root)).strip() or self._settings.output_root
            generation_backend = str(
                payload.get("generation_backend", self._settings.generation_backend)
            ).strip().lower()
            if False:
                raise StoryPipelineError("generation_backend phai la `local_preview` hoac `gemini_web`.")

            gemini_headless = _bool_value(
                payload.get("gemini_headless", self._settings.gemini_headless),
                default=self._settings.gemini_headless,
            )
            gemini_base_url = str(payload.get("gemini_base_url", self._settings.gemini_base_url)).strip() or self._settings.gemini_base_url
            timeout_raw = payload.get("gemini_response_timeout_ms", self._settings.gemini_response_timeout_ms)
            try:
                gemini_response_timeout_ms = int(timeout_raw)
            except (TypeError, ValueError):
                raise StoryPipelineError("gemini_response_timeout_ms khong hop le")
            gemini_model = str(payload.get("gemini_model", self._settings.gemini_model)).strip() or self._settings.gemini_model

            previous_max_parallel = self._settings.max_parallel_videos
            self._settings = StorySettings(
                output_root=output_root,
                max_parallel_videos=max(1, min(8, max_parallel_videos)),
                generation_backend=generation_backend,
                gemini_headless=gemini_headless,
                gemini_base_url=gemini_base_url,
                gemini_response_timeout_ms=max(20_000, min(300_000, gemini_response_timeout_ms)),
                gemini_model=gemini_model,
            )
            self._refresh_adapter_locked()
            self._invalidate_session_status_cache_locked()
            self._persist_state_locked()
            self._record_event_locked("story.settings.updated", {})

        if previous_max_parallel != self._settings.max_parallel_videos:
            self._restart_workers()
        return asdict(self._settings)

    def update_global_prompt(self, prompt: str) -> dict:
        with self._lock:
            self._global_prompt = prompt.strip()
            self._persist_state_locked()
            self._record_event_locked("story.global_prompt.updated", {})
        return {"globalPrompt": self._global_prompt}

    def import_manifest(self, payload: dict) -> list[dict]:
        manifest = payload.get("manifest")
        manifest_path = str(payload.get("manifest_path", "")).strip()

        if manifest is None and manifest_path:
            file_path = Path(manifest_path)
            if not file_path.exists():
                raise StoryPipelineError(f"Khong tim thay manifest: {manifest_path}")
            try:
                manifest = json.loads(file_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise StoryPipelineError(f"Manifest JSON khong hop le: {exc}") from exc

        if manifest is None:
            raise StoryPipelineError("Can truyen manifest hoac manifest_path")

        raw_videos = manifest.get("videos") if isinstance(manifest, dict) else None
        if raw_videos is None:
            raw_videos = [manifest]

        created_ids: list[str] = []
        with self._lock:
            for raw_video in raw_videos:
                video = self._build_video_from_manifest(raw_video)
                self._videos[video.id] = video
                created_ids.append(video.id)
                self._active_video_id = video.id
                self._record_event_locked("story.video.created", {"videoId": video.id})

            self._persist_state_locked()

        return [self.get_video_detail(video_id) or {} for video_id in created_ids]

    def import_from_folder(self, payload: dict) -> list[dict]:
        folder_path = str(payload.get("folder_path", "")).strip()
        if not folder_path:
            raise StoryPipelineError("folder_path la bat buoc")

        try:
            videos, diagnostics = xmp_scanner.scan_folder(folder_path)
        except Exception as exc:
            raise StoryPipelineError(f"Quet thu muc that bai: {exc}") from exc

        if not videos:
            raise StoryPipelineError(self._build_xmp_import_error(diagnostics))

        return self.import_manifest({"manifest": {"videos": videos}})

    def _build_xmp_import_error(self, diagnostics: dict) -> str:
        video_count = len(diagnostics.get("video_files", []))
        xmp_count = len(diagnostics.get("xmp_files", []))
        videos_without_markers = diagnostics.get("videos_without_markers", [])
        orphan_xmp_files = diagnostics.get("orphan_xmp_files", [])

        if video_count == 0:
            return (
                "Khong tim thay file video nao trong thu muc nay hoac cac thu muc con. "
                "Hay chon dung thu muc nguon chua clip Premiere."
            )

        message = (
            f"Khong tim thay marker XMP hop le. Da quet {video_count} file video"
            f" va {xmp_count} file .xmp trong ca thu muc con."
        )

        if xmp_count == 0:
            message += " Khong thay sidecar .xmp nao; hay bat 'Write clip markers to XMP' trong Premiere hoac kiem tra marker da duoc ghi nhung vao file."
        else:
            message += " Co file .xmp nhung scanner khong trich xuat duoc marker hop le tu cac file do."

        if not xmp_scanner.exiftool_cmd:
            message += " ExifTool hien khong co san, nen app khong the doc embedded XMP mot cach day du."

        if videos_without_markers:
            preview = ", ".join(videos_without_markers[:3])
            suffix = "..." if len(videos_without_markers) > 3 else ""
            message += f" Video khong co marker: {preview}{suffix}."

        if orphan_xmp_files:
            preview = ", ".join(orphan_xmp_files[:3])
            suffix = "..." if len(orphan_xmp_files) > 3 else ""
            message += f" XMP khong khop ten clip: {preview}{suffix}."

        return message

    def run_video(self, video_id: str) -> dict:
        with self._lock:
            video = self._require_video(video_id)
            if video.status == "completed":
                self._reset_video_for_replay_locked(video)
            elif video.status == "paused":
                video.status = "queued"
                video.last_updated_at = utc_now()
            elif video.status == "running":
                return self._serialize_video_detail(video)
            elif video.status == "review":
                return self._serialize_video_detail(video)
            else:
                video.status = "queued"
                video.last_updated_at = utc_now()

            self._active_video_id = video.id
            self._persist_state_locked()
            self._record_event_locked("story.video.updated", {"videoId": video.id})
            self._enqueue_pending_markers_locked()
            return self._serialize_video_detail(video)

    def pause_video(self, video_id: str) -> dict:
        with self._lock:
            video = self._require_video(video_id)
            if video.status in {"completed", "cancelled"}:
                return self._serialize_video_detail(video)
            video.status = "paused"
            video.last_updated_at = utc_now()
            self._persist_state_locked()
            self._record_event_locked("story.video.updated", {"videoId": video.id})
            return self._serialize_video_detail(video)

    def cancel_video(self, video_id: str) -> dict:
        with self._lock:
            video = self._require_video(video_id)
            if video.status in {"completed", "cancelled"}:
                return self._serialize_video_detail(video)
            video.status = "cancelled"
            video.last_updated_at = utc_now()
            for marker in video.markers:
                if marker.status in {"queued", "running", "paused"}:
                    marker.status = "cancelled"
                for step in marker.steps:
                    if step.status in {"queued", "running", "paused"}:
                        step.status = "cancelled"
            self._persist_state_locked()
            self._record_event_locked("story.video.updated", {"videoId": video.id})
            return self._serialize_video_detail(video)

    def run_all_videos(self) -> dict:
        with self._lock:
            affected_video_ids: list[str] = []
            for video in self._videos.values():
                if video.status in {"completed", "cancelled", "running", "review", "paused"}:
                    continue
                video.status = "queued"
                video.last_updated_at = utc_now()
                affected_video_ids.append(video.id)
                self._record_event_locked("story.video.updated", {"videoId": video.id})

            if affected_video_ids:
                self._active_video_id = affected_video_ids[0]
                self._persist_state_locked()
                self._enqueue_pending_markers_locked()

            return {
                "ok": True,
                "action": "run",
                "affectedVideoIds": affected_video_ids,
                "count": len(affected_video_ids),
            }

    def pause_all_videos(self) -> dict:
        with self._lock:
            affected_video_ids: list[str] = []
            for video in self._videos.values():
                if video.status not in {"queued", "running"}:
                    continue
                video.status = "paused"
                video.last_updated_at = utc_now()
                for marker in video.markers:
                    self._refresh_marker_status_locked(video, marker)
                affected_video_ids.append(video.id)
                self._record_event_locked("story.video.updated", {"videoId": video.id})

            if affected_video_ids:
                self._persist_state_locked()

            return {
                "ok": True,
                "action": "pause",
                "affectedVideoIds": affected_video_ids,
                "count": len(affected_video_ids),
            }

    def resume_all_videos(self) -> dict:
        with self._lock:
            affected_video_ids: list[str] = []
            for video in self._videos.values():
                if video.status != "paused":
                    continue
                video.status = "queued"
                for marker in video.markers:
                    self._refresh_marker_status_locked(video, marker)
                self._refresh_video_status_locked(video)
                affected_video_ids.append(video.id)
                self._record_event_locked("story.video.updated", {"videoId": video.id})

            if affected_video_ids:
                self._active_video_id = affected_video_ids[0]
                self._persist_state_locked()
                self._enqueue_pending_markers_locked()

            return {
                "ok": True,
                "action": "resume",
                "affectedVideoIds": affected_video_ids,
                "count": len(affected_video_ids),
            }

    def cancel_all_videos(self) -> dict:
        with self._lock:
            affected_video_ids: list[str] = []
            for video in self._videos.values():
                if video.status in {"completed", "cancelled"}:
                    continue
                video.status = "cancelled"
                video.last_updated_at = utc_now()
                for marker in video.markers:
                    if marker.status in {"queued", "running", "paused"}:
                        marker.status = "cancelled"
                    for step in marker.steps:
                        if step.status in {"queued", "running", "paused"}:
                            step.status = "cancelled"
                affected_video_ids.append(video.id)
                self._record_event_locked("story.video.updated", {"videoId": video.id})

            if affected_video_ids:
                self._persist_state_locked()

            return {
                "ok": True,
                "action": "cancel",
                "affectedVideoIds": affected_video_ids,
                "count": len(affected_video_ids),
            }

    def apply_action(self, payload: dict) -> dict:
        action = str(payload.get("action", "")).strip().lower()
        video_id = str(payload.get("video_id", "")).strip()
        marker_id = str(payload.get("marker_id", "")).strip()
        step_id = str(payload.get("step_id", "")).strip()
        attempt_id = str(payload.get("attempt_id", "")).strip() or None
        prompt_override = str(payload.get("prompt", "")).strip() or None

        if not action:
            raise StoryPipelineError("action la bat buoc")
        if not video_id:
            raise StoryPipelineError("video_id la bat buoc")

        if action == "run":
            return self.run_video(video_id)
        if action == "pause":
            return self.pause_video(video_id)
        if action == "cancel":
            return self.cancel_video(video_id)

        with self._lock:
            video = self._require_video(video_id)

            if action == "update_video_prompt":
                video.video_prompt = prompt_override or ""
                video.last_updated_at = utc_now()
                self._persist_state_locked()
                self._record_event_locked("story.video.updated", {"videoId": video.id})
                return self._serialize_video_detail(video)

            if action == "update_marker_seed":
                if not marker_id:
                    raise StoryPipelineError("marker_id la bat buoc")
                marker = self._require_marker(video, marker_id)
                marker.seed_prompt = prompt_override or ""
                video.last_updated_at = utc_now()
                self._persist_state_locked()
                self._record_event_locked(
                    "story.step.updated",
                    {"videoId": video.id, "markerId": marker.id},
                )
                return self._serialize_video_detail(video)

            if action == "update_step_prompt":
                if not marker_id or not step_id:
                    raise StoryPipelineError("marker_id va step_id la bat buoc")
                marker = self._require_marker(video, marker_id)
                step = self._require_step(marker, step_id)
                step.modifier_prompt = prompt_override or ""
                video.last_updated_at = utc_now()
                self._persist_state_locked()
                self._record_event_locked(
                    "story.step.updated",
                    {"videoId": video.id, "markerId": marker.id, "stepId": step.id},
                )
                return self._serialize_video_detail(video)

            if not marker_id or not step_id:
                raise StoryPipelineError("marker_id va step_id la bat buoc")

            marker = self._require_marker(video, marker_id)
            step = self._require_step(marker, step_id)

            if action == "accept":
                self._accept_step_attempt_locked(video, marker, step, attempt_id=attempt_id)
                self._persist_state_locked()
                self._record_event_locked("story.step.updated", {"videoId": video.id, "markerId": marker.id, "stepId": step.id})
                self._enqueue_pending_markers_locked()
                return self._serialize_video_detail(video)

            if action == "skip":
                step.status = "skipped"
                step.pending_mode = "auto"
                step.pending_input_path = None
                step.pending_thread_url = None
                step.pending_prompt_override = None
                step.selected_attempt_id = None
                video.status = "queued"
                video.last_updated_at = utc_now()
                self._refresh_marker_status_locked(video, marker)
                self._refresh_video_status_locked(video)
                self._persist_state_locked()
                self._record_event_locked("story.step.updated", {"videoId": video.id, "markerId": marker.id, "stepId": step.id})
                self._enqueue_pending_markers_locked()
                return self._serialize_video_detail(video)

            if action == "retry":
                # Cho phep retry tu ca 'failed' lan 'review' (khong hai long ket qua)
                if step.status not in {"failed", "review"}:
                    raise StoryPipelineError("Chi co the retry step o trang thai failed hoac review")
                latest_attempt = step.attempts[-1] if step.attempts else None
                step.status = "queued"
                step.pending_mode = "retry"
                # Retry dung input goc (input_image_path) de tao lai tu dau, khong dung normalized output
                step.pending_input_path = latest_attempt.input_image_path if latest_attempt else None
                # Retry van su dung cung thread URL de tiep tuc trong cung cuoc hoi thoai
                step.pending_thread_url = latest_attempt.thread_url if latest_attempt else None
                step.pending_prompt_override = None
                marker.status = "queued"
                video.status = "queued"
                video.error = None
                video.last_updated_at = utc_now()
                self._persist_state_locked()
                self._record_event_locked("story.step.updated", {"videoId": video.id, "markerId": marker.id, "stepId": step.id})
                self._enqueue_pending_markers_locked()
                return self._serialize_video_detail(video)

            if action == "regenerate":
                self._queue_regeneration_locked(
                    video,
                    marker,
                    step,
                    action=action,
                    attempt_id=attempt_id,
                    prompt_override=prompt_override,
                )
                self._persist_state_locked()
                self._record_event_locked("story.step.updated", {"videoId": video.id, "markerId": marker.id, "stepId": step.id})
                self._enqueue_pending_markers_locked()
                return self._serialize_video_detail(video)

            if action == "refine":
                self._queue_refine_as_variant_locked(
                    video,
                    marker,
                    step,
                    attempt_id=attempt_id,
                    prompt_override=prompt_override,
                )
                self._persist_state_locked()
                self._record_event_locked("story.video.updated", {"videoId": video.id})
                self._enqueue_pending_markers_locked()
                return self._serialize_video_detail(video)

            raise StoryPipelineError(f"Action khong ho tro: {action}")

    def wait_for_events(self, after_id: int, timeout: float = 15.0) -> list[dict]:
        deadline = datetime.now().timestamp() + timeout
        with self._event_condition:
            while True:
                pending = [event for event in self._event_backlog if int(event["id"]) > after_id]
                if pending:
                    return pending

                remaining = deadline - datetime.now().timestamp()
                if remaining <= 0:
                    return []
                self._event_condition.wait(timeout=remaining)

    def close(self) -> None:
        self._shutdown_event.set()
        for _ in self._workers:
            self._queue.put((-1, ("__shutdown__", "")))
        for worker in self._workers:
            worker.join(timeout=0.5)

    def _restart_workers(self) -> None:
        self._shutdown_event.set()
        for _ in self._workers:
            self._queue.put((-1, ("__shutdown__", "")))
        for worker in self._workers:
            worker.join(timeout=0.5)
        self._shutdown_event.clear()
        self._workers.clear()
        self._start_workers()

    def _start_workers(self) -> None:
        target_workers = max(1, int(self._settings.max_parallel_videos))
        for index in range(target_workers):
            worker = threading.Thread(target=self._worker_loop, name=f"StoryWorker-{index + 1}", daemon=True)
            worker.start()
            self._workers.append(worker)

    def _worker_loop(self) -> None:
        # Đảm bảo thread worker không có asyncio loop running để tránh conflict với Playwright Sync API
        try:
            asyncio.set_event_loop(None)
        except Exception:
            pass

        while not self._shutdown_event.is_set():
            try:
                priority, task_data = self._queue.get(timeout=0.5)
            except Empty:
                continue

            try:
                video_id, marker_id = task_data
                if video_id == "__shutdown__":
                    return
                self._process_marker(video_id, marker_id)
            finally:
                self._queue.task_done()

    def _process_marker(self, video_id: str, marker_id: str) -> None:
        """Xử lý một marker cụ thể trong một worker thread / một browser tab."""
        with self._lock:
            self._queued_marker_ids.discard(marker_id)
            video = self._videos.get(video_id)
            if video is None:
                return
            if video.status in {"paused"}:
                return

            marker = next((m for m in video.markers if m.id == marker_id), None)
            if marker is None:
                return
            if marker.status in {"completed", "skipped"}:
                return

            step = self._next_step_in_marker_locked(marker)
            if step is None:
                # Không có step nào cần xử lý, cập nhật trạng thái
                self._refresh_marker_status_locked(video, marker)
                self._refresh_video_status_locked(video)
                self._persist_state_locked()
                self._record_event_locked("story.video.updated", {"videoId": video.id})
                return

            marker.status = "running"
            step.status = "running"
            mode = step.pending_mode or "auto"
            input_path = step.pending_input_path or self._resolve_step_input_locked(video, marker, step)
            prompt = (step.pending_prompt_override or "").strip() or self._merge_prompt(video, marker, step)

            attempt = StoryAttempt(
                id=f"att-{uuid.uuid4().hex[:10]}",
                index=len(step.attempts) + 1,
                mode=mode,
                status="running",
                prompt=prompt,
                input_image_path=input_path,
                thread_url=step.pending_thread_url,
                started_at=utc_now(),
            )
            step.attempts.append(attempt)
            step.pending_mode = "auto"
            step.pending_input_path = None
            step.pending_thread_url = None
            step.pending_prompt_override = None
            video.status = "running"
            video.last_updated_at = utc_now()
            self._active_video_id = video.id
            self._persist_state_locked()
            self._record_event_locked(
                "story.attempt.started",
                {"videoId": video.id, "markerId": marker.id, "stepId": step.id, "attemptId": attempt.id},
            )

        try:
            result = self._run_generation(video, marker, step, attempt)
        except Exception as exc:
            with self._lock:
                attempt.status = "failed"
                attempt.error = str(exc)
                attempt.completed_at = utc_now()
                step.status = "failed"
                marker.status = "failed"
                # Không đặt video thành failed nếu các marker khác vẫn đang chạy
                self._refresh_video_status_locked(video)
                video.error = str(exc)
                video.last_updated_at = utc_now()
                self._persist_state_locked()
                self._record_event_locked(
                    "story.attempt.failed",
                    {"videoId": video.id, "markerId": marker.id, "stepId": step.id, "attemptId": attempt.id},
                )
            return

        with self._lock:
            attempt.status = "review"
            attempt.thread_url = result.thread_url or attempt.thread_url
            attempt.preview_path = result.preview_path
            attempt.normalized_path = result.normalized_path
            attempt.completed_at = utc_now()
            step.status = "review"
            marker.status = "review"
            # Cập nhật video status: có thể có marker khác vẫn đang running
            self._refresh_video_status_locked(video)
            video.error = None
            video.last_updated_at = utc_now()
            self._persist_state_locked()
            self._record_event_locked(
                "story.attempt.review",
                {"videoId": video.id, "markerId": marker.id, "stepId": step.id, "attemptId": attempt.id},
            )
            self._enqueue_pending_markers_locked()

    def _run_generation(
        self,
        video: StoryVideo,
        marker: StoryMarker,
        step: StoryStep,
        attempt: StoryAttempt,
    ) -> GenerationResult:
        attempt_dir = self._attempt_cache_dir(video, marker, step, attempt.index)
        preview_path = attempt_dir / "preview.jpg"
        normalized_path = attempt_dir / "normalized.jpg"

        return self._adapter.generate(
            prompt=attempt.prompt,
            input_image_path=Path(attempt.input_image_path),
            preview_path=preview_path,
            normalized_path=normalized_path,
            context={
                "videoId": video.id,
                "markerId": marker.id,
                "stepId": step.id,
                "attemptId": attempt.id,
                "mode": attempt.mode,
                "threadUrl": attempt.thread_url,
                "videoMode": video.mode,
                "geminiModel": self._settings.gemini_model,
            },
        )

    def _attempt_cache_dir(
        self,
        video: StoryVideo,
        marker: StoryMarker,
        step: StoryStep,
        attempt_index: int,
    ) -> Path:
        variant_suffix = "" if marker.variant_index <= 0 else f"_v{marker.variant_index}"
        return (
            story_generated_root()
            / video.id
            / f"marker_{marker.index:03d}{variant_suffix}"
            / f"step_{step.index:02d}"
            / f"attempt_{attempt_index:02d}"
        )

    def _build_attempt_stem(
        self,
        video: StoryVideo,
        marker: StoryMarker,
        step: StoryStep,
        attempt_index: int,
    ) -> str:
        source_name = video.name or video.source_video_path or video.id
        video_stem = sanitize_file_stem(Path(source_name).stem) or sanitize_file_stem(video.id)
        return f"{video_stem}.m{marker.index}s{step.index}v{marker.variant_index}"

    def _next_step_to_generate_locked(self, video: StoryVideo) -> tuple[StoryMarker, StoryStep] | None:
        # Uu tien variant markers (refine) - chay doc lap, khong bi block boi root
        for marker in sorted(video.markers, key=lambda item: (item.index, item.variant_index)):
            if marker.parent_marker_id is None:
                continue  # Bo qua root marker o buoc nay
            for step in sorted(marker.steps, key=lambda item: item.index):
                if step.status == "review":
                    return None
                if step.status in {"queued", "failed"}:
                    return marker, step

        # Sau do xu ly root markers
        for marker in sorted(video.markers, key=lambda item: item.index):
            if marker.parent_marker_id is not None:
                continue  # Bo qua variant marker
            for step in sorted(marker.steps, key=lambda item: item.index):
                if step.status == "review":
                    return None
                if step.status in {"queued", "failed"}:
                    return marker, step
        return None

    def _next_step_in_marker_locked(self, marker: StoryMarker) -> StoryStep | None:
        """
        Tìm step tiếp theo cần xử lý trong một marker cụ thể.
        - Nếu gặp step đang "review" → dừng, đợi user duyệt.
        - Nếu gặp step "queued" hoặc "failed" → trả về step đó.
        - Không còn step nào → trả về None.
        """
        for step in step_order(marker.steps):
            if step.status == "review":
                return None  # Dừng lại, đợi user accept/skip
            if step.status in {"queued", "failed"}:
                return step
        return None

    def _resolve_step_input_locked(self, video: StoryVideo, marker: StoryMarker, step: StoryStep) -> str:
        if video.mode == "from_source" or step.index <= 1:
            return marker.input_frame_path

        prev_step_index = step.index - 1
        previous_step = next((candidate for candidate in marker.steps if candidate.index == prev_step_index), None)
        if previous_step is None:
            return marker.input_frame_path

        if previous_step.selected_attempt_id:
            accepted = next(
                (attempt for attempt in previous_step.attempts if attempt.id == previous_step.selected_attempt_id),
                None,
            )
            if accepted and accepted.normalized_path:
                return accepted.normalized_path

        if previous_step.attempts and previous_step.attempts[-1].normalized_path:
            return previous_step.attempts[-1].normalized_path or marker.input_frame_path

        return marker.input_frame_path

    def _queue_regeneration_locked(
        self,
        video: StoryVideo,
        marker: StoryMarker,
        step: StoryStep,
        *,
        action: str,
        attempt_id: str | None,
        prompt_override: str | None,
    ) -> None:
        """Tạo lại (Regenerate) giờ đây sẽ tạo ra một Variant mới thay vì ghi đè."""
        if step.status not in {"review", "failed", "completed"}:
            raise StoryPipelineError("Step khong o trang thai review, failed hoac completed de regenerate")
        
        if not step.attempts:
            raise StoryPipelineError("Step chua co attempt")

        selected_attempt = self._pick_attempt(step, attempt_id)
        
        # Logic giong refine cu: Tao mot marker variant moi
        parent_id = marker.parent_marker_id or marker.id
        existing_variants = [m for m in video.markers if m.parent_marker_id == parent_id or m.id == parent_id]
        new_variant_index = max(m.variant_index for m in existing_variants) + 1

        import copy
        new_steps = []
        target_new_step = None
        for s in marker.steps:
            new_s = StoryStep(
                id=f"step-{uuid.uuid4().hex[:10]}",
                index=s.index,
                title=s.title,
                modifier_prompt=s.modifier_prompt,
                status=s.status if s.id != step.id else "queued",
                selected_attempt_id=s.selected_attempt_id if s.id != step.id else None,
                pending_mode=action if s.id == step.id else s.pending_mode,
                pending_input_path=selected_attempt.input_image_path if s.id == step.id else s.pending_input_path,
                pending_thread_url=selected_attempt.thread_url if s.id == step.id else s.pending_thread_url,
            )
            if s.id != step.id:
                new_s.attempts = copy.deepcopy(s.attempts)
            else:
                new_s.attempts = []
                target_new_step = new_s
            new_steps.append(new_s)

        new_marker = StoryMarker(
            id=f"marker-{uuid.uuid4().hex[:10]}",
            index=marker.index,
            label=marker.label,
            timestamp_ms=marker.timestamp_ms,
            input_frame_path=marker.input_frame_path,
            seed_prompt=marker.seed_prompt,
            status="queued",
            steps=new_steps,
            parent_marker_id=parent_id,
            variant_index=new_variant_index,
        )
        video.markers.append(new_marker)
        video.status = "running"
        video.last_updated_at = utc_now()

    def _queue_refine_as_variant_locked(
        self,
        video: StoryVideo,
        marker: StoryMarker,
        step: StoryStep,
        *,
        attempt_id: str | None,
        prompt_override: str | None,
    ) -> None:
        """Tinh chỉnh (Refine) giờ đây sẽ thêm một Step mới vào Marker hiện tại."""
        if step.status not in {"review", "failed", "completed"}:
            raise StoryPipelineError("Step khong o trang thai review, failed hoac completed de refine")
        if not step.attempts:
            raise StoryPipelineError("Step chua co attempt")
        if not prompt_override:
            raise StoryPipelineError("Refine bat buoc phai nhap prompt rieng.")

        selected_attempt = self._pick_attempt(step, attempt_id)
        
        # Tao step moi noi tiep vao danh sach steps cua marker hien tai
        new_step_index = max(s.index for s in marker.steps) + 1
        new_step = StoryStep(
            id=f"step-{uuid.uuid4().hex[:10]}",
            index=new_step_index,
            title=f"Tinh chỉnh {step.index}",
            modifier_prompt=prompt_override,
            status="queued",
            pending_mode="refine",
            pending_input_path=selected_attempt.normalized_path or selected_attempt.preview_path,
            pending_thread_url=None, # Ep mo thread moi thay vi dung tiep thread cu
            pending_prompt_override=prompt_override,
        )
        
        marker.steps.append(new_step)
        marker.status = "queued"
        video.status = "running"
        video.last_updated_at = utc_now()

    def _accept_step_attempt_locked(
        self,
        video: StoryVideo,
        marker: StoryMarker,
        step: StoryStep,
        *,
        attempt_id: str | None,
    ) -> None:
        if step.status not in {"review", "failed", "completed"}:
            raise StoryPipelineError("Step khong o trang thai review, failed hoac completed de accept")
        if not step.attempts:
            raise StoryPipelineError("Step chua co attempt")

        chosen = self._pick_attempt(step, attempt_id)
        if not chosen.preview_path and not chosen.normalized_path:
            raise StoryPipelineError("Attempt chua co output")

        # Copy anh vao thu muc persistent de tranh bi xoa khi restart app
        self._persist_accepted_image_locked(video, marker, step, chosen)

        chosen.status = "accepted"
        step.selected_attempt_id = chosen.id
        step.status = "completed"
        step.pending_mode = "auto"
        step.pending_input_path = None
        step.pending_thread_url = None
        step.pending_prompt_override = None
        marker.status = "completed" if all(candidate.status in {"completed", "skipped"} for candidate in marker.steps) else "queued"
        video.status = "completed" if self._video_all_steps_done(video) else "running"
        video.last_updated_at = utc_now()

        if video.status == "completed":
            self._active_video_id = video.id
        
        self._enqueue_pending_markers_locked()

    def _persist_accepted_image_locked(
        self,
        video: StoryVideo,
        marker: StoryMarker,
        step: StoryStep,
        attempt: StoryAttempt,
    ) -> None:
        """Copy anh duoc accept vao story_accepted_root() de giu sau khi restart."""
        source_raw = attempt.normalized_path or attempt.preview_path
        if not source_raw:
            return
        source = Path(source_raw)
        if not source.exists():
            return

        accepted_dir = story_accepted_root() / video.id
        accepted_dir.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix or ".jpg"
        stem = self._build_attempt_stem(video, marker, step, attempt.index)
        dest = accepted_dir / f"{stem}{suffix}"
        if not dest.exists():
            try:
                shutil.copy2(source, dest)
            except OSError:
                return  # Neu copy that bai, giu nguyen duong dan cu

        # Cap nhat duong dan tren attempt de export luon tim duoc file
        attempt.normalized_path = str(dest)
        attempt.preview_path = str(dest)

    def _pick_attempt(self, step: StoryStep, attempt_id: str | None) -> StoryAttempt:
        if attempt_id:
            for candidate in step.attempts:
                if candidate.id == attempt_id:
                    return candidate
            raise StoryPipelineError(f"Khong tim thay attempt {attempt_id}")

        return step.attempts[-1]

    def _video_all_steps_done(self, video: StoryVideo) -> bool:
        # Chi kiem tra root markers, variant (refine) la tuy chon
        for marker in video.markers:
            if marker.parent_marker_id is not None:
                continue  # Bo qua variant marker
            for step in marker.steps:
                if step.status not in {"completed", "skipped"}:
                    return False
        return True

    def _refresh_marker_status_locked(self, video: StoryVideo, marker: StoryMarker) -> None:
        if all(step.status in {"completed", "skipped"} for step in marker.steps):
            marker.status = "completed"
            return
        if any(step.status == "review" for step in marker.steps):
            marker.status = "review"
            return
        if any(step.status == "running" for step in marker.steps):
            marker.status = "running"
            return
        if video.status == "paused":
            marker.status = "paused"
            return
        marker.status = "queued"

    def _refresh_video_status_locked(self, video: StoryVideo) -> None:
        if self._video_all_steps_done(video):
            video.status = "completed"
        elif any(marker.status == "running" for marker in video.markers):
            # Ít nhất 1 marker đang chạy → video vẫn là "running"
            video.status = "running"
        elif any(
            step.status == "review"
            for marker in video.markers
            if marker.parent_marker_id is None
            for step in marker.steps
        ):
            video.status = "review"
        elif video.status != "paused":
            video.status = "queued"
        video.last_updated_at = utc_now()

    def _reset_video_for_replay_locked(self, video: StoryVideo) -> None:
        for marker in video.markers:
            marker.status = "queued"
            for step in marker.steps:
                step.status = "queued"
                step.selected_attempt_id = None
                step.pending_mode = "auto"
                step.pending_input_path = None
                step.pending_thread_url = None
                step.attempts = []
        video.status = "queued"
        video.error = None
        video.last_updated_at = utc_now()

    def _build_video_from_manifest(self, raw_video: dict) -> StoryVideo:
        if not isinstance(raw_video, dict):
            raise StoryPipelineError("Moi video trong manifest phai la object")

        name = str(raw_video.get("video_name") or raw_video.get("name") or "Untitled Video").strip() or "Untitled Video"
        source_video_path = str(raw_video.get("video_path") or raw_video.get("source_video_path") or "").strip()
        mode = str(raw_video.get("mode") or "chain").strip().lower()
        if mode not in {"chain", "from_source"}:
            raise StoryPipelineError("mode chi duoc la 'chain' hoac 'from_source'")

        raw_markers = raw_video.get("markers")
        if not isinstance(raw_markers, list) or not raw_markers:
            raise StoryPipelineError("Manifest can co danh sach markers")

        markers: list[StoryMarker] = []
        for marker_index, raw_marker in enumerate(raw_markers, start=1):
            if not isinstance(raw_marker, dict):
                raise StoryPipelineError("Marker khong hop le")

            label = str(raw_marker.get("name") or raw_marker.get("label") or f"Marker {marker_index}").strip() or f"Marker {marker_index}"
            timestamp_ms = self._parse_timestamp_ms(raw_marker.get("timestamp_ms", raw_marker.get("timestamp", 0)))
            input_frame_path = str(
                raw_marker.get("input_frame")
                or raw_marker.get("input_frame_path")
                or raw_marker.get("frame_path")
                or ""
            ).strip()
            if not input_frame_path:
                raise StoryPipelineError(f"Marker '{label}' chua co input_frame")

            marker_comment = str(raw_marker.get("comment") or "").strip()
            seed_prompt = str(raw_marker.get("seed_prompt") or raw_marker.get("seed") or label).strip()
            raw_steps = raw_marker.get("steps") or raw_marker.get("story_steps") or []
            if not isinstance(raw_steps, list):
                raise StoryPipelineError("steps cua marker phai la array")
            if not raw_steps:
                raw_steps = [{"title": label, "modifier_prompt": marker_comment}]

            steps: list[StoryStep] = []
            for step_index, raw_step in enumerate(raw_steps, start=1):
                if isinstance(raw_step, str):
                    title = raw_step.strip() or f"Step {step_index}"
                    modifier_prompt = ""
                elif isinstance(raw_step, dict):
                    title = str(raw_step.get("title") or raw_step.get("name") or f"Step {step_index}").strip() or f"Step {step_index}"
                    modifier_prompt = str(raw_step.get("modifier_prompt") or raw_step.get("prompt") or "").strip()
                else:
                    raise StoryPipelineError("Step khong hop le")

                steps.append(
                    StoryStep(
                        id=f"step-{uuid.uuid4().hex[:10]}",
                        index=step_index,
                        title=title,
                        modifier_prompt=modifier_prompt,
                    )
                )

            markers.append(
                StoryMarker(
                    id=f"marker-{uuid.uuid4().hex[:10]}",
                    index=marker_index,
                    label=label,
                    timestamp_ms=timestamp_ms,
                    input_frame_path=input_frame_path,
                    seed_prompt=seed_prompt,
                    steps=steps,
                )
            )

        # Dung deterministic ID dua tren source_video_path de tranh duplicate khi quet lai
        import hashlib
        video_id_seed = source_video_path or name
        video_id = f"video-{hashlib.md5(video_id_seed.encode('utf-8')).hexdigest()[:12]}"

        now = utc_now()
        return StoryVideo(
            id=video_id,
            name=name,
            source_video_path=source_video_path,
            mode=mode,
            video_prompt=str(raw_video.get("video_prompt") or "").strip(),
            status="ready",
            created_at=now,
            last_updated_at=now,
            markers=markers,
        )

    def _merge_prompt(self, video: StoryVideo, marker: StoryMarker, step: StoryStep) -> str:
        parts = [
            self._global_prompt.strip(),
            video.video_prompt.strip(),
            step.modifier_prompt.strip(),
        ]
        return "\n\n".join(part for part in parts if part)

    def _parse_timestamp_ms(self, raw_value: object) -> int:
        if isinstance(raw_value, int):
            return max(0, raw_value)

        if isinstance(raw_value, float):
            if raw_value.is_integer():
                return max(0, int(raw_value))
            return max(0, int(raw_value * 1000))

        value = str(raw_value or "").strip()
        if not value:
            return 0

        if value.isdigit():
            return int(value)

        segments = value.split(":")
        try:
            numeric = [float(segment) for segment in segments]
        except ValueError:
            raise StoryPipelineError(f"timestamp khong hop le: {raw_value}")

        seconds = 0.0
        for number in numeric:
            seconds = seconds * 60 + number
        return int(seconds * 1000)

    def _require_video(self, video_id: str) -> StoryVideo:
        video = self._videos.get(video_id)
        if video is None:
            raise StoryPipelineError(f"Khong tim thay video: {video_id}")
        return video

    def _require_marker(self, video: StoryVideo, marker_id: str) -> StoryMarker:
        marker = next((item for item in video.markers if item.id == marker_id), None)
        if marker is None:
            raise StoryPipelineError(f"Khong tim thay marker: {marker_id}")
        return marker

    def _require_step(self, marker: StoryMarker, step_id: str) -> StoryStep:
        step = next((item for item in marker.steps if item.id == step_id), None)
        if step is None:
            raise StoryPipelineError(f"Khong tim thay step: {step_id}")
        return step

    def _serialize_video_summary(self, video: StoryVideo) -> dict:
        step_total = sum(len(marker.steps) for marker in video.markers)
        completed_steps = sum(
            1
            for marker in video.markers
            for step in marker.steps
            if step.status in {"completed", "skipped"}
        )
        review_steps = sum(
            1
            for marker in video.markers
            for step in marker.steps
            if step.status == "review"
        )

        # Tim anh review/accepted moi nhat de lam thumbnail cho video list
        result_preview_path = None
        for marker in reversed(video.markers):
            for step in reversed(marker.steps):
                if step.selected_attempt_id:
                    chosen = next((a for a in step.attempts if a.id == step.selected_attempt_id), None)
                    if chosen and (chosen.preview_path or chosen.normalized_path):
                        result_preview_path = chosen.normalized_path or chosen.preview_path
                        break
                elif step.status == "review" and step.attempts:
                    latest = step.attempts[-1]
                    if latest.preview_path or latest.normalized_path:
                        result_preview_path = latest.normalized_path or latest.preview_path
                        break
            if result_preview_path:
                break

        # Tim tat ca cac anh da duoc duyet de hien thi trong gallery
        accepted_steps_info = []
        for marker in video.markers:
            for step in marker.steps:
                if step.status == "completed" and step.selected_attempt_id:
                    attempt = next((a for a in step.attempts if a.id == step.selected_attempt_id), None)
                    if attempt and (attempt.normalized_path or attempt.preview_path):
                        accepted_steps_info.append({
                            "videoId": video.id,
                            "videoName": video.name,
                            "markerIndex": marker.index,
                            "stepId": step.id,
                            "stepIndex": step.index,
                            "previewPath": attempt.normalized_path or attempt.preview_path,
                            "stepTitle": step.title
                        })

        return {
            "id": video.id,
            "name": video.name,
            "status": video.status,
            "sourceVideoPath": video.source_video_path,
            "createdAt": video.created_at,
            "lastUpdatedAt": video.last_updated_at,
            "markerCount": len(video.markers),
            "stepTotal": sum(len(m.steps) for m in video.markers),
            "completedSteps": video.completed_steps,
            "reviewSteps": video.review_steps,
            "previewPath": video.markers[0].input_frame_path if video.markers else None,
            "resultPreviewPath": result_preview_path,
            "acceptedSteps": accepted_steps_info,
            "error": video.error,
        }

    def _serialize_video_detail(self, video: StoryVideo) -> dict:
        return {
            **self._serialize_video_summary(video),
            "videoPrompt": video.video_prompt,
            "markers": [
                {
                    "id": marker.id,
                    "index": marker.index,
                    "label": marker.label,
                    "timestampMs": marker.timestamp_ms,
                    "inputFramePath": marker.input_frame_path,
                    "seedPrompt": marker.seed_prompt,
                    "status": marker.status,
                    "parentMarkerId": marker.parent_marker_id,
                    "variantIndex": marker.variant_index,
                    "steps": [
                        {
                            "id": step.id,
                            "index": step.index,
                            "title": step.title,
                            "modifierPrompt": step.modifier_prompt,
                            "status": step.status,
                            "selectedAttemptId": step.selected_attempt_id,
                            "attempts": [
                                {
                                    "id": attempt.id,
                                    "index": attempt.index,
                                    "mode": attempt.mode,
                                    "status": attempt.status,
                                    "prompt": attempt.prompt,
                                    "inputImagePath": attempt.input_image_path,
                                    "threadUrl": attempt.thread_url,
                                    "previewPath": attempt.preview_path,
                                    "normalizedPath": attempt.normalized_path,
                                    "error": attempt.error,
                                    "startedAt": attempt.started_at,
                                    "completedAt": attempt.completed_at,
                                }
                                for attempt in step.attempts
                            ],
                        }
                        for step in step_order(marker.steps)
                    ],
                }
                for marker in marker_order(video.markers)
            ],
        }

    def _load_state(self) -> None:
        if not self._state_file.exists():
            return

        try:
            raw = json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception:
            return

        settings = raw.get("settings") if isinstance(raw, dict) else None
        if isinstance(settings, dict):
            try:
                self._settings = StorySettings(
                    output_root=str(settings.get("output_root", self._settings.output_root)),
                    max_parallel_videos=max(1, min(8, int(settings.get("max_parallel_videos", self._settings.max_parallel_videos)))),
                    generation_backend=str(
                        settings.get("generation_backend", self._settings.generation_backend)
                    ).strip().lower() or self._settings.generation_backend,
                    gemini_headless=_bool_value(
                        settings.get("gemini_headless", self._settings.gemini_headless),
                        default=self._settings.gemini_headless,
                    ),
                    gemini_base_url=str(settings.get("gemini_base_url", self._settings.gemini_base_url)).strip()
                    or self._settings.gemini_base_url,
                    gemini_response_timeout_ms=max(
                        20_000,
                        min(
                            300_000,
                            int(
                                settings.get(
                                    "gemini_response_timeout_ms",
                                    self._settings.gemini_response_timeout_ms,
                                )
                            ),
                        ),
                    ),
                    gemini_model=str(settings.get("gemini_model", self._settings.gemini_model)).strip()
                    or self._settings.gemini_model,
                )
                # Always force gemini_web as requested by user
                self._settings.generation_backend = "gemini_web"
            except (TypeError, ValueError):
                pass

        self._global_prompt = str(raw.get("global_prompt", "")).strip() if isinstance(raw, dict) else ""

        self._global_prompt = str(raw.get("global_prompt", "")).strip() if isinstance(raw, dict) else ""

        # Load video state
        self._videos = {}
        serialized_videos = raw.get("videos", []) if isinstance(raw, dict) else []
        if isinstance(serialized_videos, list):
            for video_dict in serialized_videos:
                try:
                    video = self._deserialize_video_state(video_dict)
                    self._videos[video.id] = video
                except Exception:
                    # Skip corrupted video entries
                    pass

        active_video_id = str(raw.get("active_video_id", "")).strip() if isinstance(raw, dict) else None
        if active_video_id and active_video_id in self._videos:
            self._active_video_id = active_video_id
        elif self._videos:
            self._active_video_id = list(self._videos.keys())[0]
        else:
            self._active_video_id = None

    def _persist_state_locked(self) -> None:
        payload = {
            "settings": asdict(self._settings),
            "global_prompt": self._global_prompt,
            "active_video_id": self._active_video_id,
            "videos": [self._serialize_video_state(video) for video in self._videos.values()],
        }

        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _reset_runtime_state_for_restart(self) -> None:
        if not self._videos:
            return

        self._queued_video_ids.clear()
        interruption_message = "Tien trinh bi gian doan khi khoi dong lai ung dung."

        for video in self._videos.values():
            for marker in marker_order(video.markers):
                for step in step_order(marker.steps):
                    for attempt in step.attempts:
                        if attempt.status == "running":
                            attempt.status = "failed"
                            attempt.error = attempt.error or interruption_message
                            attempt.completed_at = attempt.completed_at or utc_now()

                    if step.status == "running":
                        latest_attempt = step.attempts[-1] if step.attempts else None
                        if latest_attempt and (latest_attempt.preview_path or latest_attempt.normalized_path):
                            step.status = "review"
                        elif latest_attempt is not None:
                            step.status = "failed"
                        else:
                            step.status = "queued"

                self._refresh_marker_status_locked(video, marker)

            if video.status == "running":
                video.status = "queued"
            self._refresh_video_status_locked(video)

        if self._active_video_id not in self._videos:
            self._active_video_id = next(iter(self._videos), None)

        self._persist_state_locked()

    def _serialize_video_state(self, video: StoryVideo) -> dict:
        return {
            "id": video.id,
            "name": video.name,
            "source_video_path": video.source_video_path,
            "mode": video.mode,
            "video_prompt": video.video_prompt,
            "status": video.status,
            "created_at": video.created_at,
            "last_updated_at": video.last_updated_at,
            "error": video.error,
            "markers": [
                {
                    "id": marker.id,
                    "index": marker.index,
                    "label": marker.label,
                    "timestamp_ms": marker.timestamp_ms,
                    "input_frame_path": marker.input_frame_path,
                    "seed_prompt": marker.seed_prompt,
                    "status": marker.status,
                    "parent_marker_id": marker.parent_marker_id,
                    "variant_index": marker.variant_index,
                    "steps": [
                        {
                            "id": step.id,
                            "index": step.index,
                            "title": step.title,
                            "modifier_prompt": step.modifier_prompt,
                            "status": step.status,
                            "selected_attempt_id": step.selected_attempt_id,
                            "pending_mode": step.pending_mode,
                            "pending_input_path": step.pending_input_path,
                            "pending_thread_url": step.pending_thread_url,
                            "pending_prompt_override": step.pending_prompt_override,
                            "attempts": [
                                {
                                    "id": attempt.id,
                                    "index": attempt.index,
                                    "mode": attempt.mode,
                                    "status": attempt.status,
                                    "prompt": attempt.prompt,
                                    "input_image_path": attempt.input_image_path,
                                    "thread_url": attempt.thread_url,
                                    "preview_path": attempt.preview_path,
                                    "normalized_path": attempt.normalized_path,
                                    "error": attempt.error,
                                    "started_at": attempt.started_at,
                                    "completed_at": attempt.completed_at,
                                }
                                for attempt in step.attempts
                            ],
                        }
                        for step in step_order(marker.steps)
                    ],
                }
                for marker in marker_order(video.markers)
            ],
        }

    def _deserialize_video(self, data: dict) -> StoryVideo:
        markers: list[StoryMarker] = []
        for marker_data in data.get("markers", []):
            steps: list[StoryStep] = []
            for step_data in marker_data.get("steps", []):
                attempts = [
                    StoryAttempt(
                        id=str(attempt_data.get("id")),
                        index=int(attempt_data.get("index", 1)),
                        mode=str(attempt_data.get("mode", "auto")),
                        status=str(attempt_data.get("status", "queued")),
                        prompt=str(attempt_data.get("prompt", "")),
                        input_image_path=str(attempt_data.get("input_image_path", "")),
                        thread_url=_optional_str(attempt_data.get("thread_url")),
                        preview_path=_optional_str(attempt_data.get("preview_path")),
                        normalized_path=_optional_str(attempt_data.get("normalized_path")),
                        error=_optional_str(attempt_data.get("error")),
                        started_at=_optional_str(attempt_data.get("started_at")),
                        completed_at=_optional_str(attempt_data.get("completed_at")),
                    )
                    for attempt_data in step_data.get("attempts", [])
                    if isinstance(attempt_data, dict)
                ]

                steps.append(
                    StoryStep(
                        id=str(step_data.get("id")),
                        index=int(step_data.get("index", 1)),
                        title=str(step_data.get("title", "Step")),
                        modifier_prompt=str(step_data.get("modifier_prompt", "")),
                        status=str(step_data.get("status", "queued")),
                        selected_attempt_id=_optional_str(step_data.get("selected_attempt_id")),
                        pending_mode=str(step_data.get("pending_mode", "auto")),
                        pending_input_path=_optional_str(step_data.get("pending_input_path")),
                        pending_thread_url=_optional_str(step_data.get("pending_thread_url")),
                        pending_prompt_override=_optional_str(step_data.get("pending_prompt_override")),
                        attempts=attempts,
                    )
                )

            markers.append(
                StoryMarker(
                    id=str(marker_data.get("id")),
                    index=int(marker_data.get("index", 1)),
                    label=str(marker_data.get("label", "Marker")),
                    timestamp_ms=int(marker_data.get("timestamp_ms", 0)),
                    input_frame_path=str(marker_data.get("input_frame_path", "")),
                    seed_prompt=str(marker_data.get("seed_prompt", "")),
                    status=str(marker_data.get("status", "queued")),
                    steps=steps,
                    parent_marker_id=_optional_str(marker_data.get("parent_marker_id")),
                    variant_index=int(marker_data.get("variant_index", 0)),
                )
            )

        return StoryVideo(
            id=str(data.get("id")),
            name=str(data.get("name", "Untitled Video")),
            source_video_path=str(data.get("source_video_path", "")),
            mode=str(data.get("mode", "chain")),
            video_prompt=str(data.get("video_prompt", "")),
            status=str(data.get("status", "queued")),
            created_at=str(data.get("created_at", utc_now())),
            last_updated_at=str(data.get("last_updated_at", utc_now())),
            error=_optional_str(data.get("error")),
            markers=markers,
        )

    def _record_event_locked(self, event_type: str, payload: dict) -> None:
        self._event_sequence += 1
        event = {
            "id": self._event_sequence,
            "type": event_type,
            "timestamp": utc_now(),
            **payload,
        }
        self._event_backlog.append(event)
        if len(self._event_backlog) > MAX_EVENT_BACKLOG:
            self._event_backlog = self._event_backlog[-MAX_EVENT_BACKLOG:]

        with self._event_condition:
            self._event_condition.notify_all()

    def _enqueue_pending_markers_locked(self) -> None:
        """
        Đưa từng marker pending của tất cả video đang queued/running vào queue.
        Mỗi marker = 1 queue item = 1 worker thread = 1 browser tab.
        Luôn ưu tiên (priority=0) cho:
          - Variant markers (refine)
          - Markers có step đang retry/regenerate
          - Markers có step bị failed cần xử lý lại
        """
        pending_items = []
        for video in self._videos.values():
            if video.status not in {"queued", "running"}:
                continue
            for marker in marker_order(video.markers):
                if marker.id in self._queued_marker_ids:
                    continue
                if marker.status in {"completed", "review", "skipped"}:
                    continue
                # Marker có step đang chờ xử lý (queued hoặc failed)
                has_pending = any(step.status in {"queued", "failed"} for step in marker.steps)
                if not has_pending:
                    continue

                # Xác định mức ưu tiên:
                # priority 0 = cao nhất (refine/retry/failed)
                # priority 1 = thường (auto gen mới)
                is_priority = (
                    marker.parent_marker_id is not None  # Variant marker từ refine
                    or marker.status == "failed"          # Marker thất bại
                    or any(
                        step.pending_mode in {"refine", "retry", "regenerate"}
                        or step.status == "failed"
                        for step in marker.steps
                    )
                )
                priority = 0 if is_priority else 1
                pending_items.append((priority, video.id, marker))

        # Sắp xếp: priority tăng dần (0 trước), sau đó theo index và variant_index
        pending_items.sort(key=lambda item: (item[0], item[2].index, item[2].variant_index))

        for priority, video_id, marker in pending_items:
            self._queued_marker_ids.add(marker.id)
            self._queue.put((priority, (video_id, marker.id)))

    def _refresh_adapter_locked(self) -> None:
        if self._injected_adapter is not None:
            self._adapter = self._injected_adapter
            return

        # Shutdown browser window cũ trước khi tạo adapter mới
        if hasattr(self._adapter, "shutdown"):
            try:
                self._adapter.shutdown()
            except Exception:
                pass

        if True: # Always use gemini_web
            runtime_root = story_gemini_runtime_root()
            runtime_root.mkdir(parents=True, exist_ok=True)
            self._adapter = GeminiWebAdapter(
                runtime_root=runtime_root,
                headless=self._settings.gemini_headless,
                base_url=self._settings.gemini_base_url,
                response_timeout_ms=self._settings.gemini_response_timeout_ms,
                model_name=self._settings.gemini_model,
                debug_selector=True,
                debug_root=story_debug_root(),
                max_tabs=self._settings.max_parallel_videos,
            )
            return

        pass # LocalPreviewAdapter removed

    def _invalidate_session_status_cache_locked(self) -> None:
        self._session_status_cache = None
        self._session_status_cache_time = 0.0


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool_value(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _copy_with_unique_name(source: Path, destination_dir: Path, preferred_name: str) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / preferred_name
    if not target.exists():
        shutil.copy2(source, target)
        return target

    stem = target.stem
    suffix = target.suffix
    counter = 2
    while True:
        candidate = destination_dir / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            shutil.copy2(source, candidate)
            return candidate
        counter += 1


def marker_order(items: list[StoryMarker]) -> list[StoryMarker]:
    return sorted(items, key=lambda item: (item.index, item.variant_index))


def step_order(items: list[StoryStep]) -> list[StoryStep]:
    return sorted(items, key=lambda item: item.index)


story_pipeline = StoryPipelineManager()
