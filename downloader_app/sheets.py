from __future__ import annotations

import csv
import html
import io
import json
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

from downloader_app.browser_session import BrowserSessionError, browser_session
from downloader_app.google_auth import GoogleAuthError, google_oauth


URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")
SHEET_ID_PATTERN = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
ACCOUNT_INDEX_PATTERN = re.compile(r"/spreadsheets/u/(\d+)/d/")
GVIZ_PREFIX = "google.visualization.Query.setResponse("
TIME_POINT_RAW = r"\d{1,3}(?:[:.]\d{1,2})?"
TIME_POINT_PATTERN = re.compile(rf"^{TIME_POINT_RAW}$")
TIME_TO_END_PATTERN = re.compile(
    rf"^\s*(?P<start>{TIME_POINT_RAW})\s*(?:-\s*|\s+)(?:đến\s*hết|den\s*het|hết|het)\s*$",
    re.IGNORECASE,
)
EMBEDDED_TIME_RANGE_PATTERN = re.compile(
    rf"(?<![\w:.])(?P<start>{TIME_POINT_RAW})\s*-\s*(?P<end>{TIME_POINT_RAW})(?![\w:.])"
)
EMBEDDED_TIME_TO_END_PATTERN = re.compile(
    rf"(?<![\w:.])(?P<start>{TIME_POINT_RAW})\s*(?:-\s*|\s+)(?P<end>đến\s*hết|den\s*het|hết|het)(?![\w:.])",
    re.IGNORECASE,
)
EXCLUDE_MARKER_PATTERN = re.compile(r"(?:bỏ\s*đoạn|bo\s*doan)", re.IGNORECASE)
INCLUDE_MARKER_PATTERN = re.compile(r"(?:lấy\s*từ|lay\s*tu|lấy|lay)", re.IGNORECASE)
TIME_RANGE_SPLIT_PATTERN = re.compile(r"[\n,;|]+")
HEADER_SCAN_LIMIT = 12
SEQUENCE_HEADERS = {
    "stt",
    "sothutu",
    "sothutu.",
    "thutu",
    "index",
    "sequence",
    "order",
    "no",
}
TIME_HEADERS = {
    "time",
    "thoiluong",
    "thoiluongvideo",
    "duration",
    "videoduration",
    "timerange",
    "cliptime",
    "trimtime",
}
URL_HEADERS = {
    "link",
    "linkvideo",
    "videolink",
    "url",
    "videourl",
    "source",
    "sourcelink",
}


@dataclass(frozen=True)
class SheetCell:
    value: str
    row_index: int
    column_index: int


@dataclass(frozen=True)
class ClipRange:
    label: str
    start_seconds: int
    end_seconds: int | None = None


@dataclass(frozen=True)
class _RawClipRange:
    start_seconds: int
    end_seconds: int | None = None


def _join_clip_range_labels(clip_ranges: Iterable["ClipRange"]) -> str | None:
    labels = [clip_range.label for clip_range in clip_ranges]
    if not labels:
        return None
    return "; ".join(labels)


@dataclass(frozen=True)
class SheetUrlEntry:
    url: str
    row_index: int
    column_index: int
    sequence_label: str
    clip_ranges: tuple[ClipRange, ...] = ()

    @property
    def clip_range_label(self) -> str | None:
        return _join_clip_range_labels(self.clip_ranges)

    @property
    def clip_start_seconds(self) -> int | None:
        if len(self.clip_ranges) != 1:
            return None
        return self.clip_ranges[0].start_seconds

    @property
    def clip_end_seconds(self) -> int | None:
        if len(self.clip_ranges) != 1:
            return None
        return self.clip_ranges[0].end_seconds


@dataclass(frozen=True)
class SheetScanResult:
    sheet_id: str
    gid: str | None
    sheet_title: str
    cells: list[SheetCell]
    entries: list[SheetUrlEntry]
    access_mode: str

    @property
    def urls(self) -> list[str]:
        return [entry.url for entry in self.entries]


