import json
import re

with open("downloader_app/story_pipeline.py", "r") as f:
    code = f.read()

# 1. Add StoryProject
code = code.replace(
"""@dataclass
class StoryVideo:""",
"""@dataclass
class StoryProject:
    id: str
    name: str
    folder: str
    created_at: str
    updated_at: str
    videos: dict[str, 'StoryVideo'] = field(default_factory=dict)
    active_video_id: str | None = None

@dataclass
class StoryVideo:""")

# 2. Update __init__
code = code.replace(
"""        self._global_prompt = ""
        self._videos: dict[str, StoryVideo] = {}
        self._active_video_id: str | None = None""",
"""        self._global_prompt = ""
        self._projects: dict[str, StoryProject] = {}
        self._active_project_id: str | None = None""")

# 3. Update get_bootstrap
code = code.replace(
"""    def get_bootstrap(self) -> dict:
        with self._lock:
            return {
                "settings": asdict(self._settings),
                "globalPrompt": self._global_prompt,
                "videoSummaries": [self._serialize_video_summary(video) for video in self._videos.values()],
                "activeVideoId": self._active_video_id,
                "sessionStatus": self._bootstrap_session_status_locked(),
            }""",
"""    def get_bootstrap(self) -> dict:
        with self._lock:
            active_project = self._projects.get(self._active_project_id) if self._active_project_id else None
            return {
                "settings": asdict(self._settings),
                "globalPrompt": self._global_prompt,
                "projects": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "folderPath": p.folder,
                        "videoCount": len(p.videos),
                        "createdAt": p.created_at,
                        "updatedAt": p.updated_at,
                    }
                    for p in self._projects.values()
                ],
                "activeProjectId": self._active_project_id,
                "videoSummaries": [self._serialize_video_summary(video) for video in active_project.videos.values()] if active_project else [],
                "activeVideoId": active_project.active_video_id if active_project else None,
                "sessionStatus": self._bootstrap_session_status_locked(),
            }

    def _require_project(self, project_id: str) -> StoryProject:
        project = self._projects.get(project_id)
        if not project:
            raise StoryPipelineError(f"Khong tim thay project {project_id}")
        return project

    def create_project(self, payload: dict) -> dict:
        with self._lock:
            name = str(payload.get("name", "")).strip() or "New Project"
            folder = str(payload.get("folder", "")).strip()
            project_id = f"story-{uuid.uuid4().hex[:10]}"
            project = StoryProject(
                id=project_id,
                name=name,
                folder=folder,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            self._projects[project.id] = project
            self._active_project_id = project.id
            self._persist_state_locked()
            return self.get_bootstrap()

    def select_project(self, project_id: str) -> dict:
        with self._lock:
            self._require_project(project_id)
            self._active_project_id = project_id
            self._persist_state_locked()
            return self.get_bootstrap()

    def delete_project(self, project_id: str) -> dict:
        with self._lock:
            if project_id in self._projects:
                del self._projects[project_id]
                if self._active_project_id == project_id:
                    self._active_project_id = list(self._projects.keys())[0] if self._projects else None
                self._persist_state_locked()
            return self.get_bootstrap()

    def rename_project(self, project_id: str, payload: dict) -> dict:
        with self._lock:
            project = self._require_project(project_id)
            name = str(payload.get("name", "")).strip()
            if name:
                project.name = name
                project.updated_at = utc_now()
                self._persist_state_locked()
            return self.get_bootstrap()""")

# 4. list_video_summaries
code = code.replace(
"""    def list_video_summaries(self, *, status: str | None = None, limit: int | None = None) -> list[dict]:
        with self._lock:
            items = [
                self._serialize_video_summary(video)
                for video in self._videos.values()
                if status is None or video.status == status
            ]""",
"""    def list_video_summaries(self, *, status: str | None = None, limit: int | None = None) -> list[dict]:
        with self._lock:
            active_project = self._projects.get(self._active_project_id) if self._active_project_id else None
            if not active_project:
                return []
            items = [
                self._serialize_video_summary(video)
                for video in active_project.videos.values()
                if status is None or video.status == status
            ]""")

