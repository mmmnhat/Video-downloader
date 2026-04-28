from __future__ import annotations

import json
import os
import re
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

            videos_with_markers.append(relative_video)
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

            for idx, m in enumerate(markers, start=1):
                frame_filename = f"marker_{idx:03d}_{m['timeSec']:.2f}.jpg"
                frame_path = frames_dir / frame_filename

                # Capture frame if it doesn't exist
                if not frame_path.exists():
                    self.capture_frame(str(file_path), m['timeSec'], str(frame_path))

                video_results["markers"].append({
                    "index": idx,
                    "name": m['name'],
                    "comment": m['comment'],
                    "timestamp_ms": int(m['timeSec'] * 1000),
                    "input_frame": str(frame_path),
                    "seed_prompt": (m['name'] or f"Marker {idx}").strip(),
                    "steps": [
                        {
                            "title": (m['name'] or f"Marker {idx}").strip(),
                            "modifier_prompt": (m['comment'] or "").strip(),
                        }
                    ],
                })

            results.append(video_results)

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
            # We try to find xmpmeta block, then fallback to rdf:RDF block
            match = re.search(r"<(?:x:)?xmpmeta.*?</(?:x:)?xmpmeta>", xml_content, re.DOTALL | re.IGNORECASE)
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
                'x': 'adobe:ns:meta/',
                'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
                'xmpDM': 'http://ns.adobe.com/xmp/1.0/DynamicMedia/',
                'xmp': 'http://ns.adobe.com/xap/1.0/',
            }

            # 1. Standard Adobe markers (xmpDM:markers or xmp:Markers)
            marker_list_elements = root.findall(".//xmpDM:markers//rdf:li", ns)
            if not marker_list_elements:
                marker_list_elements = root.findall(".//xmp:Markers//rdf:li", ns)
            
            # 2. Tracks markers (xmpDM:Tracks -> xmpDM:Track -> xmpDM:markers)
            if not marker_list_elements:
                marker_list_elements = root.findall(".//xmpDM:Track/xmpDM:markers/rdf:Seq/rdf:li", ns)
            
            # 3. Flexible search for any element that looks like a marker
            if not marker_list_elements:
                # Look for li elements that have a startTime either as attribute or child
                all_li = root.findall(".//rdf:li", ns)
                for li in all_li:
                    has_start = any(li.get(f"{{{ns[p]}}}startTime") for p in ["xmpDM", "xmp"])
                    if not has_start:
                        has_start = any(li.find(f"{p}:startTime", ns) is not None for p in ["xmpDM", "xmp"])
                    
                    if has_start:
                        marker_list_elements.append(li)
            
            if not marker_list_elements:
                # Final desperate attempt: find ANY element with startTime (even if not in rdf:li)
                for p in ["xmpDM", "xmp"]:
                    starts = root.findall(f".//{{{ns[p]}}}startTime", ns) # As attribute? No, findall is for elements
                    # Try finding elements that HAVE the attribute
                    for elem in root.iter():
                        if elem.get(f"{{{ns[p]}}}startTime"):
                            marker_list_elements.append(elem)
                        # Or are the startTime element themselves (meaning the parent is the marker)
                        # But that's handled by finding child elements later.
                
                # Deduplicate
                unique_elems = []
                seen_id = set()
                for e in marker_list_elements:
                    if id(e) not in seen_id:
                        unique_elems.append(e)
                        seen_id.add(id(e))
                marker_list_elements = unique_elems
            
            for markers_list in marker_list_elements:
                # Check for various possible tag names for name, startTime, and comment
                # They can be in attributes or child elements, and can use different namespaces
                
                name = ""
                start_time_raw = ""
                comment = ""
                
                # 1. Try attributes
                for prefix in ["xmpDM", "xmp"]:
                    p_ns = ns[prefix]
                    if not name:
                        name = markers_list.get(f"{{{p_ns}}}name", "")
                    if not start_time_raw:
                        start_time_raw = markers_list.get(f"{{{p_ns}}}startTime", "")
                    if not comment:
                        comment = markers_list.get(f"{{{p_ns}}}comment", "")
                
                # 2. Try child elements
                if not name:
                    for tag in ["xmpDM:name", "xmp:name", "name"]:
                        elem = markers_list.find(tag, ns)
                        if elem is not None:
                            name = elem.text or ""
                            break
                
                if not start_time_raw or start_time_raw == "0":
                    for tag in ["xmpDM:startTime", "xmp:startTime", "startTime"]:
                        elem = markers_list.find(tag, ns)
                        if elem is not None:
                            start_time_raw = elem.text or ""
                            break
                
                if not comment:
                    for tag in ["xmpDM:comment", "xmp:comment", "comment"]:
                        elem = markers_list.find(tag, ns)
                        if elem is not None:
                            comment = elem.text or ""
                            break

                # Skip if no valid start time found
                if not start_time_raw:
                    continue
                    
                try:
                    time_sec = self.parse_adobe_time(start_time_raw)
                except Exception:
                    continue
                
                markers.append({
                    "videoPath": video_path,
                    "markerIndex": len(markers) + 1,
                    "timeSec": time_sec,
                    "name": name or f"Marker {len(markers) + 1}",
                    "comment": comment
                })
                print(f"[DEBUG] Parsed marker: '{name}' at {time_sec}s")

            # Sort by time
            markers.sort(key=lambda x: x["timeSec"])
        except Exception as e:
            print(f"[DEBUG] Error parsing XMP XML for {video_path}: {e}")
            import traceback
            traceback.print_exc()
            
        return markers

    def parse_adobe_time(self, time_raw: str) -> float:
        """
        Adobe time can be:
        - Plain number (ticks)
        - Format like "12345f254016000000" (value + f + timebase)
        """
        if not time_raw:
            return 0.0
        
        if 'f' in time_raw:
            parts = time_raw.split('f')
            try:
                value = int(parts[0])
                base = int(parts[1])
                return value / base
            except (ValueError, IndexError):
                return 0.0
        
        try:
            # Assume ticks
            return int(time_raw) / self.ticks_per_second
        except ValueError:
            return 0.0

    def capture_frame(self, video_path: str, timestamp_sec: float, output_path: str):
        """
        Captures a frame at a specific timestamp using FFmpeg.
        """
        if not self.ffmpeg_cmd:
            raise RuntimeError("Khong tim thay ffmpeg. Hay dam bao ffmpeg co trong PATH hoac thu muc vendor.")

        # Command: ffmpeg -ss [time] -i [video] -frames:v 1 -q:v 2 [output]
        # We use -ss before -i for fast seeking
        cmd = [
            self.ffmpeg_cmd,
            "-y",
            "-ss", str(timestamp_sec),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            output_path
        ]
        
        try:
            # creationflags to hide window on Windows
            kwargs = {}
            if os.name == "nt":
                kwargs["creationflags"] = 0x08000000 # CREATE_NO_WINDOW
            
            subprocess.run(cmd, check=True, capture_output=True, **kwargs)
        except subprocess.CalledProcessError as e:
            print(f"[DEBUG] FFmpeg frame capture failed: {e.stderr.decode()}")
            raise RuntimeError(f"FFmpeg failed to capture frame: {e.stderr.decode()}")


# Singleton instance
xmp_scanner = XmpScanner()
