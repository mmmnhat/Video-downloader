from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from downloader_app.runtime import cache_root
from downloader_app.story_pipeline import (
    STORY_CACHE_ROOT,
    story_debug_root,
    story_gem_scan_runtime_root,
    story_gemini_runtime_root,
    story_generated_root,
    story_pipeline,
)
from downloader_app.tts_manager import (
    ACTIVE_BATCH_STATUSES,
    TTS_BATCH_ROOT,
    TTS_CACHE_ROOT,
    TTS_PROFILE_ROOT,
    TTS_SCRATCH_ROOT,
    TTS_VOICE_CACHE_FILE,
    tts_manager,
)


@dataclass(frozen=True)
class CacheGroupDefinition:
    id: str
    feature: str
    title: str
    description: str
    path: Path
    open_path: Path


def _path_stats(path: Path) -> tuple[int, int, int]:
    if not path.exists():
        return 0, 0, 0

    if path.is_file():
        try:
            return path.stat().st_size, 1, 0
        except OSError:
            return 0, 1, 0

    total_size = 0
    file_count = 0
    dir_count = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_dir():
                    dir_count += 1
                    continue
                if child.is_file():
                    file_count += 1
                    total_size += child.stat().st_size
            except OSError:
                continue
    except OSError:
        return 0, 0, 0
    return total_size, file_count, dir_count


def _remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_file() or path.is_symlink():
        path.unlink(missing_ok=True)
        return
    shutil.rmtree(path, ignore_errors=True)


class CacheManagerError(RuntimeError):
    pass


class CacheManager:
    def _group_definitions(self) -> list[CacheGroupDefinition]:
        return [
            CacheGroupDefinition(
                id="story-generated",
                feature="story",
                title="Story Generated",
                description="Ảnh preview và normalized của Gen Img.",
                path=story_generated_root(),
                open_path=STORY_CACHE_ROOT,
            ),
            CacheGroupDefinition(
                id="story-runtime",
                feature="story",
                title="Story Gemini Runtime",
                description="Profile và runtime tạm cho Gemini web.",
                path=story_gemini_runtime_root(),
                open_path=STORY_CACHE_ROOT,
            ),
            CacheGroupDefinition(
                id="story-scan-runtime",
                feature="story",
                title="Story Gem Scan Runtime",
                description="Runtime tạm khi quét danh sách Gem.",
                path=story_gem_scan_runtime_root(),
                open_path=STORY_CACHE_ROOT,
            ),
            CacheGroupDefinition(
                id="story-debug",
                feature="story",
                title="Story Debug",
                description="Dữ liệu debug và selector dump của Gen Img.",
                path=story_debug_root(),
                open_path=STORY_CACHE_ROOT,
            ),
            CacheGroupDefinition(
                id="tts-batches",
                feature="tts",
                title="TTS Batches",
                description="Audio đã gen, workdir, và metadata runtime của TTS.",
                path=TTS_BATCH_ROOT,
                open_path=TTS_CACHE_ROOT,
            ),
            CacheGroupDefinition(
                id="tts-profiles",
                feature="tts",
                title="TTS Profiles",
                description="Profile browser clone phục vụ đăng nhập và session TTS.",
                path=TTS_PROFILE_ROOT,
                open_path=TTS_CACHE_ROOT,
            ),
            CacheGroupDefinition(
                id="tts-scratch",
                feature="tts",
                title="TTS Scratch",
                description="Thư mục tạm cho TTS worker.",
                path=TTS_SCRATCH_ROOT,
                open_path=TTS_CACHE_ROOT,
            ),
            CacheGroupDefinition(
                id="tts-voices-cache",
                feature="tts",
                title="TTS Voice Cache",
                description="Danh sách My Voice cache để bootstrap nhanh hơn.",
                path=TTS_VOICE_CACHE_FILE,
                open_path=TTS_CACHE_ROOT,
            ),
        ]

    def _story_active(self) -> bool:
        statuses = {
            str(item.get("status", "")).strip().lower()
            for item in story_pipeline.list_video_summaries()
            if isinstance(item, dict)
        }
        return bool(statuses & {"running", "review"})

    def _tts_active(self) -> bool:
        statuses = {
            str(item.get("status", "")).strip().lower()
            for item in tts_manager.list_batch_summaries()
            if isinstance(item, dict)
        }
        return bool(statuses & ACTIVE_BATCH_STATUSES)

    def _group_active(self, group_id: str) -> bool:
        if group_id.startswith("story-"):
            return self._story_active()
        if group_id.startswith("tts-"):
            return self._tts_active()
        return False

    def _serialize_group(self, definition: CacheGroupDefinition) -> dict:
        size_bytes, file_count, dir_count = _path_stats(definition.path)
        active = self._group_active(definition.id)
        return {
            "id": definition.id,
            "feature": definition.feature,
            "title": definition.title,
            "description": definition.description,
            "path": str(definition.path),
            "openPath": str(definition.open_path),
            "exists": definition.path.exists(),
            "sizeBytes": size_bytes,
            "fileCount": file_count,
            "dirCount": dir_count,
            "active": active,
            "canDelete": not active,
        }

    def get_bootstrap(self) -> dict:
        groups = [self._serialize_group(definition) for definition in self._group_definitions()]
        return {
            "rootPath": str(cache_root()),
            "groups": groups,
            "summary": {
                "groupCount": len(groups),
                "existingGroupCount": sum(1 for group in groups if group["exists"]),
                "totalSizeBytes": sum(int(group["sizeBytes"]) for group in groups),
                "totalFileCount": sum(int(group["fileCount"]) for group in groups),
            },
        }

    def clear(self, group_id: str) -> dict:
        definitions = {definition.id: definition for definition in self._group_definitions()}
        if group_id == "all":
            targets = list(definitions.values())
        else:
            target = definitions.get(group_id)
            if target is None:
                raise CacheManagerError("Không tìm thấy nhóm cache cần xoá.")
            targets = [target]

        cleared: list[str] = []
        skipped: list[dict] = []
        removed_bytes = 0

        for definition in targets:
            if self._group_active(definition.id):
                skipped.append({"id": definition.id, "reason": "dang_duoc_su_dung"})
                continue

            size_bytes, _, _ = _path_stats(definition.path)
            removed_bytes += size_bytes
            _remove_path(definition.path)
            cleared.append(definition.id)

        return {
            "cleared": cleared,
            "skipped": skipped,
            "removedBytes": removed_bytes,
            "bootstrap": self.get_bootstrap(),
        }


cache_manager = CacheManager()