class SheetParseError(ValueError):
    pass


@dataclass(frozen=True)
class HeaderLayout:
    header_row_index: int | None
    sequence_column: int | None
    time_columns: tuple[int, ...]


def extract_sheet_id(sheet_url: str) -> str:
    match = SHEET_ID_PATTERN.search(sheet_url)
    if not match:
        raise SheetParseError("Khong tim thay sheet id trong URL Google Sheets.")
    return match.group(1)


def extract_gid(sheet_url: str) -> str | None:
    parsed = urlparse(sheet_url)

    query = parse_qs(parsed.query)
    if "gid" in query and query["gid"]:
        return query["gid"][0]

    if parsed.fragment:
        fragment_query = parse_qs(parsed.fragment.replace("#", ""))
        if "gid" in fragment_query and fragment_query["gid"]:
            return fragment_query["gid"][0]

        gid_match = re.search(r"gid=(\d+)", parsed.fragment)
        if gid_match:
            return gid_match.group(1)

    return None


def extract_account_index(sheet_url: str) -> str | None:
    match = ACCOUNT_INDEX_PATTERN.search(sheet_url)
    if not match:
        return None
    return match.group(1)


def _fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0 Safari/537.36"
            )
        },
    )
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def _build_gviz_url(sheet_id: str, gid: str | None) -> str:
    base = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
    params = {"tqx": "out:json"}
    if gid:
        params["gid"] = gid
    return f"{base}?{urlencode(params)}"


def _build_csv_url(sheet_id: str, gid: str | None) -> str:
    base = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export"
    params = {"format": "csv"}
    if gid:
        params["gid"] = gid
    return f"{base}?{urlencode(params)}"


def _build_account_gviz_url(sheet_id: str, gid: str | None, account_index: str | None) -> str:
    if account_index is None:
        return _build_gviz_url(sheet_id, gid)
    base = f"https://docs.google.com/spreadsheets/u/{account_index}/d/{sheet_id}/gviz/tq"
    params = {"tqx": "out:json"}
    if gid:
        params["gid"] = gid
    return f"{base}?{urlencode(params)}"


def _build_account_csv_url(sheet_id: str, gid: str | None, account_index: str | None) -> str:
    if account_index is None:
        return _build_csv_url(sheet_id, gid)
    base = f"https://docs.google.com/spreadsheets/u/{account_index}/d/{sheet_id}/export"
    params = {"format": "csv"}
    if gid:
        params["gid"] = gid
    return f"{base}?{urlencode(params)}"


def _parse_gviz_payload(payload: str) -> list[SheetCell]:
    if not payload.startswith(GVIZ_PREFIX):
        raise SheetParseError("Khong doc duoc du lieu gviz tu Google Sheets.")

    raw_json = payload[len(GVIZ_PREFIX) :].strip()
    if raw_json.endswith(");"):
        raw_json = raw_json[:-2]
    parsed = json.loads(raw_json)
    table = parsed.get("table", {})
    rows = table.get("rows", [])
    cells: list[SheetCell] = []

    for row_index, row in enumerate(rows):
        columns = row.get("c", [])
        for column_index, column in enumerate(columns):
            if not column:
                continue
            value = column.get("f")
            if value is None:
                raw_value = column.get("v")
                value = "" if raw_value is None else str(raw_value)
            cells.append(
                SheetCell(
                    value=str(value),
                    row_index=row_index,
                    column_index=column_index,
                )
            )

    return cells


def _parse_csv_payload(payload: str) -> list[SheetCell]:
    reader = csv.reader(io.StringIO(payload))
    cells: list[SheetCell] = []

    for row_index, row in enumerate(reader):
        for column_index, value in enumerate(row):
            if not value:
                continue
            cells.append(
                SheetCell(
                    value=value,
                    row_index=row_index,
                    column_index=column_index,
                )
            )

    return cells