# 5. clear_videos (remove this logic, or clear videos of active project)
code = code.replace(
"""    def clear_videos(self) -> dict:
        with self._lock:
            self._videos.clear()
            self._active_video_id = None
            self._persist_state_locked()
            self._record_event_locked("story.videos.cleared", {})
        return {"ok": True}""",
"""    def clear_videos(self) -> dict:
        with self._lock:
            if self._active_project_id and self._active_project_id in self._projects:
                self._projects[self._active_project_id].videos.clear()
                self._projects[self._active_project_id].active_video_id = None
            self._persist_state_locked()
            self._record_event_locked("story.videos.cleared", {})
        return {"ok": True}""")

# 6. _require_video
code = code.replace(
"""    def _require_video(self, video_id: str) -> StoryVideo:
        video = self._videos.get(video_id)
        if not video:
            raise StoryPipelineError(f"Khong tim thay video {video_id}")
        return video""",
"""    def _require_video(self, video_id: str) -> StoryVideo:
        for project in self._projects.values():
            if video_id in project.videos:
                return project.videos[video_id]
        raise StoryPipelineError(f"Khong tim thay video {video_id}")""")

# 7. import_from_folder
code = code.replace(
"""    def import_from_folder(self, payload: dict) -> list[dict]:
        folder_path = str(payload.get("folder_path", "")).strip()
        if not folder_path:
            raise StoryPipelineError("folder_path la bat buoc")

        try:
            staged_inputs_dir = story_gemini_runtime_root() / "staged_inputs"
            videos, diagnostics = xmp_scanner.scan_folder(folder_path, output_dir=staged_inputs_dir)
        except Exception as exc:
            raise StoryPipelineError(f"Quet thu muc that bai: {exc}") from exc

        if not videos:
            raise StoryPipelineError(self._build_xmp_import_error(diagnostics))

        return self.import_manifest({"manifest": {"videos": videos}})""",
"""    def import_from_folder(self, payload: dict) -> list[dict]:
        folder_path = str(payload.get("folder_path", "")).strip()
        if not folder_path:
            raise StoryPipelineError("folder_path la bat buoc")

        try:
            staged_inputs_dir = story_gemini_runtime_root() / "staged_inputs"
            videos, diagnostics = xmp_scanner.scan_folder(folder_path, output_dir=staged_inputs_dir)
        except Exception as exc:
            raise StoryPipelineError(f"Quet thu muc that bai: {exc}") from exc

        if not videos:
            raise StoryPipelineError(self._build_xmp_import_error(diagnostics))

        from pathlib import Path
        import uuid
        
        with self._lock:
            project_id = f"story-{uuid.uuid4().hex[:10]}"
            project = StoryProject(
                id=project_id,
                name=Path(folder_path).name or "New Project",
                folder=folder_path,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            self._projects[project.id] = project
            self._active_project_id = project.id
            
            created_ids: list[str] = []
            for raw_video in videos:
                video = self._build_video_from_manifest(raw_video)
                project.videos[video.id] = video
                created_ids.append(video.id)
                project.active_video_id = video.id
                self._record_event_locked("story.video.created", {"videoId": video.id})

            self._persist_state_locked()

        return [self.get_video_detail(video_id) or {} for video_id in created_ids]""")

# 8. get_video_detail
code = code.replace(
"""    def get_video_detail(self, video_id: str) -> dict | None:
        with self._lock:
            video = self._videos.get(video_id)
            if not video:
                return None
            
            # Neu dang lay detail cua video khac, chuyen active sang no
            if video_id != self._active_video_id:
                self._active_video_id = video_id
                self._persist_state_locked()
                
            return self._serialize_video_detail(video)""",
"""    def get_video_detail(self, video_id: str) -> dict | None:
        with self._lock:
            for project in self._projects.values():
                if video_id in project.videos:
                    video = project.videos[video_id]
                    if project.active_video_id != video_id:
                        project.active_video_id = video_id
                        self._persist_state_locked()
                    return self._serialize_video_detail(video)
            return None""")

