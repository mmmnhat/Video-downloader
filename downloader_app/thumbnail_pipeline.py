from __future__ import annotations

import json
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from downloader_app.gemini_web_adapter import GEMINI_DEFAULT_URL, GeminiWebAdapter
from downloader_app.jobs import sanitize_file_stem
from downloader_app.runtime import app_path, cache_path


THUMBNAIL_STATE_FILE = app_path("thumbnail_projects_state.json")
THUMBNAIL_CACHE_ROOT = cache_path("thumbnail_pipeline")
THUMBNAIL_PROJECTS_ROOT = THUMBNAIL_CACHE_ROOT / "projects"


def thumbnail_runtime_root() -> Path:
    return THUMBNAIL_CACHE_ROOT / "gemini_runtime"


def thumbnail_projects_root() -> Path:
    return THUMBNAIL_PROJECTS_ROOT


def thumbnail_debug_root() -> Path:
    return THUMBNAIL_CACHE_ROOT / "debug"


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def display_time() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")


class ThumbnailPipelineError(RuntimeError):
    pass


def _coerce_guide_rect(payload: dict) -> tuple[float, float, float, float] | None:
    rect = payload.get("rect")
    if not isinstance(rect, dict):
        return None
    try:
        x = float(rect.get("x", 0))
        y = float(rect.get("y", 0))
        width = float(rect.get("width", 0))
        height = float(rect.get("height", 0))
    except (TypeError, ValueError):
        return None
    if width <= 1 or height <= 1:
        return None
    return x, y, width, height


def require_pillow():
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise ThumbnailPipelineError(
            "Thiếu thư viện Pillow. Hãy chạy `.venv/bin/pip install -r requirements.txt` rồi mở lại app."
        ) from exc
    return Image


@dataclass
class ThumbnailButtonField:
    key: str
    label: str
    type: str
    value: str | int | float | bool | list | None
    tooltip: str
    options: list[str] = field(default_factory=list)
    min: float | None = None
    max: float | None = None
    required: bool = True
    visible_if: str | dict | None = None


@dataclass
class ThumbnailButton:
    id: str
    name: str
    icon: str
    category: str
    prompt_template: str
    requires_mask: bool
    create_new_chat: bool
    allow_regenerate: bool
    summary: str
    is_pinned: bool = False
    fields: list[ThumbnailButtonField] = field(default_factory=list)


@dataclass
class ThumbnailProfileEffect:
    button_id: str
    fields: list[ThumbnailButtonField] = field(default_factory=list)

@dataclass
class ThumbnailProfile:
    id: str
    name: str
    icon: str
    effects: list[ThumbnailProfileEffect] = field(default_factory=list)
    description: str = ""
    is_pinned: bool = False


@dataclass
class ThumbnailVersion:
    id: str
    label: str
    note: str
    prompt: str
    button_name: str
    fields: dict[str, str | int]
    mask_mode: str
    created_at: str
    status: str
    source_image_path: str
    output_image_path: str
    thread_url: str | None = None
    parent_version_id: str | None = None


@dataclass
class ThumbnailProject:
    id: str
    name: str
    folder: str
    source_image_path: str
    created_at: str
    updated_at: str
    selected_version_id: str
    versions: list[ThumbnailVersion] = field(default_factory=list)


def default_buttons() -> list[ThumbnailButton]:
    return [
        ThumbnailButton(
            id="change-color",
            name="Đổi màu vật thể",
            icon="🎨",
            category="Màu sắc",
            prompt_template="Change only the selected {object} to {color}.\nKeep face, pose, background, lighting, and all unmasked areas unchanged.",
            requires_mask=True,
            create_new_chat=True,
            allow_regenerate=True,
            summary="Đổi đúng màu vùng đã chọn mà không làm lệch phần còn lại.",
            fields=[
                ThumbnailButtonField(
                    key="object",
                    label="Vật thể",
                    type="text",
                    value="áo",
                    tooltip="Mô tả ngắn vật thể cần đổi màu, ví dụ áo, tóc, mũ hoặc ghế.",
                ),
                ThumbnailButtonField(
                    key="color",
                    label="Màu mới",
                    type="text",
                    value="đỏ",
                    tooltip="Nhập màu đích muốn áp dụng cho vật thể đã chọn.",
                ),
            ],
        ),
        ThumbnailButton(
            id="remove-object",
            name="Xóa vật thể",
            icon="🧽",
            category="Dọn ảnh",
            prompt_template="Remove the object in the red masked area.\nReconstruct the hidden area naturally.\nKeep all unmasked areas unchanged.",
            requires_mask=True,
            create_new_chat=True,
            allow_regenerate=True,
            summary="Xóa logo, chữ hoặc chi tiết thừa theo vùng mask đỏ.",
        ),
        ThumbnailButton(
            id="extend-wide",
            name="Extend Canvas",
            icon="🖼️",
            category="Khung hình",
            prompt_template="Extend this image to a clean {target_ratio} thumbnail composition.\n{artboard_hint}\nPreserve the subject scale, identity, and lighting.\nFill new space naturally for the new frame while respecting the intended composition.",
            requires_mask=False,
            create_new_chat=True,
            allow_regenerate=True,
            summary="Mở rộng khung hình theo tỉ lệ mong muốn để chuẩn bị xuất thumbnail.",
            fields=[
                ThumbnailButtonField(
                    key="target_ratio",
                    label="Tỉ lệ đích",
                    type="select",
                    value="16:9",
                    tooltip="Chọn tỉ lệ khung hình muốn mở rộng tới.",
                    options=["16:9", "4:5", "1:1", "3:4", "2:3", "9:16", "21:9", "custom"],
                ),
                ThumbnailButtonField(
                    key="custom_ratio",
                    label="Tỉ lệ custom",
                    type="text",
                    value="",
                    tooltip="Nhập tỉ lệ tự do, ví dụ 5:4 hoặc 7:10.",
                    required=False,
                    visible_if={"target_ratio": "custom"},
                ),
                ThumbnailButtonField(
                    key="artboard_hint",
                    label="Ghi chú artboard",
                    type="textarea",
                    value="Keep the main subject balanced inside the new frame.",
                    tooltip="Gợi ý bố cục bổ sung, có thể tự động cập nhật từ tool artboard trên canvas.",
                    required=False,
                ),
            ],
        ),
        ThumbnailButton(
            id="shock-face",
            name="Làm mặt sốc hơn",
            icon="😱",
            category="Biểu cảm",
            prompt_template="Make the character expression more {expression}, intensity {intensity}/10.\nKeep identity, pose, outfit and background unchanged.",
            requires_mask=False,
            create_new_chat=True,
            allow_regenerate=True,
            summary="Đẩy biểu cảm khuôn mặt mạnh hơn nhưng giữ nhận diện nhân vật.",
            fields=[
                ThumbnailButtonField(
                    key="expression",
                    label="Biểu cảm",
                    type="select",
                    value="shocked",
                    tooltip="Chọn kiểu biểu cảm muốn đẩy mạnh trên gương mặt.",
                    options=["shocked", "scared", "crying", "angry"],
                ),
                ThumbnailButtonField(
                    key="intensity",
                    label="Cường độ",
                    type="slider",
                    value=8,
                    tooltip="Điều chỉnh độ mạnh của biểu cảm từ nhẹ đến rất gắt.",
                    min=1,
                    max=10,
                ),
            ],
        ),
    ]