def _parse_values_payload(payload: dict) -> list[SheetCell]:
    values = payload.get("values", [])
    cells: list[SheetCell] = []

    for row_index, row in enumerate(values):
        for column_index, value in enumerate(row):
            if not value:
                continue
            cells.append(
                SheetCell(
                    value=str(value),
                    row_index=row_index,
                    column_index=column_index,
                )
            )

    return cells


def _extract_sheet_title_from_html(payload: str) -> str | None:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", payload, re.IGNORECASE | re.DOTALL)
    if not title_match:
        return None

    title = re.sub(r"\s+", " ", title_match.group(1)).strip()
    if not title:
        return None

    for suffix in (
        " - Google Sheets",
        " – Google Sheets",
        " - Google Trang tính",
        " – Google Trang tính",
    ):
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
            break

    return title or None


def _clean_html_text(value: str) -> str | None:
    stripped = re.sub(r"<[^>]+>", " ", value)
    stripped = html.unescape(stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    if not stripped:
        return None
    return stripped


def _decode_embedded_text(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return html.unescape(value)


def _extract_sheet_tab_title_from_html(payload: str, gid: str | None) -> str | None:
    normalized_gid = str(gid).strip() if gid is not None else None

    if normalized_gid:
        object_patterns = [
            re.compile(
                rf'"sheetId"\s*:\s*"?{re.escape(normalized_gid)}"?[\s\S]{{0,10000}}?"title"\s*:\s*"([^"]+)"',
                re.IGNORECASE,
            ),
            re.compile(
                rf'"title"\s*:\s*"([^"]+)"[\s\S]{{0,10000}}?"sheetId"\s*:\s*"?{re.escape(normalized_gid)}"?',
                re.IGNORECASE,
            ),
            re.compile(
                rf'\bsheetId\s*:\s*"?{re.escape(normalized_gid)}"?[\s\S]{{0,10000}}?\btitle\s*:\s*"([^"]+)"',
                re.IGNORECASE,
            ),
            re.compile(
                rf'\btitle\s*:\s*"([^"]+)"[\s\S]{{0,10000}}?\bsheetId\s*:\s*"?{re.escape(normalized_gid)}"?',
                re.IGNORECASE,
            ),
        ]
        for pattern in object_patterns:
            match = pattern.search(payload)
            if match:
                title = _clean_html_text(_decode_embedded_text(match.group(1)))
                if title:
                    return title

        link_patterns = [
            re.compile(
                rf'<a[^>]+href="[^"]*gid={re.escape(normalized_gid)}[^"]*"[^>]*>(.*?)</a>',
                re.IGNORECASE | re.DOTALL,
            ),
            re.compile(
                rf'<[^>]+data-sheet-id="{re.escape(normalized_gid)}"[^>]*>(.*?)</[^>]+>',
                re.IGNORECASE | re.DOTALL,
            ),
            re.compile(
                rf'<[^>]+data-sheet-id="{re.escape(normalized_gid)}"[^>]+aria-label="([^"]+)"[^>]*>',
                re.IGNORECASE | re.DOTALL,
            ),
            re.compile(
                rf'<[^>]+data-sheet-id="{re.escape(normalized_gid)}"[^>]+title="([^"]+)"[^>]*>',
                re.IGNORECASE | re.DOTALL,
            ),
        ]
        for pattern in link_patterns:
            match = pattern.search(payload)
            if match:
                title = _clean_html_text(match.group(1))
                if title:
                    return title

        # Fallback: locate gid first, then try to infer nearby tab-title keys.
        nearby_patterns = (
            rf'(?:"sheetId"|"gid"|"id")\s*:\s*"?{re.escape(normalized_gid)}"?[\s\S]{{0,6000}}?(?:"title"|"name"|"sheetName"|"tabName"|"caption")\s*:\s*"((?:\\.|[^"\\])+)"',
            rf'(?:"title"|"name"|"sheetName"|"tabName"|"caption")\s*:\s*"((?:\\.|[^"\\])+)"[\s\S]{{0,6000}}?(?:"sheetId"|"gid"|"id")\s*:\s*"?{re.escape(normalized_gid)}"?',
        )
        gid_matches = list(re.finditer(re.escape(normalized_gid), payload))
        for gid_match in gid_matches:
            start = max(0, gid_match.start() - 20000)
            end = min(len(payload), gid_match.end() + 20000)
            window = payload[start:end]
            for pattern in nearby_patterns:
                match = re.search(pattern, window, re.IGNORECASE)
                if not match:
                    continue
                title = _clean_html_text(_decode_embedded_text(match.group(1)))
                if title and "google sheets" not in title.lower():
                    return title

    selected_patterns = [
        re.compile(r'<[^>]+aria-selected="true"[^>]*>(.*?)</[^>]+>', re.IGNORECASE | re.DOTALL),
        re.compile(r'<[^>]+data-active="true"[^>]*>(.*?)</[^>]+>', re.IGNORECASE | re.DOTALL),
    ]
    for pattern in selected_patterns:
        match = pattern.search(payload)
        if match:
            title = _clean_html_text(match.group(1))
            if title and "google sheets" not in title.lower():
                return title

    return None


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _format_seconds(total_seconds: int) -> str:
    minutes, seconds = divmod(max(0, total_seconds), 60)
    return f"{minutes:02d}:{seconds:02d}"


def _parse_clip_endpoint(value: str) -> tuple[int | None, int] | None:
    stripped = value.strip()
    if not TIME_POINT_PATTERN.match(stripped):
        return None

    if ":" in stripped or "." in stripped:
        minutes_text, seconds_text = re.split(r"[:.]", stripped, maxsplit=1)
        seconds = int(seconds_text)
        if seconds >= 60:
            return None
        return int(minutes_text), seconds

    seconds = int(stripped)
    if seconds >= 60:
        return None
    return None, seconds


def _parse_raw_clip_range(value: str) -> _RawClipRange | None:
    stripped = value.strip()
    to_end_match = TIME_TO_END_PATTERN.match(stripped)
    if to_end_match:
        start_endpoint = _parse_clip_endpoint(to_end_match.group("start"))
        if start_endpoint is None:
            return None

        start_minutes, start_seconds = start_endpoint
        if start_minutes is None:
            start_minutes = 0

        start_total = start_minutes * 60 + start_seconds
        return _RawClipRange(start_seconds=start_total, end_seconds=None)

    parts = re.split(r"\s*-\s*", stripped)
    if len(parts) != 2:
        return None

    start_endpoint = _parse_clip_endpoint(parts[0])
    end_endpoint = _parse_clip_endpoint(parts[1])
    if start_endpoint is None or end_endpoint is None:
        return None

    start_minutes, start_seconds = start_endpoint
    end_minutes, end_seconds = end_endpoint
    if start_minutes is None and end_minutes is None:
        return None

    if start_minutes is None:
        start_minutes = 0
    if end_minutes is None:
        end_minutes = start_minutes
    if start_minutes is None or end_minutes is None:
        return None

    start_total = start_minutes * 60 + start_seconds
    end_total = end_minutes * 60 + end_seconds
    if end_total <= start_total:
        return None

    return _RawClipRange(
        start_seconds=start_total,
        end_seconds=end_total,
    )


def _clip_range_from_raw(raw_range: _RawClipRange) -> ClipRange | None:
    if raw_range.end_seconds is not None and raw_range.end_seconds <= raw_range.start_seconds:
        return None

    padded_start = max(0, raw_range.start_seconds - 1)
    if raw_range.end_seconds is None:
        return ClipRange(
            label=f"{_format_seconds(padded_start)}-het",
            start_seconds=padded_start,
            end_seconds=None,
        )

    padded_end = raw_range.end_seconds + 1
    return ClipRange(
        label=f"{_format_seconds(padded_start)}-{_format_seconds(padded_end)}",
        start_seconds=padded_start,
        end_seconds=padded_end,
    )


def _last_clip_marker_mode(context: str) -> str | None:
    last_mode: str | None = None
    last_position = -1

    for match in INCLUDE_MARKER_PATTERN.finditer(context):
        if match.start() >= last_position:
            last_position = match.start()
            last_mode = "include"

    for match in EXCLUDE_MARKER_PATTERN.finditer(context):
        if match.start() >= last_position:
            last_position = match.start()
            last_mode = "exclude"

    return last_mode


def _subtract_raw_clip_range(include_range: _RawClipRange, exclude_range: _RawClipRange) -> list[_RawClipRange]:
    include_end = float("inf") if include_range.end_seconds is None else include_range.end_seconds
    exclude_end = float("inf") if exclude_range.end_seconds is None else exclude_range.end_seconds

    if exclude_end <= include_range.start_seconds or exclude_range.start_seconds >= include_end:
        return [include_range]

    results: list[_RawClipRange] = []
    if exclude_range.start_seconds > include_range.start_seconds:
        left = _RawClipRange(
            start_seconds=include_range.start_seconds,
            end_seconds=min(exclude_range.start_seconds, include_end) if include_range.end_seconds is not None else exclude_range.start_seconds,
        )
        if left.end_seconds is None or left.end_seconds > left.start_seconds:
            results.append(left)

    if exclude_end < include_end:
        right_end = include_range.end_seconds
        right = _RawClipRange(
            start_seconds=int(exclude_end),
            end_seconds=right_end,
        )
        if right.end_seconds is None or right.end_seconds > right.start_seconds:
            results.append(right)

    return results


def _parse_clip_ranges(value: str) -> list[ClipRange]:
    stripped = value.strip()
    if not stripped:
        return []

    single_range = _parse_raw_clip_range(stripped)
    if single_range:
        clip_range = _clip_range_from_raw(single_range)
        return [] if clip_range is None else [clip_range]

    candidates: list[tuple[int, int, str]] = []
    for pattern in (EMBEDDED_TIME_RANGE_PATTERN, EMBEDDED_TIME_TO_END_PATTERN):
        for match in pattern.finditer(stripped):
            candidates.append((match.start(), match.end(), match.group(0)))

    candidates.sort(key=lambda item: item[0])

    include_ranges: list[_RawClipRange] = []
    exclude_ranges: list[_RawClipRange] = []
    current_mode = "include"
    previous_end = 0

    for start, end, candidate in candidates:
        marker_mode = _last_clip_marker_mode(stripped[previous_end:start])
        if marker_mode is not None:
            current_mode = marker_mode

        raw_clip_range = _parse_raw_clip_range(candidate)
        if raw_clip_range is None:
            previous_end = end
            continue

        if current_mode == "exclude":
            exclude_ranges.append(raw_clip_range)
        else:
            include_ranges.append(raw_clip_range)
        previous_end = end

    if not include_ranges and exclude_ranges:
        include_ranges = [_RawClipRange(start_seconds=0, end_seconds=None)]

    resolved_ranges: list[_RawClipRange] = []
    for include_range in include_ranges:
        pending = [include_range]
        for exclude_range in exclude_ranges:
            next_pending: list[_RawClipRange] = []
            for segment in pending:
                next_pending.extend(_subtract_raw_clip_range(segment, exclude_range))
            pending = next_pending
            if not pending:
                break
        resolved_ranges.extend(pending)

    clip_ranges: list[ClipRange] = []
    seen: set[tuple[int, int | None]] = set()
    for raw_range in resolved_ranges:
        clip_range = _clip_range_from_raw(raw_range)
        if clip_range is None:
            continue
        key = (clip_range.start_seconds, clip_range.end_seconds)
        if key in seen:
            continue
        seen.add(key)
        clip_ranges.append(clip_range)

    return clip_ranges


def _group_cells_by_row(cells: Iterable[SheetCell]) -> dict[int, list[SheetCell]]:
    rows: dict[int, list[SheetCell]] = {}
    for cell in cells:
        rows.setdefault(cell.row_index, []).append(cell)

    for row_cells in rows.values():
        row_cells.sort(key=lambda cell: cell.column_index)
    return rows


def _first_column_value(row_cells: list[SheetCell]) -> str:
    for cell in row_cells:
        if cell.column_index == 0:
            return cell.value.strip()
    return ""


def _find_sequence_column(row_cells: list[SheetCell]) -> int | None:
    for cell in row_cells:
        normalized = _normalize_header(cell.value)
        if normalized in SEQUENCE_HEADERS:
            return cell.column_index
    return None


def _find_time_columns(row_cells: list[SheetCell]) -> tuple[int, ...]:
    columns: list[int] = []
    for cell in row_cells:
        normalized = _normalize_header(cell.value)
        if normalized in TIME_HEADERS:
            columns.append(cell.column_index)
    return tuple(columns)


def _row_header_score(row_cells: list[SheetCell]) -> int:
    matched_kinds: set[str] = set()
    for cell in row_cells:
        normalized = _normalize_header(cell.value)
        if normalized in SEQUENCE_HEADERS:
            matched_kinds.add("sequence")
        elif normalized in TIME_HEADERS:
            matched_kinds.add("time")
        elif normalized in URL_HEADERS:
            matched_kinds.add("url")

    score = len(matched_kinds)
    if "url" in matched_kinds:
        score += 1
    return score


def _detect_header_layout(rows: dict[int, list[SheetCell]]) -> HeaderLayout:
    best_row_index: int | None = None
    best_score = 0

    for row_index in sorted(rows)[:HEADER_SCAN_LIMIT]:
        row_cells = rows[row_index]
        score = _row_header_score(row_cells)
        if score > best_score:
            best_row_index = row_index
            best_score = score

    if best_row_index is None or best_score == 0:
        return HeaderLayout(header_row_index=None, sequence_column=None, time_columns=())

    header_cells = rows[best_row_index]
    return HeaderLayout(
        header_row_index=best_row_index,
        sequence_column=_find_sequence_column(header_cells),
        time_columns=_find_time_columns(header_cells),
    )


def _candidate_sequence_label(
    row_cells: list[SheetCell],
    sequence_column: int | None,
    url_column: int,
) -> str | None:
    if sequence_column is not None:
        for cell in row_cells:
            if cell.column_index == sequence_column and cell.value.strip():
                return cell.value.strip()

    for cell in row_cells:
        if cell.column_index >= url_column:
            break
        value = cell.value.strip()
        if not value:
            continue
        if _parse_clip_ranges(value):
            continue
        if URL_PATTERN.search(value):
            continue
        return value

    return None


def _candidate_clip_values(
    row_cells: list[SheetCell],
    time_columns: tuple[int, ...],
    url_column: int,
) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()

    def push(raw_value: str) -> None:
        value = raw_value.strip()
        if not value or value in seen:
            return
        seen.add(value)
        values.append(value)

    for cell in row_cells:
        if cell.column_index in time_columns:
            push(cell.value)

    push(_first_column_value(row_cells))

    for cell in row_cells:
        if cell.column_index == url_column:
            continue
        if URL_PATTERN.search(cell.value):
            continue
        push(cell.value)

    return values


def _extract_clip_ranges(
    row_cells: list[SheetCell],
    time_columns: tuple[int, ...],
    url_column: int,
) -> list[ClipRange]:
    clip_ranges: list[ClipRange] = []
    seen: set[tuple[int, int | None]] = set()

    for value in _candidate_clip_values(row_cells, time_columns, url_column):
        for clip_range in _parse_clip_ranges(value):
            key = (clip_range.start_seconds, clip_range.end_seconds)
            if key in seen:
                continue
            seen.add(key)
            clip_ranges.append(clip_range)
    return clip_ranges


def _extract_entries_from_cells(cells: Iterable[SheetCell]) -> list[SheetUrlEntry]:
    ordered_cells = sorted(cells, key=lambda cell: (cell.row_index, cell.column_index))
    rows = _group_cells_by_row(ordered_cells)
    header_layout = _detect_header_layout(rows)

    entries: list[SheetUrlEntry] = []
    seen_urls_by_row: dict[int, set[str]] = {}
    used_labels: dict[str, int] = {}
    fallback_index = 1

    for cell in ordered_cells:
        matches = URL_PATTERN.findall(cell.value)
        if not matches:
            continue

        row_cells = rows.get(cell.row_index, [])
        clip_ranges = _extract_clip_ranges(
            row_cells,
            header_layout.time_columns,
            cell.column_index,
        )

        for match in matches:
            cleaned = match.rstrip(".,);]")
            row_seen_urls = seen_urls_by_row.setdefault(cell.row_index, set())
            if cleaned in row_seen_urls:
                continue

            row_seen_urls.add(cleaned)
            raw_label = _candidate_sequence_label(
                row_cells,
                header_layout.sequence_column,
                cell.column_index,
            )
            base_label = raw_label or str(fallback_index)
            fallback_index += 1
            count = used_labels.get(base_label, 0) + 1
            used_labels[base_label] = count
            final_label = base_label if count == 1 else f"{base_label}-{count}"

            entries.append(
                SheetUrlEntry(
                    url=cleaned,
                    row_index=cell.row_index,
                    column_index=cell.column_index,
                    sequence_label=final_label,
                    clip_ranges=tuple(clip_ranges),
                )
            )

    return entries


def _scan_private_sheet(sheet_id: str, gid: str | None) -> SheetScanResult:
    metadata = google_oauth.authorized_json(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
        "?fields=properties(title),sheets(properties(sheetId,title))"
    )

    sheets = metadata.get("sheets", [])
    if not sheets:
        raise SheetParseError("Google Sheets API khong tra ve tab nao trong file nay.")

    selected_title: str | None = None
    selected_gid = gid

    if gid:
        for sheet in sheets:
            properties = sheet.get("properties", {})
            if str(properties.get("sheetId")) == gid:
                selected_title = properties.get("title")
                break
        if selected_title is None:
            raise SheetParseError(f"Khong tim thay tab co gid={gid} trong Google Sheet.")
    else:
        properties = sheets[0].get("properties", {})
        selected_title = properties.get("title")
        selected_gid = str(properties.get("sheetId"))

    if not selected_title:
        raise SheetParseError("Khong xac dinh duoc ten tab Google Sheets can doc.")

    escaped_title = selected_title.replace("'", "''")
    requested_range = quote(f"'{escaped_title}'", safe="")
    values = google_oauth.authorized_json(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{requested_range}"
    )

    cells = _parse_values_payload(values)
    entries = _extract_entries_from_cells(cells)

    return SheetScanResult(
        sheet_id=sheet_id,
        gid=selected_gid,
        sheet_title=selected_title,
        cells=cells,
        entries=entries,
        access_mode="private_google_oauth",
    )


def _scan_public_sheet(sheet_id: str, gid: str | None) -> SheetScanResult:
    gviz_url = _build_gviz_url(sheet_id, gid)
    csv_url = _build_csv_url(sheet_id, gid)

    cells: list[SheetCell]

    try:
        payload = _fetch_text(gviz_url)
        cells = _parse_gviz_payload(payload)
    except Exception:
        try:
            payload = _fetch_text(csv_url)
            cells = _parse_csv_payload(payload)
        except Exception as exc:  # pragma: no cover - network/runtime edge
            raise SheetParseError(
                "Khong the doc sheet. Neu sheet private, hay dang nhap Google. "
                "Neu sheet public, hay dam bao link co quyen xem bang link hoac da duoc publish."
            ) from exc

    entries = _extract_entries_from_cells(cells)
    sheet_title = ""
    try:
        landing_page = _fetch_text(
            f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
            + (f"?gid={gid}" if gid else "")
        )
        tab_title = _extract_sheet_tab_title_from_html(landing_page, gid)
        doc_title = _extract_sheet_title_from_html(landing_page)
        sheet_title = tab_title or doc_title or ""
    except Exception:
        sheet_title = ""

    return SheetScanResult(
        sheet_id=sheet_id,
        gid=gid,
        sheet_title=sheet_title or "sheet",
        cells=cells,
        entries=entries,
        access_mode="public_link",
    )


def _candidate_account_indices(sheet_url: str) -> list[str | None]:
    preferred = extract_account_index(sheet_url)
    candidates: list[str | None] = []

    if preferred is not None:
        candidates.append(preferred)

    candidates.append(None)

    for index in range(2):
        value = str(index)
        if value == preferred:
            continue
        candidates.append(value)

    return candidates


def _scan_browser_session_sheet(sheet_id: str, gid: str | None, sheet_url: str) -> SheetScanResult:
    try:
        landing_page = browser_session.fetch_text(sheet_url)
    except BrowserSessionError as exc:
        raise SheetParseError(str(exc)) from exc
    tab_title = _extract_sheet_tab_title_from_html(landing_page, gid)
    doc_title = _extract_sheet_title_from_html(landing_page)
    sheet_title = tab_title or doc_title or "sheet"

    last_error: Exception | None = None

    for account_index in _candidate_account_indices(sheet_url):
        gviz_url = _build_account_gviz_url(sheet_id, gid, account_index)
        csv_url = _build_account_csv_url(sheet_id, gid, account_index)

        try:
            payload = browser_session.fetch_text(gviz_url)
            cells = _parse_gviz_payload(payload)
        except Exception as gviz_exc:
            try:
                payload = browser_session.fetch_text(csv_url)
                cells = _parse_csv_payload(payload)
            except Exception as csv_exc:
                last_error = csv_exc
                continue
            else:
                entries = _extract_entries_from_cells(cells)
                return SheetScanResult(
                    sheet_id=sheet_id,
                    gid=gid,
                    sheet_title=sheet_title,
                    cells=cells,
                    entries=entries,
                    access_mode="browser_session",
                )
        else:
            entries = _extract_entries_from_cells(cells)
            return SheetScanResult(
                sheet_id=sheet_id,
                gid=gid,
                sheet_title=sheet_title,
                cells=cells,
                entries=entries,
                access_mode="browser_session",
            )

    raise SheetParseError(
        "Khong the doc sheet bang browser session. App da thu nhieu Google account slot "
        "(/u/0, /u/1, ...). Hay mo chinh sheet nay trong browser bang tai khoan co quyen xem, "
        "sau do bam Refresh Session va thu lai. "
        f"Chi tiet cuoi cung: {last_error}"
    ) from last_error


def scan_sheet(sheet_url: str) -> SheetScanResult:
    sheet_id = extract_sheet_id(sheet_url)
    gid = extract_gid(sheet_url)

    if google_oauth.is_authenticated():
        try:
            return _scan_private_sheet(sheet_id, gid)
        except GoogleAuthError as exc:
            oauth_error = SheetParseError(str(exc))
        else:
            oauth_error = None
    else:
        oauth_error = None

    if browser_session.has_session():
        try:
            return _scan_browser_session_sheet(sheet_id, gid, sheet_url)
        except SheetParseError as exc:
            browser_error = exc
        except BrowserSessionError as exc:
            browser_error = SheetParseError(str(exc))
    else:
        browser_error = None

    try:
        return _scan_public_sheet(sheet_id, gid)
    except SheetParseError as public_error:
        if browser_error is not None:
            raise browser_error from public_error
        if oauth_error is not None:
            raise oauth_error from public_error
        raise
