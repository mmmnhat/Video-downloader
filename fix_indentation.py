with open("downloader_app/story_pipeline.py", "r") as f:
    lines = f.readlines()

new_lines = []
in_migrate = False
in_reset = False

for line in lines:
    if "def _migrate_frames_to_local_cache" in line:
        in_migrate = True
        
    if "def _persist_state_locked" in line:
        in_migrate = False
        
    if "def _reset_runtime_state_for_restart" in line:
        in_reset = True
        
    if "def _refresh_adapter_locked" in line:
        in_reset = False

    if in_migrate:
        # indent if starts with exactly 16 spaces (4 for def, 4 for with, 4 for for proj, 4 for vid -> wait! Original was `for video in self._videos.values():` which had 12 spaces.
        # Now we added `for project` which has 12 spaces, so `for video` has 16 spaces. The contents inside it had 16 spaces originally, now need 20 spaces.
        if line.startswith("                ") and not line.startswith("                    ") and "for video in project.videos" not in line:
            # We must indent it 4 more spaces.
            # But wait, we only want to indent the body of the `for video` loop.
            pass

with open("downloader_app/story_pipeline.py", "r") as f:
    code = f.read()

# Instead of complex logic, I'll use simple replacements for the exact blocks:

migrate_old = """    def _migrate_frames_to_local_cache(self) -> None:
        \"\"\"
        Di cu toan bo frame tu o ngoai vao cache noi bo cho tat ca video hien co.
        Giup on dinh hoa cac project cu da tao truoc khi co logic caching.
        \"\"\"
        with self._lock:
            modified = False
            for project in self._projects.values():
                for video in project.videos.values():
                inputs_dir = self._video_inputs_dir(video.id)
                for marker in video.markers:
                    # Neu path van dang nam o '_frames' hoac o ngoai volume thi di cu
                    current_path = Path(marker.input_frame_path)
                    if ("_frames" in str(current_path) or ".frames" in str(current_path)) and current_path.exists():
                        new_filename = f"m{marker.index:02d}_source{current_path.suffix}"
                        new_path = inputs_dir / new_filename
                        if not new_path.exists():
                            try:
                                import shutil
                                shutil.copy(str(current_path), str(new_path))
                                marker.input_frame_path = str(new_path)
                                modified = True
                            except Exception as e:
                                print(f"[StoryPipeline] Migration failed for {marker.id}: {e}")
                        elif str(current_path) != str(new_path):
                            marker.input_frame_path = str(new_path)
                            modified = True
            if modified:
                self._persist_state_locked()"""

migrate_new = """    def _migrate_frames_to_local_cache(self) -> None:
        \"\"\"
        Di cu toan bo frame tu o ngoai vao cache noi bo cho tat ca video hien co.
        Giup on dinh hoa cac project cu da tao truoc khi co logic caching.
        \"\"\"
        with self._lock:
            modified = False
            for project in self._projects.values():
                for video in project.videos.values():
                    inputs_dir = self._video_inputs_dir(video.id)
                    for marker in video.markers:
                        # Neu path van dang nam o '_frames' hoac o ngoai volume thi di cu
                        current_path = Path(marker.input_frame_path)
                        if ("_frames" in str(current_path) or ".frames" in str(current_path)) and current_path.exists():
                            new_filename = f"m{marker.index:02d}_source{current_path.suffix}"
                            new_path = inputs_dir / new_filename
                            if not new_path.exists():
                                try:
                                    import shutil
                                    shutil.copy(str(current_path), str(new_path))
                                    marker.input_frame_path = str(new_path)
                                    modified = True
                                except Exception as e:
                                    print(f"[StoryPipeline] Migration failed for {marker.id}: {e}")
                            elif str(current_path) != str(new_path):
                                marker.input_frame_path = str(new_path)
                                modified = True
            if modified:
                self._persist_state_locked()"""

reset_old = """    def _reset_runtime_state_for_restart(self) -> None:
        self._queued_marker_ids.clear()
        interruption_message = "Tien trinh bi gian doan khi khoi dong lai ung dung."

        for project in self._projects.values():
            for video in project.videos.values():
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
                            video.error = video.error or interruption_message

            self._refresh_video_status_locked(video)"""

reset_new = """    def _reset_runtime_state_for_restart(self) -> None:
        self._queued_marker_ids.clear()
        interruption_message = "Tien trinh bi gian doan khi khoi dong lai ung dung."

        for project in self._projects.values():
            for video in project.videos.values():
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
                                video.error = video.error or interruption_message

                self._refresh_video_status_locked(video)"""

code = code.replace(migrate_old, migrate_new)
code = code.replace(reset_old, reset_new)

with open("downloader_app/story_pipeline.py", "w") as f:
    f.write(code)