class ThumbnailPipelineManager:
    def __init__(self) -> None:
        self._state_file = THUMBNAIL_STATE_FILE
        self._projects_root = THUMBNAIL_PROJECTS_ROOT
        self._runtime_root = thumbnail_runtime_root()
        self._debug_root = thumbnail_debug_root()
        self._lock = threading.RLock()
        self._projects: dict[str, ThumbnailProject] = {}
        self._buttons: list[ThumbnailButton] = default_buttons()
        self._active_project_id: str | None = None
        self._profiles: list[ThumbnailProfile] = []
        self._adapter: GeminiWebAdapter | None = None
        self._running_project_ids: set[str] = set()
        self._load_state()
        if not self._profiles:
            self._profiles = [
                ThumbnailProfile(
                    id="funny_thumbnail",
                    name="Funny Thumbnail",
                    icon="🔥",
                    effects=[
                        self._build_profile_effect("extend-wide"),
                        self._build_profile_effect(
                            "shock-face",
                            field_values={"expression": "shocked", "intensity": 8},
                        ),
                    ],
                    description="Combo: Mở rộng + Biểu cảm sốc",
                )
            ]

    def _build_unique_project_dir(self, folder_path: Path, project_name: str, project_id: str) -> Path:
        base_stem = sanitize_file_stem(project_name or project_id).strip() or project_id
        preferred = folder_path / f"{base_stem}-{project_id}"
        if not preferred.exists():
            return preferred

        suffix = 1
        while True:
            candidate = folder_path / f"{base_stem}-{project_id}-{suffix}"
            if not candidate.exists():
                return candidate
            suffix += 1

    def _folder_in_use_by_other_project_locked(self, folder: Path, current_project_id: str) -> bool:
        target = str(folder.resolve())
        for project in self._projects.values():
            if project.id == current_project_id:
                continue
            try:
                if str(Path(project.folder).resolve()) == target:
                    return True
            except Exception:
                if project.folder == target:
                    return True
        return False

    def get_bootstrap(self) -> dict:
        with self._lock:
            if self._repair_all_projects_missing_outputs_locked():
                self._persist_locked()
            return {
                "buttons": [self._serialize_button(button) for button in self._buttons],
                "projects": [self._serialize_project_summary(project) for project in self._projects.values()],
                "activeProjectId": self._active_project_id,
                "activeProject": self._serialize_project_detail(self._projects[self._active_project_id]) if self._active_project_id and self._active_project_id in self._projects else None,
                "profiles": [self._serialize_profile(profile) for profile in self._profiles],
                "sessionStatus": {
                    "backend": "gemini_web",
                    "dependencies_ready": True,
                    "authenticated": True,
                    "baseUrl": GEMINI_DEFAULT_URL,
                },
            }

    def create_project(self, *, name: str, folder: str, source_image_path: str) -> dict:
        source_path = Path(source_image_path).expanduser().resolve()
        if not source_path.exists() or not source_path.is_file():
            raise ThumbnailPipelineError("Không tìm thấy ảnh gốc để tạo project.")

        project_name = str(name).strip() or source_path.stem
        if not folder:
            folder_path = self._projects_root
        else:
            folder_path = Path(folder).expanduser()
            if not folder_path.is_absolute():
                folder_path = (Path.cwd() / folder_path).resolve()
        folder_path.mkdir(parents=True, exist_ok=True)

        project_id = f"thumb-{uuid.uuid4().hex[:10]}"
        version_id = "original"
        project_dir = self._build_unique_project_dir(folder_path, project_name, project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        versions_dir = project_dir / "versions" / version_id
        versions_dir.mkdir(parents=True, exist_ok=True)

        copied_source = versions_dir / f"original{source_path.suffix.lower() or '.png'}"
        shutil.copy2(source_path, copied_source)

        version = ThumbnailVersion(
            id=version_id,
            label="Version 0 - Original",
            note="Ảnh gốc vừa tạo project",
            prompt="Ảnh gốc chưa chỉnh sửa.",
            button_name="Original",
            fields={},
            mask_mode="none",
            created_at=display_time(),
            status="current",
            source_image_path=str(copied_source),
            output_image_path=str(copied_source),
        )
        project = ThumbnailProject(
            id=project_id,
            name=project_name,
            folder=str(project_dir),
            source_image_path=str(copied_source),
            created_at=utc_now(),
            updated_at=utc_now(),
            selected_version_id=version_id,
            versions=[version],
        )
        with self._lock:
            self._projects[project.id] = project
            self._active_project_id = project.id
            self._persist_locked()
            return self._serialize_project_detail(project)

    def select_project(self, project_id: str) -> dict:
        with self._lock:
            project = self._require_project(project_id)
            repaired = self._repair_project_missing_outputs_locked(project)
            self._active_project_id = project.id
            if repaired:
                project.updated_at = utc_now()
            self._persist_locked()
            return self._serialize_project_detail(project)

    def delete_project(self, project_id: str) -> dict:
        with self._lock:
            project = self._projects.pop(project_id, None)
            if project:
                if self._active_project_id == project_id:
                    self._active_project_id = None
                project_dir = Path(project.folder)
                if project_dir.exists() and not self._folder_in_use_by_other_project_locked(project_dir, project_id):
                    shutil.rmtree(project_dir, ignore_errors=True)
                self._persist_locked()
            return {"ok": True}

    def rename_project(self, project_id: str, name: str) -> dict:
        name = name.strip()
        if not name:
            raise ThumbnailPipelineError("Tên dự án không được để trống.")
        with self._lock:
            project = self._require_project(project_id)
            project.name = name
            project.updated_at = utc_now()
            self._persist_locked()
            return self._serialize_project_detail(project)

    def select_version(self, project_id: str, version_id: str) -> dict:
        with self._lock:
            project = self._require_project(project_id)
            version = self._require_version(project, version_id)
            project.selected_version_id = version.id
            for item in project.versions:
                if item.id == version.id:
                    item.status = "current"
                elif item.status == "current":
                    item.status = "history"
            project.updated_at = utc_now()
            self._persist_locked()
            return self._serialize_project_detail(project)
    def delete_version(self, project_id: str, version_id: str) -> dict:
        with self._lock:
            project = self._require_project(project_id)

            # If this is the only version, delete the entire project
            if len(project.versions) <= 1:
                if self._active_project_id == project_id:
                    self._active_project_id = None
                project_dir = Path(project.folder)
                self._projects.pop(project_id, None)
                if project_dir.exists() and not self._folder_in_use_by_other_project_locked(project_dir, project_id):
                    shutil.rmtree(project_dir, ignore_errors=True)
                self._persist_locked()
                return {"ok": True, "projectDeleted": True}

            version_to_delete = None
            for idx, v in enumerate(project.versions):
                if v.id == version_id:
                    version_to_delete = project.versions.pop(idx)
                    break

            if not version_to_delete:
                raise ValueError(f"Không tìm thấy phiên bản {version_id}")

            # Physical cleanup
            if version_to_delete.output_image_path:
                img_path = Path(version_to_delete.output_image_path)
                if img_path.exists():
                    img_path.unlink()

            # Update selected version if it was the one deleted
            if project.selected_version_id == version_id:
                project.selected_version_id = project.versions[-1].id
                # Reset statuses
                for v in project.versions:
                    v.status = "current" if v.id == project.selected_version_id else "history"

            project.updated_at = utc_now()
            self._persist_locked()
            return {**self._serialize_project_detail(project), "projectDeleted": False}


    def create_button(self, payload: dict) -> dict:
        button_id = str(payload.get("id", "")).strip() or f"custom-{uuid.uuid4().hex[:8]}"
        button = ThumbnailButton(
            id=button_id,
            name=str(payload.get("name", "")).strip() or "Button mới",
            icon=str(payload.get("icon", "")).strip() or "✨",
            category=str(payload.get("category", "")).strip() or "Custom",
            prompt_template=str(payload.get("promptTemplate", "")).strip(),
            requires_mask=bool(payload.get("requiresMask", False)),
            create_new_chat=True,
            allow_regenerate=bool(payload.get("allowRegenerate", True)),
            summary=str(payload.get("summary", "")).strip() or "Nút tùy biến do user tạo.",
            fields=[self._deserialize_button_field(field) for field in (payload.get("fields") or [])],
        )
        if not button.prompt_template:
            raise ThumbnailPipelineError("Prompt template của button không được để trống.")
        with self._lock:
            existing = next((item for item in self._buttons if item.id == button.id), None)
            if existing:
                button.is_pinned = existing.is_pinned
            self._buttons = [item for item in self._buttons if item.id != button.id]
            self._buttons.append(button)
            self._persist_locked()
            return self._serialize_button(button)

    def delete_button(self, button_id: str) -> bool:
        with self._lock:
            self._buttons = [b for b in self._buttons if b.id != button_id]
            self._persist_locked()
            return True

    def toggle_pin_button(self, button_id: str) -> dict:
        with self._lock:
            for b in self._buttons:
                if b.id == button_id:
                    b.is_pinned = not b.is_pinned
                    self._persist_locked()
                    return self._serialize_button(b)
            raise ThumbnailPipelineError(f"Không tìm thấy button: {button_id}")

    def create_profile(self, payload: dict) -> dict:
        profile_id = str(payload.get("id", "")).strip() or f"prof-{uuid.uuid4().hex[:8]}"
        profile = ThumbnailProfile(
            id=profile_id,
            name=str(payload.get("name", "")).strip() or "Profile mới",
            icon=str(payload.get("icon", "")).strip() or "📦",
            description=str(payload.get("description", "")).strip(),
            effects=self._deserialize_profile_effects(payload),
        )
        
        with self._lock:
            existing = next((p for p in self._profiles if p.id == profile.id), None)
            if existing:
                profile.is_pinned = existing.is_pinned
            self._profiles = [p for p in self._profiles if p.id != profile.id]
            self._profiles.append(profile)
            self._persist_locked()
            return self._serialize_profile(profile)

    def delete_profile(self, profile_id: str) -> bool:
        with self._lock:
            self._profiles = [p for p in self._profiles if p.id != profile_id]
            self._persist_locked()
            return True

    def toggle_pin_profile(self, profile_id: str) -> dict:
        with self._lock:
            for p in self._profiles:
                if p.id == profile_id:
                    p.is_pinned = not p.is_pinned
                    self._persist_locked()
                    return self._serialize_profile(p)
            raise ThumbnailPipelineError(f"Không tìm thấy profile: {profile_id}")

    def run_profile(self, payload: dict) -> dict:
        project_id = str(payload.get("project_id", "")).strip()
        profile_id = str(payload.get("profile_id", "")).strip()
        mask_base64 = str(payload.get("mask_base64", "")).strip()
        canvas_guide = payload.get("canvas_guide")
        
        with self._lock:
            profile = next((p for p in self._profiles if p.id == profile_id), None)
            if not profile:
                raise ThumbnailPipelineError(f"Không tìm thấy profile: {profile_id}")
            
            combined_instructions = []
            buttons_map = {b.id: b for b in self._buttons}
            
            for idx, effect in enumerate(profile.effects):
                btn = buttons_map.get(effect.button_id)
                if btn:
                    merged_values = {f.key: f.value for f in btn.fields}
                    merged_values.update({field.key: field.value for field in effect.fields})
                    instr = self._build_prompt(btn, merged_values)
                    combined_instructions.append(f"{idx+1}. {instr}")
            
            final_prompt = "Perform the following improvements simultaneously:\n" + "\n".join(combined_instructions)
            final_prompt += "\n\nKeep the overall composition and all unmentioned details consistent with the original image."
            
            # Create a virtual button for history logging
            virtual_button = ThumbnailButton(
                id=f"profile-{profile.id}",
                name=profile.name,
                icon=profile.icon,
                category="Profile",
                prompt_template=final_prompt,
                requires_mask=bool(mask_base64),
                create_new_chat=True,
                allow_regenerate=True,
                summary=profile.description,
                fields=[]
            )
            
            # Forward to regular generation
            gen_payload = {
                **payload,
                "button_id": virtual_button.id,
                "prompt_override": final_prompt, # We'll need to update run_generation to support this
            }
            
            # Temporary hack: register the virtual button so run_generation finds it
            self._buttons.append(virtual_button)
            try:
                return self.run_generation(gen_payload)
            finally:
                self._buttons = [b for b in self._buttons if b.id != virtual_button.id]

    def run_generation_batch(self, payload: dict) -> dict:
        project_id = str(payload.get("project_id", "")).strip()
        effects = payload.get("effects", [])
        selected_mode = str(payload.get("selected_mode", "preset")).strip() or "preset"
        regenerate_mode = "new-chat"
        is_regenerate = bool(payload.get("is_regenerate", False))
        mask_mode = str(payload.get("mask_mode", "")).strip() or (
            "red" if selected_mode == "mask" else "none"
        )
        mask_base64 = str(payload.get("mask_base64", "")).strip()
        canvas_guide = payload.get("canvas_guide")

        if not effects:
            raise ThumbnailPipelineError("Không có hiệu ứng nào để chạy.")

        with self._lock:
            project = self._require_project(project_id)
            combined_instructions = []
            buttons_map = {b.id: b for b in self._buttons}
            
            for idx, effect in enumerate(effects):
                btn_id = effect.get("button_id")
                btn = buttons_map.get(btn_id)
                if btn:
                    field_values = effect.get("field_values", {})
                    merged_values = {f.key: f.value for f in btn.fields}
                    merged_values.update(field_values)
                    instr = self._build_prompt(btn, merged_values)
                    combined_instructions.append(f"{idx+1}. {instr}")
            
            if not combined_instructions:
                raise ThumbnailPipelineError("Các hiệu ứng không hợp lệ.")

            if len(combined_instructions) == 1:
                # Fallback to normal generation if only one effect
                payload["button_id"] = effects[0].get("button_id")
                payload["field_values"] = effects[0].get("field_values", {})
                return self.run_generation(payload)

            final_prompt = "Perform the following improvements simultaneously:\n" + "\n".join(combined_instructions)
            final_prompt += "\n\nKeep the overall composition and all unmentioned details consistent with the original image."
            
            # Use properties from the first button as a base
            first_btn = buttons_map.get(effects[0].get("button_id"))
            virtual_button = ThumbnailButton(
                id=f"virtual_batch_{uuid.uuid4().hex}",
                name=f"Batch Effects ({len(effects)})",
                icon=first_btn.icon if first_btn else "✨",
                category="Batch",
                prompt_template=final_prompt,
                requires_mask=any(
                    buttons_map.get(e.get("button_id")).requires_mask
                    for e in effects
                    if buttons_map.get(e.get("button_id"))
                ),
                create_new_chat=True,
                allow_regenerate=first_btn.allow_regenerate if first_btn else True,
                summary="Chạy đồng thời nhiều hiệu ứng trên cùng một ảnh.",
                fields=[],
            )
            self._buttons.append(virtual_button)

        try:
            gen_payload = {
                "project_id": project_id,
                "button_id": virtual_button.id,
                "field_values": {},
                "prompt_override": final_prompt,
                "selected_mode": selected_mode,
                "regenerate_mode": regenerate_mode,
                "is_regenerate": is_regenerate,
                "mask_mode": mask_mode,
                "mask_base64": mask_base64,
                "canvas_guide": canvas_guide,
            }
            return self.run_generation(gen_payload)
        finally:
            with self._lock:
                self._buttons = [b for b in self._buttons if b.id != virtual_button.id]

    def run_generation(self, payload: dict) -> dict:
        project_id = str(payload.get("project_id", "")).strip()
        button_id = str(payload.get("button_id", "")).strip()
        selected_mode = str(payload.get("selected_mode", "preset")).strip() or "preset"
        regenerate_mode = "new-chat"
        field_values = payload.get("field_values") or {}
        is_regenerate = bool(payload.get("is_regenerate", False))
        mask_mode = str(payload.get("mask_mode", "")).strip() or (
            "red" if selected_mode == "mask" else "none"
        )

        mask_base64 = str(payload.get("mask_base64", "")).strip()
        canvas_guide = payload.get("canvas_guide") or {}
        generation_claimed = False

        with self._lock:
            project = self._require_project(project_id)
            selected_version = self._require_version(project, project.selected_version_id)
            selected_version = self._repair_missing_selected_version_locked(project, selected_version)
            source_path = Path(selected_version.output_image_path).expanduser().resolve()
            if not source_path.exists():
                raise ThumbnailPipelineError(f"Không tìm thấy ảnh input của version hiện tại: {source_path}")
            button = self._require_button(button_id)
            prompt = payload.get("prompt_override") or self._build_prompt(button, field_values)
            if project.id in self._running_project_ids:
                raise ThumbnailPipelineError("Project này đang tạo ảnh. Vui lòng chờ lượt hiện tại hoàn tất.")
            self._running_project_ids.add(project.id)
            generation_claimed = True
            try:
                next_version = self._create_next_version_locked(
                    project=project,
                    parent_version=selected_version,
                    button=button,
                    prompt=prompt,
                    field_values=field_values,
                    mask_mode=mask_mode,
                    selected_mode=selected_mode,
                    regenerate_mode=regenerate_mode,
                    is_regenerate=is_regenerate,
                )
            except Exception:
                self._running_project_ids.discard(project.id)
                generation_claimed = False
                raise

        output_dir = Path(next_version.output_image_path).parent

        try:
            input_image_for_gemini = source_path
            if mask_base64 or canvas_guide:
                import base64
                import io
                Image = require_pillow()

                try:
                    base_img = Image.open(source_path).convert("RGBA")
                    working_img = base_img
                    working_mask = None

                    if mask_base64:
                        if "," in mask_base64:
                            mask_base64 = mask_base64.split(",")[1]
                        mask_data = base64.b64decode(mask_base64)
                        working_mask = Image.open(io.BytesIO(mask_data)).convert("RGBA")
                        if working_mask.size != working_img.size:
                            working_mask = working_mask.resize(working_img.size, Image.Resampling.LANCZOS)

                    guide_mode = str(canvas_guide.get("mode", "")).strip().lower()
                    guide_rect = _coerce_guide_rect(canvas_guide) if isinstance(canvas_guide, dict) else None
                    if guide_mode in {"crop", "artboard"} and guide_rect:
                        x, y, width, height = guide_rect
                        left = int(round(x))
                        top = int(round(y))
                        right = int(round(x + width))
                        bottom = int(round(y + height))

                        if guide_mode == "crop":
                            left = max(0, min(left, working_img.width - 1))
                            top = max(0, min(top, working_img.height - 1))
                            right = max(left + 1, min(right, working_img.width))
                            bottom = max(top + 1, min(bottom, working_img.height))
                            working_img = working_img.crop((left, top, right, bottom))
                            if working_mask is not None:
                                working_mask = working_mask.crop((left, top, right, bottom))
                        else:
                            target_width = max(1, int(round(width)))
                            target_height = max(1, int(round(height)))
                            artboard = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))
                            artboard.alpha_composite(working_img, (-left, -top))
                            working_img = artboard
                            if working_mask is not None:
                                mask_artboard = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))
                                mask_artboard.alpha_composite(working_mask, (-left, -top))
                                working_mask = mask_artboard

                    if working_mask is not None:
                        working_img = Image.alpha_composite(working_img, working_mask)

                    prepared_source_path = output_dir / "prepared_input.png"
                    working_img.save(prepared_source_path, "PNG")
                    input_image_for_gemini = prepared_source_path
                except Exception as e:
                    print(f"[DEBUG] Failed to prepare guided input: {e}")

            preview_path = output_dir / "preview.jpg"
            normalized_path = output_dir / "normalized.jpg"
            thread_url = None

            adapter = self._get_adapter()
            result = adapter.generate(
                prompt=prompt,
                input_image_path=input_image_for_gemini,
                preview_path=preview_path,
                normalized_path=normalized_path,
                context={
                    "mode": "regenerate" if is_regenerate else "auto",
                    "threadUrl": thread_url,
                    "buttonName": button.name,
                    "projectId": project.id,
                    "versionId": next_version.id,
                },
            )

            with self._lock:
                project = self._require_project(project_id)
                stored_version = self._require_version(project, next_version.id)
                stored_version.output_image_path = result.normalized_path
                stored_version.source_image_path = selected_version.output_image_path
                stored_version.thread_url = result.thread_url
                if result.response_text:
                    stored_version.note = result.response_text
                project.selected_version_id = stored_version.id
                project.updated_at = utc_now()
                self._persist_locked()
                return self._serialize_project_detail(project)
        except Exception as exc:
            self._rollback_failed_generation(project_id, next_version.id, selected_version.id)
            if isinstance(exc, ThumbnailPipelineError):
                raise
            raise ThumbnailPipelineError(str(exc)) from exc
        finally:
            if generation_claimed:
                with self._lock:
                    self._running_project_ids.discard(project_id)

    def export_image(self, payload: dict) -> dict:
        project_id = str(payload.get("project_id", "")).strip()
        version_id = str(payload.get("version_id", "")).strip()
        destination_dir_raw = str(payload.get("destination_dir", "")).strip()
        file_name_raw = str(payload.get("file_name", "")).strip()
        image_format = str(payload.get("format", "PNG")).strip().lower()

        if not destination_dir_raw:
            raise ThumbnailPipelineError("Cần chọn thư mục export.")

        with self._lock:
            project = self._require_project(project_id)
            version = self._require_version(project, version_id or project.selected_version_id)
            source_path = Path(version.output_image_path).expanduser().resolve()

        target_size = str(payload.get("size", "original")).strip().lower()

        if not source_path.exists():
            raise ThumbnailPipelineError("Không tìm thấy ảnh để export.")

        destination_dir = Path(destination_dir_raw).expanduser()
        if not destination_dir.is_absolute():
            destination_dir = (Path.cwd() / destination_dir).resolve()
        destination_dir.mkdir(parents=True, exist_ok=True)

        suffix = ".jpg" if image_format == "jpg" else ".png"
        file_name = sanitize_file_stem(file_name_raw or version.label) + suffix
        target_path = destination_dir / file_name

        if target_size == "original":
            shutil.copy2(source_path, target_path)
        else:
            try:
                Image = require_pillow()
                with Image.open(source_path) as img:
                    try:
                        w_str, h_str = target_size.split("x")
                        w, h = int(w_str), int(h_str)
                        # Resize with Lanczos for high quality
                        # If the aspect ratio is different, this will stretch. 
                        # But since we want "No Cropping", stretching/fitting is the only alternative if forced to a size.
                        # However, for thumbnails, usually users want exact size.
                        resized = img.resize((w, h), Image.Resampling.LANCZOS)
                        if image_format == "jpg":
                            resized.convert("RGB").save(target_path, "JPEG", quality=95)
                        else:
                            resized.save(target_path, "PNG")
                    except ValueError:
                        # Fallback to copy if size string is invalid
                        shutil.copy2(source_path, target_path)
            except Exception as e:
                print(f"[DEBUG] Resize failed: {e}")
                shutil.copy2(source_path, target_path)
        return {
            "ok": True,
            "path": str(target_path),
        }

    def clear_cache(self) -> dict:
        with self._lock:
            self._projects = {}
            self._active_project_id = None
            if self._projects_root.exists():
                shutil.rmtree(self._projects_root, ignore_errors=True)
            self._projects_root.mkdir(parents=True, exist_ok=True)
            self._persist_locked()
            return {"ok": True}

    def get_project_detail(self, project_id: str) -> dict | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                return None
            if self._repair_project_missing_outputs_locked(project):
                project.updated_at = utc_now()
                self._persist_locked()
            return self._serialize_project_detail(project)

    def _repair_all_projects_missing_outputs_locked(self) -> bool:
        changed = False
        for project in self._projects.values():
            if self._repair_project_missing_outputs_locked(project):
                project.updated_at = utc_now()
                changed = True
        return changed

    def _repair_project_missing_outputs_locked(self, project: ThumbnailProject) -> bool:
        valid_versions = [
            version
            for version in project.versions
            if Path(version.output_image_path).expanduser().exists()
        ]
        if len(valid_versions) == len(project.versions):
            return False
        if not valid_versions:
            return False

        selected = next((version for version in valid_versions if version.id == project.selected_version_id), None)
        if selected is None:
            selected = valid_versions[-1]

        project.versions = valid_versions
        project.selected_version_id = selected.id
        for version in project.versions:
            if version.id == selected.id:
                version.status = "current"
            elif version.status == "current":
                version.status = "history"
        return True

    def _repair_missing_selected_version_locked(
        self,
        project: ThumbnailProject,
        selected_version: ThumbnailVersion,
    ) -> ThumbnailVersion:
        selected_path = Path(selected_version.output_image_path).expanduser()
        if selected_path.exists():
            return selected_version

        if not self._repair_project_missing_outputs_locked(project):
            return selected_version

        fallback = self._require_version(project, project.selected_version_id)
        self._persist_locked()
        return fallback

    def _rollback_failed_generation(self, project_id: str, failed_version_id: str, restore_version_id: str) -> None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                return

            failed_version = next((version for version in project.versions if version.id == failed_version_id), None)
            if failed_version is not None:
                project.versions = [version for version in project.versions if version.id != failed_version_id]

            restore_version = next((version for version in project.versions if version.id == restore_version_id), None)
            if restore_version is None:
                restore_version = next(
                    (
                        version
                        for version in reversed(project.versions)
                        if Path(version.output_image_path).expanduser().exists()
                    ),
                    None,
                )
            if restore_version is None:
                self._persist_locked()
                return

            project.selected_version_id = restore_version.id
            for version in project.versions:
                version.status = "current" if version.id == restore_version.id else "history"
            project.updated_at = utc_now()
            self._persist_locked()

    def _create_next_version_locked(
        self,
        *,
        project: ThumbnailProject,
        parent_version: ThumbnailVersion,
        button: ThumbnailButton,
        prompt: str,
        field_values: dict,
        mask_mode: str,
        selected_mode: str,
        regenerate_mode: str,
        is_regenerate: bool,
    ) -> ThumbnailVersion:
        base_count = len([item for item in project.versions if item.id.startswith("v")]) + 1
        if is_regenerate:
            base_label = parent_version.label.split(" - ")[0]
            variant_count = sum(1 for item in project.versions if item.parent_version_id == parent_version.id and "Regenerate" in item.label)
            suffix = chr(ord("A") + variant_count)
            version_id = f"{parent_version.id}-{suffix.lower()}"
            label = f"{base_label}{suffix} - Regenerate"
            note = f"Chạy lại prompt bằng chat Gemini mới từ {parent_version.label}"
            status = "branch"
        else:
            version_id = f"v{base_count}"
            label = f"Version {base_count} - {button.name}"
            note = f"Tạo chat Gemini mới từ {parent_version.label}"
            status = "current"

        version_dir = Path(project.folder) / "versions" / version_id
        version_dir.mkdir(parents=True, exist_ok=True)
        placeholder_output = version_dir / "normalized.jpg"
        version = ThumbnailVersion(
            id=version_id,
            label=label,
            note=note,
            prompt=prompt,
            button_name=button.name,
            fields={str(key): value for key, value in field_values.items()},
            mask_mode=mask_mode,
            created_at=display_time(),
            status=status,
            source_image_path=parent_version.output_image_path,
            output_image_path=str(placeholder_output),
            thread_url=None,
            parent_version_id=parent_version.id,
        )
        for item in project.versions:
            if item.id == project.selected_version_id and item.status == "current":
                item.status = "history"
        project.versions.append(version)
        project.selected_version_id = version.id
        project.updated_at = utc_now()
        self._persist_locked()
        return version

    def _build_prompt(self, button: ThumbnailButton, field_values: dict) -> str:
        prompt = button.prompt_template
        for field in button.fields:
            value = field_values.get(field.key, field.value)
            if isinstance(value, list):
                value = ", ".join(map(str, value))
            prompt = prompt.replace(f"{{{field.key}}}", str(value))
        return prompt

    def _require_project(self, project_id: str) -> ThumbnailProject:
        project = self._projects.get(project_id)
        if project is None:
            raise ThumbnailPipelineError("Không tìm thấy project thumbnail.")
        return project

    def _require_version(self, project: ThumbnailProject, version_id: str) -> ThumbnailVersion:
        for version in project.versions:
            if version.id == version_id:
                return version
        raise ThumbnailPipelineError("Không tìm thấy version thumbnail.")

    def _require_button(self, button_id: str) -> ThumbnailButton:
        for button in self._buttons:
            if button.id == button_id:
                return button
        raise ThumbnailPipelineError("Không tìm thấy button thumbnail.")

    def _serialize_project_summary(self, project: ThumbnailProject) -> dict:
        return {
            "id": project.id,
            "name": project.name,
            "folder": project.folder,
            "sourceImagePath": project.source_image_path,
            "createdAt": project.created_at,
            "updatedAt": project.updated_at,
            "selectedVersionId": project.selected_version_id,
            "versionCount": len(project.versions),
        }

    def _serialize_project_detail(self, project: ThumbnailProject) -> dict:
        current_version = self._require_version(project, project.selected_version_id)
        return {
            **self._serialize_project_summary(project),
            "versions": [self._serialize_version(version) for version in project.versions],
            "currentVersion": self._serialize_version(current_version),
        }

    def _serialize_version(self, version: ThumbnailVersion) -> dict:
        return {
            "id": version.id,
            "label": version.label,
            "note": version.note,
            "prompt": version.prompt,
            "buttonName": version.button_name,
            "fields": version.fields,
            "maskMode": version.mask_mode,
            "createdAt": version.created_at,
            "status": version.status,
            "sourceImagePath": version.source_image_path,
            "outputImagePath": version.output_image_path,
            "threadUrl": version.thread_url,
            "parentVersionId": version.parent_version_id,
        }

    def _repair_legacy_image_path(self, raw_path: str) -> str:
        path = str(raw_path or "").strip()
        if not path:
            return path

        candidate = Path(path).expanduser()
        try:
            if candidate.exists():
                return str(candidate.resolve())
        except Exception:
            return path

        suffix = candidate.suffix.lower()
        if suffix == ".png":
            jpg_candidate = candidate.with_suffix(".jpg")
            jpeg_candidate = candidate.with_suffix(".jpeg")
            for fallback in (jpg_candidate, jpeg_candidate):
                try:
                    if fallback.exists():
                        return str(fallback.resolve())
                except Exception:
                    continue
        return path

    def _serialize_button(self, button: ThumbnailButton) -> dict:
        payload = asdict(button)
        payload["promptTemplate"] = payload.pop("prompt_template")
        payload["requiresMask"] = payload.pop("requires_mask")
        payload.pop("create_new_chat")
        payload["createNewChat"] = True
        payload["allowRegenerate"] = payload.pop("allow_regenerate")
        payload["isPinned"] = payload.pop("is_pinned")
        normalized_fields = []
        for field in payload["fields"]:
            field["visibleIf"] = field.pop("visible_if", None)
            normalized_fields.append(field)
        payload["fields"] = normalized_fields
        return payload

    def _serialize_profile(self, profile: ThumbnailProfile) -> dict:
        return {
            "id": profile.id,
            "name": profile.name,
            "icon": profile.icon,
            "description": profile.description,
            "isPinned": profile.is_pinned,
            "effects": [
                {
                    "buttonId": effect.button_id,
                    "fields": self._serialize_fields(effect.fields),
                }
                for effect in profile.effects
            ],
        }

    def _serialize_fields(self, fields: list[ThumbnailButtonField]) -> list[dict]:
        normalized_fields = []
        for field_item in fields:
            field_payload = asdict(field_item)
            field_payload["visibleIf"] = field_payload.pop("visible_if", None)
            normalized_fields.append(field_payload)
        return normalized_fields

    def _deserialize_button_field(
        self,
        field_data: dict,
        fallback: ThumbnailButtonField | None = None,
    ) -> ThumbnailButtonField:
        fallback_options = list(fallback.options) if fallback else []
        options = field_data.get("options", fallback_options)
        min_value = field_data.get("min", fallback.min if fallback else None)
        max_value = field_data.get("max", fallback.max if fallback else None)
        required_default = fallback.required if fallback else True
        return ThumbnailButtonField(
            key=str(field_data.get("key", fallback.key if fallback else "")).strip(),
            label=str(field_data.get("label", fallback.label if fallback else "")).strip(),
            type=str(field_data.get("type", fallback.type if fallback else "text")).strip(),
            value=field_data.get("value", fallback.value if fallback else ""),
            tooltip=str(field_data.get("tooltip", fallback.tooltip if fallback else "")).strip(),
            options=[str(option) for option in (options or [])],
            min=float(min_value) if min_value is not None else None,
            max=float(max_value) if max_value is not None else None,
            required=bool(field_data.get("required", field_data.get("isRequired", required_default))),
            visible_if=field_data.get("visible_if", field_data.get("visibleIf", fallback.visible_if if fallback else None)),
        )

    def _build_profile_effect(
        self,
        button_id: str,
        *,
        field_values: dict[str, str | int | float | bool | list] | None = None,
        field_payloads: list[dict] | None = None,
    ) -> ThumbnailProfileEffect:
        button = next((item for item in self._buttons if item.id == button_id), None)
        if field_payloads:
            if button:
                base_fields = {field.key: field for field in button.fields}
                fields = [
                    self._deserialize_button_field(
                        field_data,
                        fallback=base_fields.get(str(field_data.get("key", "")).strip()),
                    )
                    for field_data in field_payloads
                ]
            else:
                fields = [self._deserialize_button_field(field_data) for field_data in field_payloads]
        elif button:
            saved_values = dict(field_values or {})
            fields = [
                self._deserialize_button_field({"value": saved_values.get(field.key, field.value)}, fallback=field)
                for field in button.fields
            ]
        else:
            fields = []
        return ThumbnailProfileEffect(button_id=button_id, fields=fields)

    def _deserialize_profile_effects(self, payload: dict) -> list[ThumbnailProfileEffect]:
        effects_payload = payload.get("effects")
        if isinstance(effects_payload, list):
            effects: list[ThumbnailProfileEffect] = []
            for effect_data in effects_payload:
                button_id = str(effect_data.get("button_id", effect_data.get("buttonId", ""))).strip()
                if not button_id:
                    continue
                effects.append(
                    self._build_profile_effect(
                        button_id,
                        field_payloads=list(effect_data.get("fields") or []),
                    )
                )
            return effects

        legacy_items = payload.get("items") or []
        effects = []
        for item_data in legacy_items:
            button_id = str(item_data.get("button_id", item_data.get("buttonId", ""))).strip()
            if not button_id:
                continue
            effects.append(
                self._build_profile_effect(
                    button_id,
                    field_values=dict(item_data.get("field_values", item_data.get("fieldValues", {}))),
                )
            )
        return effects

    def _persist_locked(self) -> None:
        data = {
            "activeProjectId": self._active_project_id,
            "buttons": [asdict(button) for button in self._buttons],
            "projects": [asdict(project) for project in self._projects.values()],
            "profiles": [asdict(profile) for profile in self._profiles],
        }
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_state(self) -> None:
        self._projects_root.mkdir(parents=True, exist_ok=True)
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        self._debug_root.mkdir(parents=True, exist_ok=True)
        if not self._state_file.exists():
          return
        try:
            raw = json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception:
            return

        self._active_project_id = raw.get("activeProjectId")
        self._buttons = [
            ThumbnailButton(
                id=str(item.get("id", "")).strip(),
                name=str(item.get("name", "")).strip(),
                icon=str(item.get("icon", "")).strip(),
                category=str(item.get("category", "")).strip(),
                prompt_template=str(item.get("prompt_template", item.get("promptTemplate", ""))).strip(),
                requires_mask=bool(item.get("requires_mask", item.get("requiresMask", False))),
                create_new_chat=True,
                allow_regenerate=bool(item.get("allow_regenerate", item.get("allowRegenerate", True))),
                summary=str(item.get("summary", "")).strip(),
                is_pinned=bool(item.get("is_pinned", item.get("isPinned", False))),
                fields=[
                    ThumbnailButtonField(
                        key=str(field.get("key", "")).strip(),
                        label=str(field.get("label", "")).strip(),
                        type=str(field.get("type", "text")).strip(),
                        value=field.get("value", ""),
                        tooltip=str(field.get("tooltip", "")).strip(),
                        options=[str(option) for option in field.get("options", [])],
                        min=float(field["min"]) if field.get("min") is not None else None,
                        max=float(field["max"]) if field.get("max") is not None else None,
                        required=bool(field.get("required", field.get("isRequired", True))),
                        visible_if=field.get("visible_if", field.get("visibleIf")),
                    )
                    for field in item.get("fields", [])
                ],
            )
            for item in raw.get("buttons", [])
            if str(item.get("id", "")).strip()
        ] or default_buttons()
        self._merge_builtin_buttons()

        self._profiles = [
            ThumbnailProfile(
                id=str(p.get("id", "")).strip(),
                name=str(p.get("name", "")).strip(),
                icon=str(p.get("icon", "")).strip(),
                description=str(p.get("description", "")).strip(),
                is_pinned=bool(p.get("is_pinned", p.get("isPinned", False))),
                effects=self._deserialize_profile_effects(p),
            )
            for p in raw.get("profiles", [])
            if str(p.get("id", "")).strip()
        ] or self._profiles

        projects: dict[str, ThumbnailProject] = {}
        for item in raw.get("projects", []):
            versions = [
                ThumbnailVersion(
                    id=str(version.get("id", "")).strip(),
                    label=str(version.get("label", "")).strip(),
                    note=str(version.get("note", "")).strip(),
                    prompt=str(version.get("prompt", "")).strip(),
                    button_name=str(version.get("button_name", version.get("buttonName", ""))).strip(),
                    fields=dict(version.get("fields", {})),
                    mask_mode=str(version.get("mask_mode", version.get("maskMode", "none"))).strip() or "none",
                    created_at=str(version.get("created_at", version.get("createdAt", ""))).strip(),
                    status=str(version.get("status", "history")).strip() or "history",
                    source_image_path=self._repair_legacy_image_path(version.get("source_image_path", version.get("sourceImagePath", ""))),
                    output_image_path=self._repair_legacy_image_path(version.get("output_image_path", version.get("outputImagePath", ""))),
                    thread_url=version.get("thread_url", version.get("threadUrl")),
                    parent_version_id=version.get("parent_version_id", version.get("parentVersionId")),
                )
                for version in item.get("versions", [])
            ]
            project = ThumbnailProject(
                id=str(item.get("id", "")).strip(),
                name=str(item.get("name", "")).strip(),
                folder=str(item.get("folder", "")).strip(),
                source_image_path=self._repair_legacy_image_path(item.get("source_image_path", item.get("sourceImagePath", ""))),
                created_at=str(item.get("created_at", item.get("createdAt", utc_now()))).strip(),
                updated_at=str(item.get("updated_at", item.get("updatedAt", utc_now()))).strip(),
                selected_version_id=str(item.get("selected_version_id", item.get("selectedVersionId", "original"))).strip(),
                versions=versions,
            )
            if project.id:
                projects[project.id] = project
        self._projects = projects
        # Persist repaired legacy paths so the frontend stops requesting stale files.
        self._persist_locked()

    def _merge_builtin_buttons(self) -> None:
        builtin_map = {button.id: button for button in default_buttons()}
        merged_buttons: list[ThumbnailButton] = []
        seen_ids: set[str] = set()

        for button in self._buttons:
            builtin = builtin_map.get(button.id)
            if builtin is None:
                merged_buttons.append(button)
                seen_ids.add(button.id)
                continue

            field_map = {field.key: field for field in button.fields}
            merged_fields = list(button.fields)
            for builtin_field in builtin.fields:
                if builtin_field.key not in field_map:
                    merged_fields.append(builtin_field)

            if button.id == "extend-wide":
                legacy_prompt = "Extend this image to a clean 16:9 thumbnail composition.\nPreserve the subject scale, identity, and lighting.\nFill new space naturally for YouTube thumbnail framing."
                if not button.prompt_template or button.prompt_template == legacy_prompt or "{target_ratio}" not in button.prompt_template:
                    button.prompt_template = builtin.prompt_template
                if not button.name or button.name == "Extend 16:9":
                    button.name = builtin.name
                if not button.summary or button.summary == "Mở rộng khung hình sang 16:9 để chuẩn bị xuất thumbnail.":
                    button.summary = builtin.summary

            button.fields = merged_fields
            merged_buttons.append(button)
            seen_ids.add(button.id)

        for builtin in default_buttons():
            if builtin.id not in seen_ids:
                merged_buttons.append(builtin)

        self._buttons = merged_buttons

    def _get_adapter(self) -> GeminiWebAdapter:
        with self._lock:
            if self._adapter is None:
                self._runtime_root.mkdir(parents=True, exist_ok=True)
                self._adapter = GeminiWebAdapter(
                    runtime_root=self._runtime_root,
                    headless=False,
                    base_url=GEMINI_DEFAULT_URL,
                    response_timeout_ms=120_000,
                    model_name="gemini-2.5-flash",
                    debug_selector=True,
                    debug_root=self._debug_root,
                    max_tabs=1,
                )
            return self._adapter


thumbnail_pipeline = ThumbnailPipelineManager()
