from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, TypedDict

from downloader_app.runtime import resolve_binary


class RawMarker(TypedDict):
    videoPath: str
    markerIndex: int
    timeSec: float
    name: str
    comment: str


class XmpScanDiagnostics(TypedDict):
    folder: str
    video_files: list[str]
    xmp_files: list[str]
    videos_with_markers: list[str]
    videos_without_markers: list[str]
    orphan_xmp_files: list[str]


class XmpScanner:
    def __init__(self):
        self.exiftool_cmd = resolve_binary("exiftool")
        self.ffmpeg_cmd = resolve_binary("ffmpeg")
        # Adobe Premiere default timebase for ticks
        self.ticks_per_second = 254016000000
        self.last_scan_diagnostics: XmpScanDiagnostics | None = None
        self._logged_missing_exiftool = False

    def scan_folder(self, folder_path: str) -> tuple[list[dict], XmpScanDiagnostics]:
        """
        Scans a folder for video files, extracts markers, and prepares a manifest-like list.
        """
        folder = Path(folder_path).expanduser().resolve()
        if not folder.exists() or not folder.is_dir():
            raise ValueError(f"Thu muc khong ton tai: {folder_path}")

        video_extensions = {".mp4", ".mov", ".mkv", ".avi", ".m4v"}
        results = []
        video_files = sorted(
            file_path
            for file_path in folder.rglob("*")
            if file_path.is_file()
            and file_path.suffix.lower() in video_extensions
            and not self._should_skip_path(file_path, folder)
        )
        xmp_files = sorted(
            file_path
            for file_path in folder.rglob("*")
            if file_path.is_file()
            and file_path.suffix.lower() == ".xmp"
            and not self._should_skip_path(file_path, folder)
        )
        xmp_index = self._build_xmp_index(xmp_files)
        videos_with_markers: list[str] = []
        videos_without_markers: list[str] = []

        for file_path in video_files:
            markers = self.extract_markers(file_path, xmp_index=xmp_index)
            relative_video = self._relative_display_path(file_path, folder)
            if not markers:
                videos_without_markers.append(relative_video)
                continue

            # Prepare images for markers
            video_results = {
                "name": relative_video,
                "video_path": str(file_path),
                "mode": "chain",
                "video_prompt": "",
                "markers": []
            }

            # Mirror subfolders to avoid collisions between same-named clips.
            frames_dir = folder / "_frames" / file_path.relative_to(folder).with_suffix("")
            frames_dir.mkdir(parents=True, exist_ok=True)

            prepared_markers: list[dict] = []
            for idx, m in enumerate(markers, start=1):
                frame_filename = f"marker_{idx:03d}_{m['timeSec']:.2f}.jpg"
                frame_path = frames_dir / frame_filename

                # Capture frame if it doesn't exist yet.
                # Do not fail the whole folder scan for one marker capture error.
                if not frame_path.exists() or frame_path.stat().st_size <= 0:
                    try:
                        self.capture_frame(str(file_path), m["timeSec"], str(frame_path))
                    except Exception as exc:
                        print(f"[DEBUG] Skip marker {idx} for {file_path.name}: {exc}")

                if not frame_path.exists() or frame_path.stat().st_size <= 0:
                    # Fallback: reuse previous successful frame to keep marker alignment.
                    if prepared_markers:
                        prev_frame = Path(prepared_markers[-1]["input_frame"])
                        if prev_frame.exists() and prev_frame.stat().st_size > 0:
                            try:
                                shutil.copy2(prev_frame, frame_path)
                            except Exception:
                                pass

                if not frame_path.exists() or frame_path.stat().st_size <= 0:
                    continue

                prepared_markers.append({
                    "index": idx,
                    "name": m["name"],
                    "comment": m["comment"],
                    "timestamp_ms": int(m["timeSec"] * 1000),
                    "input_frame": str(frame_path),
                    "seed_prompt": (m["name"] or f"Marker {idx}").strip(),
                    "steps": [
                        {
                            "title": (m["name"] or f"Marker {idx}").strip(),
                            "modifier_prompt": (m["comment"] or "").strip(),
                        }
                    ],
                })

            if prepared_markers:
                video_results["markers"] = prepared_markers
                videos_with_markers.append(relative_video)
                results.append(video_results)
            else:
                videos_without_markers.append(relative_video)

        orphan_xmp_files = [
            self._relative_display_path(xmp_path, folder)
            for xmp_path in xmp_files
            if not self._find_matching_video_path(xmp_path, video_files)
        ]
        diagnostics: XmpScanDiagnostics = {
            "folder": str(folder),
            "video_files": [self._relative_display_path(path, folder) for path in video_files],
            "xmp_files": [self._relative_display_path(path, folder) for path in xmp_files],
            "videos_with_markers": videos_with_markers,
            "videos_without_markers": videos_without_markers,
            "orphan_xmp_files": orphan_xmp_files,
        }
        self.last_scan_diagnostics = diagnostics
        return results, diagnostics

    def _should_skip_path(self, file_path: Path, root_folder: Path) -> bool:
        relative_parts = file_path.relative_to(root_folder).parts
        return any(part in {"_frames", ".git", "node_modules", "__pycache__"} for part in relative_parts)

    def _relative_display_path(self, file_path: Path, root_folder: Path) -> str:
        relative = file_path.relative_to(root_folder)
        return relative.as_posix()

    def _find_matching_video_path(self, xmp_path: Path, video_files: list[Path]) -> Path | None:
        xmp_name = xmp_path.name.lower()
        xmp_stem = xmp_path.stem.lower()
        for video_path in video_files:
            video_name = video_path.name.lower()
            if xmp_name == f"{video_name}.xmp" or xmp_stem == video_path.stem.lower():
                return video_path
        return None

    def _build_xmp_index(self, xmp_files: Iterable[Path]) -> dict[str, list[Path]]:
        index: dict[str, list[Path]] = {}
        for xmp_path in xmp_files:
            exact_name = xmp_path.name.lower()
            stem_name = xmp_path.stem.lower()
            index.setdefault(exact_name, []).append(xmp_path)
            index.setdefault(stem_name, []).append(xmp_path)
        return index

    def _candidate_sidecar_paths(self, video_path: Path, xmp_index: dict[str, list[Path]] | None = None) -> list[Path]:
        candidates: list[Path] = []
        seen: set[Path] = set()

        def add(path: Path) -> None:
            if path in seen:
                return
            seen.add(path)
            candidates.append(path)

        adjacent_candidates = [
            video_path.with_suffix(video_path.suffix + ".xmp"),
            video_path.with_suffix(".xmp"),
        ]
        for path in adjacent_candidates:
            if path.exists():
                add(path)

        if xmp_index:
            for key in (f"{video_path.name.lower()}.xmp", video_path.stem.lower()):
                for xmp_path in xmp_index.get(key, []):
                    if xmp_path.exists():
                        add(xmp_path)

        return candidates

    def extract_markers(self, video_path: Path, xmp_index: dict[str, list[Path]] | None = None) -> list[RawMarker]:
        """
        Tries sidecar .xmp first, then embedded XMP via exiftool.
        """
        sidecar_paths = self._candidate_sidecar_paths(video_path, xmp_index=xmp_index)

        # 1. Check sidecar(s)
        markers = []
        for sidecar_path in sidecar_paths:
            xml_content = None
            try:
                xml_content = sidecar_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            if not xml_content:
                continue

            markers = self.parse_markers_from_xml(xml_content, str(video_path))
            if markers:
                print(f"[DEBUG] Found {len(markers)} markers in sidecar XMP for {video_path.name}: {sidecar_path}")
                break

        # 2. Check embedded if no sidecar or no markers in sidecar
        if not markers and self.exiftool_cmd:
            try:
                print(f"[DEBUG] Trying ExifTool for {video_path.name}...")
                result = subprocess.run(
                    [self.exiftool_cmd, "-XMP", "-b", str(video_path)],
                    capture_output=True,
                    text=False,
                    check=False
                )
                if result.returncode == 0 and result.stdout:
                    embedded_xml = result.stdout.decode("utf-8", errors="ignore")
                    markers = self.parse_markers_from_xml(embedded_xml, str(video_path))
                    if markers:
                        print(f"[DEBUG] Found {len(markers)} markers via ExifTool for {video_path.name}")
            except Exception as e:
                print(f"[DEBUG] ExifTool failed for {video_path.name}: {e}")
        elif not markers and not self.exiftool_cmd and not self._logged_missing_exiftool:
            print("[DEBUG] ExifTool khong co san; bo qua doc embedded XMP va chi thu raw binary scan.")
            self._logged_missing_exiftool = True
        
        if not markers:
            try:
                print(f"[DEBUG] Trying raw binary XMP extraction for {video_path.name}...")
                xml_blocks = self._extract_xmp_from_binary(video_path)
                for embedded_xml in xml_blocks:
                    block_markers = self.parse_markers_from_xml(embedded_xml, str(video_path))
                    if block_markers:
                        markers.extend(block_markers)
                
                if markers:
                    # Remove duplicates and sort
                    seen_times = set()
                    unique_markers = []
                    for m in sorted(markers, key=lambda x: x["timeSec"]):
                        if m["timeSec"] not in seen_times:
                            unique_markers.append(m)
                            seen_times.add(m["timeSec"])
                    markers = unique_markers
                    print(f"[DEBUG] Found {len(markers)} markers via raw binary scan for {video_path.name}")
            except Exception as e:
                print(f"[DEBUG] Raw XMP extraction failed for {video_path.name}: {e}")

        if not markers:
            print(f"[DEBUG] No markers found for {video_path.name}")
        return markers

    def _extract_xmp_from_binary(self, file_path: Path) -> list[str]:
        """
        Extracts ALL potential XMP XML blocks from binary file.
        """
        size = file_path.stat().st_size
        chunks = []
        
        with file_path.open("rb") as f:
            # Read first 8MB (markers can be further in for large 4K files)
            chunks.append(f.read(8 * 1024 * 1024))
            # Read last 4MB
            if size > 12 * 1024 * 1024:
                f.seek(-4 * 1024 * 1024, os.SEEK_END)
                chunks.append(f.read())
        
        combined = b"".join(chunks)
        blocks = []
        
        # Search for xmpmeta blocks
        for match in re.finditer(rb"(<(?:[a-zA-Z0-9]+:)?xmpmeta.*?</(?:[a-zA-Z0-9]+:)?xmpmeta>)", combined, re.DOTALL | re.IGNORECASE):
            blocks.append(match.group(1).decode("utf-8", errors="ignore"))
        
        # Try xpacket as fallback if no xmpmeta found
        if not blocks:
            for match in re.finditer(rb"(<\?xpacket begin=.*?<\?xpacket end=.*?\?>)", combined, re.DOTALL | re.IGNORECASE):
                blocks.append(match.group(1).decode("utf-8", errors="ignore"))
            
        # Try rdf:RDF directly if still nothing
        if not blocks:
            for match in re.finditer(rb"(<rdf:RDF.*?</rdf:RDF>)", combined, re.DOTALL | re.IGNORECASE):
                blocks.append(match.group(1).decode("utf-8", errors="ignore"))
            
        return blocks

    def parse_markers_from_xml(self, xml_content: str, video_path: str) -> list[RawMarker]:
        """
        Parses Adobe XMP XML for markers.
        """
        markers = []
        try:
            # Adobe XMP often has garbage before/after the actual XML
            # We try to find xmpmeta block, then fallback to rdf:RDF block.
            match = re.search(r"<(?:[a-zA-Z0-9]+:)?xmpmeta.*?</(?:[a-zA-Z0-9]+:)?xmpmeta>", xml_content, re.DOTALL | re.IGNORECASE)
            if match:
                clean_xml = match.group(0)
            else:
                match = re.search(r"<rdf:RDF.*?</rdf:RDF>", xml_content, re.DOTALL | re.IGNORECASE)
                if match:
                    clean_xml = match.group(0)
                else:
                    # If we have something that looks like XML but no root found, try parsing directly
                    stripped = xml_content.strip()
                    if stripped.startswith("<") and stripped.endswith(">"):
                        clean_xml = stripped
                    else:
                        return []
            
            root = ET.fromstring(clean_xml)
            
            # Namespaces
            ns = {
                "x": "adobe:ns:meta/",
                "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                "xmpDM": "http://ns.adobe.com/xmp/1.0/DynamicMedia/",
                "xmp": "http://ns.adobe.com/xap/1.0/",
            }

            duration_seconds = self._extract_duration_seconds(root, ns)

            # Prefer marker nodes scoped by track so we can read per-track frameRate.
            marker_nodes_with_fps: list[tuple[ET.Element, float | None]] = []
            for track_desc in root.findall(".//xmpDM:Tracks//rdf:Description", ns):
                fps = self._parse_frame_rate(track_desc.get(f"{{{ns['xmpDM']}}}frameRate", ""))
                for marker_node in track_desc.findall("./xmpDM:markers/rdf:Seq/rdf:li", ns):
                    marker_nodes_with_fps.append((marker_node, fps))

            if not marker_nodes_with_fps:
                marker_nodes_with_fps = [
                    (marker_node, None)
                    for marker_node in root.findall(".//xmpDM:markers/rdf:Seq/rdf:li", ns)
                ]
                if not marker_nodes_with_fps:
                    marker_nodes_with_fps = [
                        (marker_node, None)
                        for marker_node in root.findall(".//xmp:Markers//rdf:li", ns)
                    ]

            for marker_node, fps in marker_nodes_with_fps:
                name = self._extract_marker_field(marker_node, "name", ns)
                start_time_raw = self._extract_marker_field(marker_node, "startTime", ns)
                comment = self._extract_marker_field(marker_node, "comment", ns)
                if not start_time_raw:
                    continue

                time_sec = self.parse_adobe_time(start_time_raw, frame_rate=fps)
                time_sec = self._coerce_time_with_duration(
                    raw=start_time_raw,
                    parsed_seconds=time_sec,
                    duration_seconds=duration_seconds,
                    frame_rate=fps,
                )

                markers.append({
                    "videoPath": video_path,
                    "markerIndex": len(markers) + 1,
                    "timeSec": time_sec,
                    "name": name or f"Marker {len(markers) + 1}",
                    "comment": comment,
                })
                print(f"[DEBUG] Parsed marker: '{name}' at {time_sec}s")

            # Sort by time
            markers.sort(key=lambda x: x["timeSec"])
        except Exception as e:
            print(f"[DEBUG] Error parsing XMP XML for {video_path}: {e}")
            import traceback
            traceback.print_exc()
            
        return markers

    def _extract_duration_seconds(self, root: ET.Element, ns: dict[str, str]) -> float | None:
        duration_elem = root.find(".//xmpDM:duration", ns)
        if duration_elem is None:
            return None
        raw_value = str(duration_elem.get(f"{{{ns['xmpDM']}}}value", "")).strip()
        raw_scale = str(duration_elem.get(f"{{{ns['xmpDM']}}}scale", "")).strip()
        if not raw_value:
            return None
        try:
            value = float(raw_value)
        except ValueError:
            return None

        if raw_scale and "/" in raw_scale:
            try:
                numerator_text, denominator_text = raw_scale.split("/", 1)
                numerator = float(numerator_text.strip() or "0")
                denominator = float(denominator_text.strip() or "0")
                if denominator > 0:
                    return value * (numerator / denominator)
            except ValueError:
                pass

        if raw_scale:
            try:
                scale = float(raw_scale)
                return value * scale
            except ValueError:
                pass

        return value / 1000.0

    def _parse_frame_rate(self, raw: str) -> float | None:
        text = str(raw or "").strip().lower()
        if not text:
            return None
        if text.startswith("f"):
            text = text[1:].strip()
        if not text:
            return None

        if "/" in text:
            try:
                numerator_text, denominator_text = text.split("/", 1)
                numerator = float(numerator_text.strip() or "0")
                denominator = float(denominator_text.strip() or "0")
                if denominator > 0:
                    return numerator / denominator
            except ValueError:
                return None

        try:
            fps = float(text)
        except ValueError:
            return None
        if fps <= 0:
            return None
        return fps

    def _coerce_time_with_duration(
        self,
        *,
        raw: str,
        parsed_seconds: float,
        duration_seconds: float | None,
        frame_rate: float | None,
    ) -> float:
        if duration_seconds is None or duration_seconds <= 0:
            return max(0.0, parsed_seconds)
        if parsed_seconds <= duration_seconds + 0.5:
            return max(0.0, parsed_seconds)

        text = str(raw or "").strip()
        if not text:
            return max(0.0, parsed_seconds)
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text):
            return max(0.0, parsed_seconds)

        if frame_rate and frame_rate > 0:
            try:
                frame_based = float(text) / frame_rate
                if frame_based <= duration_seconds + 0.5:
                    return max(0.0, frame_based)
            except ValueError:
                pass

        try:
            ms_based = float(text) / 1000.0
            if ms_based <= duration_seconds + 0.5:
                return max(0.0, ms_based)
        except ValueError:
            pass

        try:
            ticks_based = float(text) / self.ticks_per_second
            if ticks_based <= duration_seconds + 0.5:
                return max(0.0, ticks_based)
        except ValueError:
            pass

        return max(0.0, parsed_seconds)

    def _extract_marker_field(self, marker_node: ET.Element, field_name: str, ns: dict[str, str]) -> str:
        candidate_namespaces = [ns["xmpDM"]]
        xmp_ns = ns.get("xmp")
        if xmp_ns:
            candidate_namespaces.append(xmp_ns)

        for namespace in candidate_namespaces:
            direct_attr = marker_node.get(f"{{{namespace}}}{field_name}", "")
            if direct_attr:
                return direct_attr.strip()

        for prefix in ("xmpDM", "xmp"):
            direct_child = marker_node.find(f"{prefix}:{field_name}", ns)
            if direct_child is not None and direct_child.text:
                value = direct_child.text.strip()
                if value:
                    return value

        nested_desc = marker_node.find(".//rdf:Description", ns)
        if nested_desc is not None:
            for namespace in candidate_namespaces:
                nested_attr = nested_desc.get(f"{{{namespace}}}{field_name}", "")
                if nested_attr:
                    return nested_attr.strip()

            for prefix in ("xmpDM", "xmp"):
                nested_child = nested_desc.find(f"{prefix}:{field_name}", ns)
                if nested_child is not None and nested_child.text:
                    value = nested_child.text.strip()
                    if value:
                        return value

        wanted = field_name.lower()
        for elem in marker_node.iter():
            if not isinstance(elem.tag, str):
                continue
            local_name = elem.tag.split("}", 1)[-1].lower()
            if local_name == wanted and elem.text:
                value = elem.text.strip()
                if value:
                    return value
        return ""

    def parse_adobe_time(self, time_raw: str, frame_rate: float | None = None) -> float:
        """
        Adobe time can be:
        - Plain number (ticks)
        - Format like "12345f254016000000" (value + f + timebase)
        """
        if not time_raw:
            return 0.0

        raw = str(time_raw).strip()
        if not raw:
            return 0.0

        if "/" in raw:
            parts = [part.strip() for part in raw.split("/", 1)]
            if len(parts) == 2:
                try:
                    value = float(parts[0])
                    base = float(parts[1])
                    if base > 0:
                        return value / base
                except ValueError:
                    pass

        f_match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*[fF]\s*([0-9]+(?:\.[0-9]+)?)\s*", raw)
        if f_match:
            try:
                value = float(f_match.group(1))
                base = float(f_match.group(2))
                if base > 0:
                    return value / base
            except ValueError:
                pass

        if ":" in raw or ";" in raw:
            normalized = raw.replace(";", ":")
            parts = normalized.split(":")
            try:
                if len(parts) == 4:
                    hh, mm, ss, ff = [float(part.strip() or "0") for part in parts]
                    return hh * 3600.0 + mm * 60.0 + ss + (ff / 30.0)
                if len(parts) == 3:
                    hh, mm, ss = [float(part.strip() or "0") for part in parts]
                    return hh * 3600.0 + mm * 60.0 + ss
                if len(parts) == 2:
                    mm, ss = [float(part.strip() or "0") for part in parts]
                    return mm * 60.0 + ss
            except ValueError:
                pass

        try:
            numeric = float(raw)
        except ValueError:
            return 0.0

        if frame_rate and frame_rate > 0 and re.fullmatch(r"[0-9]+", raw):
            return max(0.0, numeric / frame_rate)

        if numeric >= (self.ticks_per_second / 10):
            return numeric / self.ticks_per_second

        return max(0.0, numeric)

    def capture_frame(self, video_path: str, timestamp_sec: float, output_path: str):
        """
        Captures a frame at a specific timestamp using FFmpeg.
        """
        if not self.ffmpeg_cmd:
            raise RuntimeError("Khong tim thay ffmpeg. Hay dam bao ffmpeg co trong PATH hoac thu muc vendor.")
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        def _run_capture(ts: float) -> tuple[bool, str]:
            cmd = [
                self.ffmpeg_cmd,
                "-y",
                "-hide_banner",
                "-loglevel", "error",
                "-ss", str(max(0.0, ts)),
                "-i", video_path,
                "-frames:v", "1",
                "-update", "1",
                "-q:v", "2",
                output_path,
            ]

            kwargs = {}
            if os.name == "nt":
                kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

            completed = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                **kwargs,
            )
            stderr_text = (completed.stderr or "").strip()
            if completed.returncode != 0:
                return False, stderr_text
            if not out_path.exists() or out_path.stat().st_size <= 0:
                return False, stderr_text or "FFmpeg khong tao duoc frame output."
            return True, stderr_text

        timestamp_candidates = [float(timestamp_sec), max(0.0, float(timestamp_sec) - 0.2), 0.0]
        seen: set[float] = set()
        unique_candidates: list[float] = []
        for value in timestamp_candidates:
            rounded = round(value, 3)
            if rounded in seen:
                continue
            seen.add(rounded)
            unique_candidates.append(value)

        last_error = ""
        for ts in unique_candidates:
            ok, err = _run_capture(ts)
            if ok:
                return
            if err:
                last_error = err

        detail = last_error or "Khong ro nguyen nhan."
        print(f"[DEBUG] FFmpeg frame capture failed: {detail}")
        raise RuntimeError(f"FFmpeg failed to capture frame: {detail}")


# Singleton instance
xmp_scanner = XmpScanner()
