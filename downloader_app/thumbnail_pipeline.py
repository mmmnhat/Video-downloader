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


def thumbnail_debug_root() -> Path:
    return THUMBNAIL_CACHE_ROOT / "debug"


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def display_time() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")


class ThumbnailPipelineError(RuntimeError):
    pass


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
    fields: list[ThumbnailButtonField] = field(default_factory=list)


@dataclass
class ThumbnailProfile:
    id: str
    name: str
    icon: str
    button_ids: list[str]
    description: str = ""


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
            name="Extend 16:9",
            icon="🖼️",
            category="Khung hình",
            prompt_template="Extend this image to a clean 16:9 thumbnail composition.\nPreserve the subject scale, identity, and lighting.\nFill new space naturally for YouTube thumbnail framing.",
            requires_mask=False,
            create_new_chat=True,
            allow_regenerate=True,
            summary="Mở rộng khung hình sang 16:9 để chuẩn bị xuất thumbnail.",
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
        self._profiles: list[ThumbnailProfile] = [
            ThumbnailProfile(
                id="funny_thumbnail",
                name="Funny Thumbnail",
                icon="🔥",
                button_ids=["extend-wide", "shock-face"], # Example combo
                description="Combo: Mở rộng + Biểu cảm sốc"
            ),
            ThumbnailProfile(
                id="cinematic_look",
                name="Cinematic Look",
                icon="🎬",
                button_ids=["remove-object", "extend-wide"],
                description="Combo: Xóa rác + Mở rộng 16:9"
            )
        ]
        self._adapter: GeminiWebAdapter | None = None
        self._load_state()

    def get_bootstrap(self) -> dict:
        with self._lock:
            return {
                "buttons": [self._serialize_button(button) for button in self._buttons],
                "projects": [self._serialize_project_summary(project) for project in self._projects.values()],
                "activeProjectId": self._active_project_id,
                "activeProject": self._serialize_project_detail(self._projects[self._active_project_id]) if self._active_project_id and self._active_project_id in self._projects else None,
                "profiles": [asdict(p) for p in self._profiles],
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
        project_dir = folder_path / sanitize_file_stem(project_name or project_id)
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
            self._active_project_id = project.id
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

    def create_button(self, payload: dict) -> dict:
        button_id = str(payload.get("id", "")).strip() or f"custom-{uuid.uuid4().hex[:8]}"
        button = ThumbnailButton(
            id=button_id,
            name=str(payload.get("name", "")).strip() or "Button mới",
            icon=str(payload.get("icon", "")).strip() or "✨",
            category=str(payload.get("category", "")).strip() or "Custom",
            prompt_template=str(payload.get("promptTemplate", "")).strip(),
            requires_mask=bool(payload.get("requiresMask", False)),
            create_new_chat=bool(payload.get("createNewChat", True)),
            allow_regenerate=bool(payload.get("allowRegenerate", True)),
            summary=str(payload.get("summary", "")).strip() or "Nút tùy biến do user tạo.",
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
                    required=bool(field.get("required", True)),
                    visible_if=field.get("visible_if") or field.get("visibleIf"),
                )
                for field in (payload.get("fields") or [])
            ],
        )
        if not button.prompt_template:
            raise ThumbnailPipelineError("Prompt template của button không được để trống.")
        with self._lock:
            self._buttons = [item for item in self._buttons if item.id != button.id]
            self._buttons.append(button)
            self._persist_locked()
            return self._serialize_button(button)

    def run_profile(self, payload: dict) -> dict:
        project_id = str(payload.get("project_id", "")).strip()
        profile_id = str(payload.get("profile_id", "")).strip()
        mask_base64 = str(payload.get("mask_base64", "")).strip()
        
        with self._lock:
            profile = next((p for p in self._profiles if p.id == profile_id), None)
            if not profile:
                raise ThumbnailPipelineError(f"Không tìm thấy profile: {profile_id}")
            
            combined_instructions = []
            buttons_map = {b.id: b for b in self._buttons}
            
            for idx, b_id in enumerate(profile.button_ids):
                btn = buttons_map.get(b_id)
                if btn:
                    # Build prompt with default field values
                    instr = self._build_prompt(btn, {f.key: f.value for f in btn.fields})
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

    def run_generation(self, payload: dict) -> dict:
        project_id = str(payload.get("project_id", "")).strip()
        button_id = str(payload.get("button_id", "")).strip()
        selected_mode = str(payload.get("selected_mode", "preset")).strip() or "preset"
        regenerate_mode = str(payload.get("regenerate_mode", "new-chat")).strip() or "new-chat"
        field_values = payload.get("field_values") or {}
        is_regenerate = bool(payload.get("is_regenerate", False))
        mask_mode = str(payload.get("mask_mode", "")).strip() or (
            "red" if selected_mode == "mask" else "none"
        )

        mask_base64 = str(payload.get("mask_base64", "")).strip()

        with self._lock:
            project = self._require_project(project_id)
            selected_version = self._require_version(project, project.selected_version_id)
            button = self._require_button(button_id)
            prompt = payload.get("prompt_override") or self._build_prompt(button, field_values)
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

        source_path = Path(selected_version.output_image_path).expanduser().resolve()
        output_dir = Path(next_version.output_image_path).parent
        
        # Handle mask compositing if provided
        input_image_for_gemini = source_path
        if mask_base64:
            import base64
            from PIL import Image
            import io
            
            try:
                if "," in mask_base64:
                    mask_base64 = mask_base64.split(",")[1]
                
                mask_data = base64.b64decode(mask_base64)
                mask_img = Image.open(io.BytesIO(mask_data)).convert("RGBA")
                base_img = Image.open(source_path).convert("RGBA")
                
                # Resize mask to match base image if necessary
                if mask_img.size != base_img.size:
                    mask_img = mask_img.resize(base_img.size, Image.Resampling.LANCZOS)
                
                composite = Image.alpha_composite(base_img, mask_img)
                composite_rgb = composite.convert("RGB")
                
                masked_source_path = output_dir / "masked_input.jpg"
                composite_rgb.save(masked_source_path, "JPEG", quality=95)
                input_image_for_gemini = masked_source_path
            except Exception as e:
                print(f"[DEBUG] Failed to composite mask: {e}")

        preview_path = output_dir / "preview.jpg"
        normalized_path = output_dir / "normalized.jpg"

        adapter = self._get_adapter()
        result = adapter.generate(
            prompt=prompt,
            input_image_path=input_image_for_gemini,
            preview_path=preview_path,
            normalized_path=normalized_path,
            context={
                "mode": "regenerate" if is_regenerate else "auto",
                "threadUrl": None if button.create_new_chat or regenerate_mode == "new-chat" else selected_version.thread_url,
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
            project.selected_version_id = stored_version.id
            project.updated_at = utc_now()
            self._persist_locked()
            return self._serialize_project_detail(project)

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
                from PIL import Image
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

    def get_project_detail(self, project_id: str) -> dict | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                return None
            return self._serialize_project_detail(project)

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
            note = (
                f"Chạy lại prompt bằng chat Gemini mới từ {parent_version.label}"
                if regenerate_mode == "new-chat"
                else f"Chạy lại prompt trong cùng chat của {parent_version.label}"
            )
            status = "branch"
        else:
            version_id = f"v{base_count}"
            label = f"Version {base_count} - {button.name}"
            note = (
                f"Tạo chat Gemini mới từ {parent_version.label}"
                if button.create_new_chat
                else f"Tiếp tục chỉnh trong chat của {parent_version.label}"
            )
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

    def _serialize_button(self, button: ThumbnailButton) -> dict:
        payload = asdict(button)
        payload["promptTemplate"] = payload.pop("prompt_template")
        payload["requiresMask"] = payload.pop("requires_mask")
        payload["createNewChat"] = payload.pop("create_new_chat")
        payload["allowRegenerate"] = payload.pop("allow_regenerate")
        normalized_fields = []
        for field in payload["fields"]:
            field["visibleIf"] = field.pop("visible_if", None)
            normalized_fields.append(field)
        payload["fields"] = normalized_fields
        return payload

    def _persist_locked(self) -> None:
        data = {
            "activeProjectId": self._active_project_id,
            "buttons": [asdict(button) for button in self._buttons],
            "projects": [asdict(project) for project in self._projects.values()],
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
                create_new_chat=bool(item.get("create_new_chat", item.get("createNewChat", True))),
                allow_regenerate=bool(item.get("allow_regenerate", item.get("allowRegenerate", True))),
                summary=str(item.get("summary", "")).strip(),
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
                    source_image_path=str(version.get("source_image_path", version.get("sourceImagePath", ""))).strip(),
                    output_image_path=str(version.get("output_image_path", version.get("outputImagePath", ""))).strip(),
                    thread_url=version.get("thread_url", version.get("threadUrl")),
                    parent_version_id=version.get("parent_version_id", version.get("parentVersionId")),
                )
                for version in item.get("versions", [])
            ]
            project = ThumbnailProject(
                id=str(item.get("id", "")).strip(),
                name=str(item.get("name", "")).strip(),
                folder=str(item.get("folder", "")).strip(),
                source_image_path=str(item.get("source_image_path", item.get("sourceImagePath", ""))).strip(),
                created_at=str(item.get("created_at", item.get("createdAt", utc_now()))).strip(),
                updated_at=str(item.get("updated_at", item.get("updatedAt", utc_now()))).strip(),
                selected_version_id=str(item.get("selected_version_id", item.get("selectedVersionId", "original"))).strip(),
                versions=versions,
            )
            if project.id:
                projects[project.id] = project
        self._projects = projects

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
