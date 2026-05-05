import re

with open("downloader_app/story_pipeline.py", "r") as f:
    code = f.read()

# Line 327: `video = self._videos.get(video_id)` inside `cancel_generation` maybe?
# I'll just change `self._videos.get(video_id)` to `self._get_video_safe(video_id)`
# Wait, I already created `self._require_video(video_id)`.
# But `get()` does not raise an error.
# Let's add `self._get_video_safe(video_id)`.

add_safe = """    def _require_video(self, video_id: str) -> StoryVideo:
        for project in self._projects.values():
            if video_id in project.videos:
                return project.videos[video_id]
        raise StoryPipelineError(f"Khong tim thay video {video_id}")

    def _get_video_safe(self, video_id: str) -> StoryVideo | None:
        for project in self._projects.values():
            if video_id in project.videos:
                return project.videos[video_id]
        return None"""

code = code.replace("""    def _require_video(self, video_id: str) -> StoryVideo:
        for project in self._projects.values():
            if video_id in project.videos:
                return project.videos[video_id]
        raise StoryPipelineError(f"Khong tim thay video {video_id}")""", add_safe)

code = code.replace("self._videos.get(video_id)", "self._get_video_safe(video_id)")

# self._videos.values() -> We need a helper `_all_videos()`
add_all = """    def _all_videos(self):
        for p in self._projects.values():
            for v in p.videos.values():
                yield v"""

code = code.replace("    def _get_video_safe(self", add_all + "\n\n    def _get_video_safe(self")

code = code.replace("self._videos.values()", "self._all_videos()")

# self._videos[video.id] = video -> wait, where does this happen?
# At line 547: probably during import manifest?
# Let's check where `self._videos[video.id] = video` is.
# It is in `import_manifest`. But wait, I replaced `import_manifest` with `import_from_folder`!

with open("downloader_app/story_pipeline.py", "w") as f:
    f.write(code)