# 9. _load_state
code = code.replace(
"""        self._global_prompt = str(raw.get("global_prompt", "")).strip() if isinstance(raw, dict) else ""

        self._global_prompt = str(raw.get("global_prompt", "")).strip() if isinstance(raw, dict) else ""

        # Load video state
        self._videos = {}
        serialized_videos = raw.get("videos", []) if isinstance(raw, dict) else []
        if isinstance(serialized_videos, list):
            for video_dict in serialized_videos:
                try:
                    video = self._deserialize_video(video_dict)
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
            self._active_video_id = None""",
"""        self._global_prompt = str(raw.get("global_prompt", "")).strip() if isinstance(raw, dict) else ""

        self._projects = {}
        if "projects" in raw:
            for proj_data in raw.get("projects", []):
                project = StoryProject(
                    id=str(proj_data.get("id")),
                    name=str(proj_data.get("name")),
                    folder=str(proj_data.get("folder")),
                    created_at=str(proj_data.get("created_at", utc_now())),
                    updated_at=str(proj_data.get("updated_at", utc_now())),
                    active_video_id=proj_data.get("active_video_id"),
                )
                for video_dict in proj_data.get("videos", []):
                    try:
                        video = self._deserialize_video(video_dict)
                        project.videos[video.id] = video
                    except Exception:
                        pass
                self._projects[project.id] = project
            self._active_project_id = str(raw.get("active_project_id", ""))
            if self._active_project_id not in self._projects:
                self._active_project_id = list(self._projects.keys())[0] if self._projects else None
        else:
            # Migration from old state
            videos = {}
            for video_dict in raw.get("videos", []) if isinstance(raw, dict) else []:
                try:
                    video = self._deserialize_video(video_dict)
                    videos[video.id] = video
                except Exception:
                    pass
            if videos:
                import uuid
                proj_id = f"story-{uuid.uuid4().hex[:10]}"
                project = StoryProject(
                    id=proj_id,
                    name="Default Project",
                    folder="",
                    created_at=utc_now(),
                    updated_at=utc_now(),
                    videos=videos,
                    active_video_id=str(raw.get("active_video_id", "")) if str(raw.get("active_video_id", "")) in videos else None,
                )
                self._projects[proj_id] = project
                self._active_project_id = proj_id""")

# 10. _persist_state_locked
code = code.replace(
"""    def _persist_state_locked(self) -> None:
        payload = {
            "settings": asdict(self._settings),
            "global_prompt": self._global_prompt,
            "active_video_id": self._active_video_id,
            "videos": [self._serialize_video_state(video) for video in self._videos.values()],
        }""",
"""    def _persist_state_locked(self) -> None:
        payload = {
            "settings": asdict(self._settings),
            "global_prompt": self._global_prompt,
            "active_project_id": self._active_project_id,
            "projects": [
                {
                    "id": p.id,
                    "name": p.name,
                    "folder": p.folder,
                    "created_at": p.created_at,
                    "updated_at": p.updated_at,
                    "active_video_id": p.active_video_id,
                    "videos": [self._serialize_video_state(video) for video in p.videos.values()],
                }
                for p in self._projects.values()
            ],
        }""")

# 11. _reset_runtime_state_for_restart
code = code.replace(
"""    def _reset_runtime_state_for_restart(self) -> None:
        if not self._videos:
            return

        self._queued_marker_ids.clear()
        interruption_message = "Tien trinh bi gian doan khi khoi dong lai ung dung."

        for video in self._videos.values():""",
"""    def _reset_runtime_state_for_restart(self) -> None:
        self._queued_marker_ids.clear()
        interruption_message = "Tien trinh bi gian doan khi khoi dong lai ung dung."

        for project in self._projects.values():
            for video in project.videos.values():""")

# 12. _migrate_frames_to_local_cache
code = code.replace(
"""    def _migrate_frames_to_local_cache(self) -> None:
        \"\"\"
        Di cu toan bo frame tu o ngoai vao cache noi bo cho tat ca video hien co.
        Giup on dinh hoa cac project cu da tao truoc khi co logic caching.
        \"\"\"
        with self._lock:
            modified = False
            for video in self._videos.values():""",
"""    def _migrate_frames_to_local_cache(self) -> None:
        \"\"\"
        Di cu toan bo frame tu o ngoai vao cache noi bo cho tat ca video hien co.
        Giup on dinh hoa cac project cu da tao truoc khi co logic caching.
        \"\"\"
        with self._lock:
            modified = False
            for project in self._projects.values():
                for video in project.videos.values():""")

with open("downloader_app/story_pipeline.py", "w") as f:
    f.write(code)

