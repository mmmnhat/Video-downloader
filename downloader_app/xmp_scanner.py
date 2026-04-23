from __future__ import annotations

import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TypedDict

from downloader_app.runtime import resolve_binary


class RawMarker(TypedDict):
    videoPath: str
    markerIndex: int
    timeSec: float
    name: str
    comment: str


class XmpScanner:
    def __init__(self):
        self.exiftool_cmd = resolve_binary("exiftool")
        self.ffmpeg_cmd = resolve_binary("ffmpeg")
        # Adobe Premiere default timebase for ticks
        self.ticks_per_second = 254016000000

    def scan_folder(self, folder_path: str) -> list[dict]:
        """
        Scans a folder for video files, extracts markers, and prepares a manifest-like list.
        """
        folder = Path(folder_path).expanduser().resolve()
        if not folder.exists() or not folder.is_dir():
            raise ValueError(f"Thu muc khong ton tai: {folder_path}")

        video_extensions = {".mp4", ".mov", ".mkv", ".avi", ".m4v"}
        results = []

        for file_path in folder.iterdir():
            if file_path.suffix.lower() in video_extensions:
                markers = self.extract_markers(file_path)
                if markers:
                    # Prepare images for markers
                    video_results = {
                        "name": file_path.name,
                        "video_path": str(file_path),
                        "mode": "chain",
                        "markers": []
                    }
                    
                    # Create a directory for frames
                    frames_dir = folder / "_frames" / file_path.stem
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
                            "seed_prompt": m['name'] + (f" ({m['comment']})" if m['comment'] else "")
                        })
                    
                    results.append(video_results)
        
        return results

    def extract_markers(self, video_path: Path) -> list[RawMarker]:
        """
        Tries sidecar .xmp first, then embedded XMP via exiftool.
        """
        # 1. Check sidecar
        sidecar_path = video_path.with_suffix(video_path.suffix + ".xmp")
        if not sidecar_path.exists():
            sidecar_path = video_path.with_suffix(".xmp")
        
        xml_content = None
        if sidecar_path.exists():
            try:
                xml_content = sidecar_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass

        # 2. Check embedded if no sidecar or no markers in sidecar
        markers = []
        if xml_content:
            markers = self.parse_markers_from_xml(xml_content, str(video_path))
        
        if not markers and self.exiftool_cmd:
            try:
                result = subprocess.run(
                    [self.exiftool_cmd, "-XMP", "-b", str(video_path)],
                    capture_output=True,
                    text=False,
                    check=False
                )
                if result.returncode == 0 and result.stdout:
                    embedded_xml = result.stdout.decode("utf-8", errors="ignore")
                    markers = self.parse_markers_from_xml(embedded_xml, str(video_path))
            except Exception:
                pass

        # 3. Fallback: Raw binary regex (if ExifTool is missing or failed)
        if not markers:
            try:
                embedded_xml = self._extract_xmp_from_binary(video_path)
                if embedded_xml:
                    markers = self.parse_markers_from_xml(embedded_xml, str(video_path))
            except Exception as e:
                print(f"[DEBUG] Raw XMP extraction failed: {e}")

        return markers

    def _extract_xmp_from_binary(self, file_path: Path) -> str | None:
        """
        Fallback to find XMP block directly in binary file using regex.
        Reads first 2MB and last 1MB of the file.
        """
        size = file_path.stat().st_size
        chunks = []
        
        with file_path.open("rb") as f:
            # Read first 2MB
            chunks.append(f.read(2 * 1024 * 1024))
            # Read last 1MB if file is large enough
            if size > 3 * 1024 * 1024:
                f.seek(-1024 * 1024, os.SEEK_END)
                chunks.append(f.read())
        
        combined = b"".join(chunks)
        # Search for xmpmeta or xpacket
        # We look for the <x:xmpmeta> block
        match = re.search(rb"(<x:xmpmeta.*?</x:xmpmeta>)", combined, re.DOTALL)
        if match:
            return match.group(1).decode("utf-8", errors="ignore")
        
        # Try xpacket as fallback
        match = re.search(rb"(<\?xpacket begin=.*?<\?xpacket end=.*?\?>)", combined, re.DOTALL)
        if match:
            return match.group(1).decode("utf-8", errors="ignore")
            
        return None

    def parse_markers_from_xml(self, xml_content: str, video_path: str) -> list[RawMarker]:
        """
        Parses Adobe XMP XML for markers.
        """
        markers = []
        try:
            # Adobe XMP often has garbage before/after the actual XML
            match = re.search(r"<x:xmpmeta.*?</x:xmpmeta>", xml_content, re.DOTALL)
            if not match:
                return []
            
            clean_xml = match.group(0)
            root = ET.fromstring(clean_xml)
            
            # Namespaces
            ns = {
                'x': 'adobe:ns:meta/',
                'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
                'xmpDM': 'http://ns.adobe.com/xmp/1.0/DynamicMedia/',
            }

            # Find xmpDM:markers
            # It's usually inside rdf:Description
            for markers_list in root.findall(".//xmpDM:markers/rdf:Seq/rdf:li", ns):
                # Some files use attributes instead of child elements
                name = markers_list.get(f"{{{ns['xmpDM']}}}name", "")
                start_time_raw = markers_list.get(f"{{{ns['xmpDM']}}}startTime", "0")
                comment = markers_list.get(f"{{{ns['xmpDM']}}}comment", "")
                
                # Check for child elements if not in attributes
                if not name:
                    name_elem = markers_list.find("xmpDM:name", ns)
                    if name_elem is not None:
                        name = name_elem.text or ""
                
                if start_time_raw == "0":
                    start_elem = markers_list.find("xmpDM:startTime", ns)
                    if start_elem is not None:
                        start_time_raw = start_elem.text or "0"

                if not comment:
                    comment_elem = markers_list.find("xmpDM:comment", ns)
                    if comment_elem is not None:
                        comment = comment_elem.text or ""

                time_sec = self.parse_adobe_time(start_time_raw)
                
                markers.append({
                    "videoPath": video_path,
                    "markerIndex": len(markers) + 1,
                    "timeSec": time_sec,
                    "name": name or f"Marker {len(markers) + 1}",
                    "comment": comment
                })

            # Sort by time
            markers.sort(key=lambda x: x["timeSec"])
        except Exception as e:
            print(f"[DEBUG] Error parsing XMP XML: {e}")
            
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
