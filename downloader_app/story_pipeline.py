from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Protocol

from downloader_app.gemini_web_adapter import (
    GEMINI_DEFAULT_URL,
    GeminiWebAdapter,
    GeminiWebError,
    check_gemini_session,
    open_gemini_login_window,
)
from downloader_app.jobs import sanitize_file_stem
from downloader_app.runtime import app_path
from downloader_app.xmp_scanner import xmp_scanner


STORY_STATE_FILE = app_path("story_pipeline_state.json")
STORY_OUTPUT_ROOT = app_path("story_pipeline")
MAX_EVENT_BACKLOG = 500
SESSION_STATUS_TTL_SECONDS = 45.0


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


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
    gemini_selector_debug: bool = False
    gemini_selector_debug_dir: str = ""
    gemini_model: str = "gemini-1.5-flash"


@dataclass
class StoryAttempt:
    id: str
    index: int
    mode: str
    status: str
    prompt: str
    input_image_path: str
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


class LocalPreviewAdapter:
    """Fallback adapter used before Gemini web automation is plugged in.

    Current behavior copies the input frame to preview + normalized output so the
    scheduler/state machine and UI can be developed independently.
    """

    def generate(
        self,
        *,
        prompt: str,
        input_image_path: Path,
        preview_path: Path,
        normalized_path: Path,
        context: dict,
    ) -> GenerationResult:
        if not input_image_path.exists():
            raise StoryPipelineError(f"Khong tim thay input frame: {input_image_path}")

        preview_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_image_path, preview_path)
        shutil.copy2(preview_path, normalized_path)
        return GenerationResult(
            preview_path=str(preview_path),
            normalized_path=str(normalized_path),
        )


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

        self._settings = StorySettings(output_root=str(output_root or STORY_OUTPUT_ROOT))
        self._global_prompt = ""
        self._videos: dict[str, StoryVideo] = {}
        self._active_video_id: str | None = None
        self._injected_adapter = adapter
        self._adapter: StoryGenerationAdapter = LocalPreviewAdapter()
        self._queue: Queue[str] = Queue()
        self._queued_video_ids: set[str] = set()
        self._shutdown_event = threading.Event()
        self._workers: list[threading.Thread] = []
        self._session_status_cache: dict | None = None
        self._session_status_cache_time: float = 0.0

        self._load_state()
        self._refresh_adapter_locked()
        self._start_workers()

    def get_bootstrap(self) -> dict:
        session_status = self.get_session_status(refresh=False)
        with self._lock:
            return {
                "settings": asdict(self._settings),
                "globalPrompt": self._global_prompt,
                "videoSummaries": [self._serialize_video_summary(video) for video in self._videos.values()],
                "activeVideoId": self._active_video_id,
                "sessionStatus": session_status,
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

    def get_video_detail(self, video_id: str) -> dict | None:
        with self._lock:
            video = self._videos.get(video_id)
            if video is None:
                return None
            return self._serialize_video_detail(video)

    def get_session_status(self, refresh: bool = False) -> dict:
        with self._lock:
            backend = self._settings.generation_backend
            headless = self._settings.gemini_headless
            base_url = self._settings.gemini_base_url
            runtime_root = Path(self._settings.output_root) / "_gemini_runtime"
            cache = self._session_status_cache
            cache_time = self._session_status_cache_time

        if (
            not refresh
            and cache is not None
            and (time.monotonic() - cache_time) < SESSION_STATUS_TTL_SECONDS
        ):
            return cache

        if backend != "gemini_web":
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
        if self._settings.generation_backend != "gemini_web":
            return []
        return self._adapter.list_gems()

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
            if generation_backend not in {"local_preview", "gemini_web"}:
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
            gemini_selector_debug = _bool_value(
                payload.get("gemini_selector_debug", self._settings.gemini_selector_debug),
                default=self._settings.gemini_selector_debug,
            )
            gemini_selector_debug_dir = str(
                payload.get("gemini_selector_debug_dir", self._settings.gemini_selector_debug_dir)
            ).strip()

            gemini_model = str(payload.get("gemini_model", self._settings.gemini_model)).strip() or self._settings.gemini_model

            previous_max_parallel = self._settings.max_parallel_videos
            self._settings = StorySettings(
                output_root=output_root,
                max_parallel_videos=max(1, min(8, max_parallel_videos)),
                generation_backend=generation_backend,
                gemini_headless=gemini_headless,
                gemini_base_url=gemini_base_url,
                gemini_response_timeout_ms=max(20_000, min(300_000, gemini_response_timeout_ms)),
                gemini_selector_debug=gemini_selector_debug,
                gemini_selector_debug_dir=gemini_selector_debug_dir,
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
            videos = xmp_scanner.scan_folder(folder_path)
        except Exception as exc:
            raise StoryPipelineError(f"Quet thu muc that bai: {exc}") from exc

        if not videos:
            raise StoryPipelineError("Khong tim thay marker XMP nao trong thu muc nay. Hay dam bao ban da bat 'Write clip markers to XMP' trong Premiere.")

        return self.import_manifest({"manifest": {"videos": videos}})

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
            self._enqueue_video_locked(video.id)
            return self._serialize_video_detail(video)

    def pause_video(self, video_id: str) -> dict:
        with self._lock:
            video = self._require_video(video_id)
            if video.status == "completed":
                return self._serialize_video_detail(video)
            video.status = "paused"
            video.last_updated_at = utc_now()
            self._persist_state_locked()
            self._record_event_locked("story.video.updated", {"videoId": video.id})
            return self._serialize_video_detail(video)

    def apply_action(self, payload: dict) -> dict:
        action = str(payload.get("action", "")).strip().lower()
        video_id = str(payload.get("video_id", "")).strip()
        marker_id = str(payload.get("marker_id", "")).strip()
        step_id = str(payload.get("step_id", "")).strip()
        attempt_id = str(payload.get("attempt_id", "")).strip() or None

        if not action:
            raise StoryPipelineError("action la bat buoc")
        if not video_id:
            raise StoryPipelineError("video_id la bat buoc")

        if action == "run":
            return self.run_video(video_id)
        if action == "pause":
            return self.pause_video(video_id)

        if not marker_id or not step_id:
            raise StoryPipelineError("marker_id va step_id la bat buoc")

        with self._lock:
            video = self._require_video(video_id)
            marker = self._require_marker(video, marker_id)
            step = self._require_step(marker, step_id)

            if action == "accept":
                self._accept_step_attempt_locked(video, marker, step, attempt_id=attempt_id)
                self._persist_state_locked()
                self._record_event_locked("story.step.updated", {"videoId": video.id, "markerId": marker.id, "stepId": step.id})
                if video.status == "queued":
                    self._enqueue_video_locked(video.id)
                return self._serialize_video_detail(video)

            if action == "skip":
                step.status = "skipped"
                step.pending_mode = "auto"
                step.pending_input_path = None
                step.selected_attempt_id = None
                video.status = "queued"
                video.last_updated_at = utc_now()
                self._refresh_marker_status_locked(video, marker)
                self._refresh_video_status_locked(video)
                self._persist_state_locked()
                self._record_event_locked("story.step.updated", {"videoId": video.id, "markerId": marker.id, "stepId": step.id})
                self._enqueue_video_locked(video.id)
                return self._serialize_video_detail(video)

            if action in {"regenerate", "refine"}:
                self._queue_regeneration_locked(video, marker, step, action=action, attempt_id=attempt_id)
                self._persist_state_locked()
                self._record_event_locked("story.step.updated", {"videoId": video.id, "markerId": marker.id, "stepId": step.id})
                self._enqueue_video_locked(video.id)
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
            self._queue.put("__shutdown__")
        for worker in self._workers:
            worker.join(timeout=0.5)

    def _restart_workers(self) -> None:
        self._shutdown_event.set()
        for _ in self._workers:
            self._queue.put("__shutdown__")
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
        while not self._shutdown_event.is_set():
            try:
                video_id = self._queue.get(timeout=0.5)
            except Empty:
                continue

            try:
                if video_id == "__shutdown__":
                    return
                self._process_video(video_id)
            finally:
                self._queue.task_done()

    def _process_video(self, video_id: str) -> None:
        with self._lock:
            self._queued_video_ids.discard(video_id)
            video = self._videos.get(video_id)
            if video is None:
                return
            if video.status in {"paused", "completed"}:
                return

            step_context = self._next_step_to_generate_locked(video)
            if step_context is None:
                self._refresh_video_status_locked(video)
                self._persist_state_locked()
                self._record_event_locked("story.video.updated", {"videoId": video.id})
                return

            marker, step = step_context
            marker.status = "running"
            step.status = "running"
            mode = step.pending_mode or "auto"
            input_path = step.pending_input_path or self._resolve_step_input_locked(video, marker, step)
            prompt = self._merge_prompt(video, marker, step)

            attempt = StoryAttempt(
                id=f"att-{uuid.uuid4().hex[:10]}",
                index=len(step.attempts) + 1,
                mode=mode,
                status="running",
                prompt=prompt,
                input_image_path=input_path,
                started_at=utc_now(),
            )
            step.attempts.append(attempt)
            step.pending_mode = "auto"
            step.pending_input_path = None
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
                video.status = "failed"
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
            attempt.preview_path = result.preview_path
            attempt.normalized_path = result.normalized_path
            attempt.completed_at = utc_now()
            step.status = "review"
            marker.status = "review"
            video.status = "review"
            video.error = None
            video.last_updated_at = utc_now()
            self._persist_state_locked()
            self._record_event_locked(
                "story.attempt.review",
                {"videoId": video.id, "markerId": marker.id, "stepId": step.id, "attemptId": attempt.id},
            )

    def _run_generation(
        self,
        video: StoryVideo,
        marker: StoryMarker,
        step: StoryStep,
        attempt: StoryAttempt,
    ) -> GenerationResult:
        output_dir = (
            Path(self._settings.output_root)
            / sanitize_file_stem(video.name)
            / f"marker_{marker.index:03d}"
            / f"step_{step.index:02d}"
            / f"attempt_{attempt.index:02d}"
        )
        preview_path = output_dir / "preview.jpg"
        normalized_path = output_dir / "normalized.jpg"

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
                "mode": video.mode,
            },
        )

    def _next_step_to_generate_locked(self, video: StoryVideo) -> tuple[StoryMarker, StoryStep] | None:
        for marker in sorted(video.markers, key=lambda item: item.index):
            for step in sorted(marker.steps, key=lambda item: item.index):
                if step.status == "review":
                    return None
                if step.status in {"queued", "failed"}:
                    return marker, step
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
    ) -> None:
        if step.status != "review":
            raise StoryPipelineError("Step khong o trang thai review de regenerate/refine")

        if not step.attempts:
            raise StoryPipelineError("Step chua co attempt")

        selected_attempt = self._pick_attempt(step, attempt_id)

        if action == "regenerate":
            next_input = selected_attempt.input_image_path
        else:
            next_input = selected_attempt.normalized_path or selected_attempt.preview_path
            if not next_input:
                raise StoryPipelineError("Khong co output de refine")

        step.pending_mode = action
        step.pending_input_path = next_input
        step.status = "queued"
        marker.status = "queued"
        video.status = "queued"
        video.last_updated_at = utc_now()

    def _accept_step_attempt_locked(
        self,
        video: StoryVideo,
        marker: StoryMarker,
        step: StoryStep,
        *,
        attempt_id: str | None,
    ) -> None:
        if step.status != "review":
            raise StoryPipelineError("Step khong o trang thai review de accept")
        if not step.attempts:
            raise StoryPipelineError("Step chua co attempt")

        chosen = self._pick_attempt(step, attempt_id)
        if not chosen.preview_path and not chosen.normalized_path:
            raise StoryPipelineError("Attempt chua co output")

        chosen.status = "accepted"
        step.selected_attempt_id = chosen.id
        step.status = "completed"
        step.pending_mode = "auto"
        step.pending_input_path = None
        marker.status = "completed" if all(candidate.status in {"completed", "skipped"} for candidate in marker.steps) else "queued"
        video.status = "completed" if self._video_all_steps_done(video) else "queued"
        video.last_updated_at = utc_now()

        if video.status == "completed":
            self._active_video_id = video.id

    def _pick_attempt(self, step: StoryStep, attempt_id: str | None) -> StoryAttempt:
        if attempt_id:
            for candidate in step.attempts:
                if candidate.id == attempt_id:
                    return candidate
            raise StoryPipelineError(f"Khong tim thay attempt {attempt_id}")

        return step.attempts[-1]

    def _video_all_steps_done(self, video: StoryVideo) -> bool:
        for marker in video.markers:
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
        elif any(step.status == "review" for marker in video.markers for step in marker.steps):
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

            seed_prompt = str(raw_marker.get("seed_prompt") or raw_marker.get("seed") or "").strip()
            raw_steps = raw_marker.get("steps") or raw_marker.get("story_steps") or []
            if not isinstance(raw_steps, list):
                raise StoryPipelineError("steps cua marker phai la array")
            if not raw_steps:
                raw_steps = [{"title": label, "modifier_prompt": ""}]

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

        now = utc_now()
        return StoryVideo(
            id=f"video-{uuid.uuid4().hex[:10]}",
            name=name,
            source_video_path=source_video_path,
            mode=mode,
            video_prompt=str(raw_video.get("video_prompt") or "").strip(),
            status="queued",
            created_at=now,
            last_updated_at=now,
            markers=markers,
        )

    def _merge_prompt(self, video: StoryVideo, marker: StoryMarker, step: StoryStep) -> str:
        parts = [
            self._global_prompt.strip(),
            video.video_prompt.strip(),
            marker.seed_prompt.strip(),
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

        return {
            "id": video.id,
            "name": video.name,
            "sourceVideoPath": video.source_video_path,
            "status": video.status,
            "mode": video.mode,
            "createdAt": video.created_at,
            "lastUpdatedAt": video.last_updated_at,
            "markerCount": len(video.markers),
            "stepTotal": step_total,
            "completedSteps": completed_steps,
            "reviewSteps": review_steps,
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
                    gemini_selector_debug=_bool_value(
                        settings.get("gemini_selector_debug", self._settings.gemini_selector_debug),
                        default=self._settings.gemini_selector_debug,
                    ),
                    gemini_selector_debug_dir=str(
                        settings.get("gemini_selector_debug_dir", self._settings.gemini_selector_debug_dir)
                    ).strip(),
                )
                # Always force gemini_web as requested by user
                self._settings.generation_backend = "gemini_web"
            except (TypeError, ValueError):
                pass

        self._global_prompt = str(raw.get("global_prompt", "")).strip() if isinstance(raw, dict) else ""

        raw_videos = raw.get("videos") if isinstance(raw, dict) else []
        if isinstance(raw_videos, list):
            restored: dict[str, StoryVideo] = {}
            for item in raw_videos:
                try:
                    video = self._deserialize_video(item)
                except Exception:
                    continue
                restored[video.id] = video
            self._videos = restored

        active_video_id = raw.get("active_video_id") if isinstance(raw, dict) else None
        if isinstance(active_video_id, str) and active_video_id in self._videos:
            self._active_video_id = active_video_id
        else:
            self._active_video_id = next(iter(self._videos), None)

    def _persist_state_locked(self) -> None:
        payload = {
            "settings": asdict(self._settings),
            "global_prompt": self._global_prompt,
            "active_video_id": self._active_video_id,
            "videos": [self._serialize_video_state(video) for video in self._videos.values()],
        }

        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

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
                            "attempts": [
                                {
                                    "id": attempt.id,
                                    "index": attempt.index,
                                    "mode": attempt.mode,
                                    "status": attempt.status,
                                    "prompt": attempt.prompt,
                                    "input_image_path": attempt.input_image_path,
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

    def _enqueue_video_locked(self, video_id: str) -> None:
        if video_id in self._queued_video_ids:
            return
        self._queued_video_ids.add(video_id)
        self._queue.put(video_id)

    def _refresh_adapter_locked(self) -> None:
        if self._injected_adapter is not None:
            self._adapter = self._injected_adapter
            return

        if self._settings.generation_backend == "gemini_web":
            runtime_root = Path(self._settings.output_root) / "_gemini_runtime"
            runtime_root.mkdir(parents=True, exist_ok=True)
            debug_root_raw = self._settings.gemini_selector_debug_dir.strip()
            if debug_root_raw:
                debug_root = Path(debug_root_raw).expanduser()
                if not debug_root.is_absolute():
                    debug_root = Path(self._settings.output_root) / debug_root
            else:
                debug_root = Path(self._settings.output_root) / "_gemini_debug"
            self._adapter = GeminiWebAdapter(
                runtime_root=runtime_root,
                headless=self._settings.gemini_headless,
                base_url=self._settings.gemini_base_url,
                response_timeout_ms=self._settings.gemini_response_timeout_ms,
                debug_selector=self._settings.gemini_selector_debug,
                debug_root=debug_root,
            )
            return

        self._adapter = LocalPreviewAdapter()

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


def marker_order(items: list[StoryMarker]) -> list[StoryMarker]:
    return sorted(items, key=lambda item: item.index)


def step_order(items: list[StoryStep]) -> list[StoryStep]:
    return sorted(items, key=lambda item: item.index)


story_pipeline = StoryPipelineManager()
