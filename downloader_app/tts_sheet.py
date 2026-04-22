from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from downloader_app.sheets import HEADER_SCAN_LIMIT, SheetCell, SheetParseError, _normalize_header, scan_sheet


TEXT_HEADERS = (
    "comment",
    "text",
    "script",
    "content",
    "caption",
    "message",
    "prompt",
    "line",
    "sentence",
)

ID_HEADERS = (
    "id",
    "stt",
    "sothutu",
    "sothutu.",
    "thutu",
    "index",
    "sequence",
    "order",
    "no",
)


@dataclass(frozen=True)
class SheetTextEntry:
    sequence_label: str
    row_index: int
    text: str


@dataclass(frozen=True)
class SheetTextScanResult:
    sheet_id: str
    gid: str | None
    sheet_title: str
    access_mode: str
    text_column: str
    available_columns: list[str]
    entries: list[SheetTextEntry]
    skipped_rows: int
    header_row_index: int | None


def _group_cells_by_row(cells: Iterable[SheetCell]) -> dict[int, list[SheetCell]]:
    rows: dict[int, list[SheetCell]] = {}
    for cell in cells:
        rows.setdefault(cell.row_index, []).append(cell)
    for row_cells in rows.values():
        row_cells.sort(key=lambda cell: cell.column_index)
    return rows


def _header_score(row_cells: list[SheetCell]) -> int:
    score = 0
    normalized_values = {_normalize_header(cell.value) for cell in row_cells if cell.value.strip()}
    if any(value in TEXT_HEADERS for value in normalized_values):
        score += 3
    if any(value in ID_HEADERS for value in normalized_values):
        score += 1
    return score


def _detect_header_row(rows: dict[int, list[SheetCell]]) -> int | None:
    best_row_index: int | None = None
    best_score = 0

    for row_index in sorted(rows)[:HEADER_SCAN_LIMIT]:
        score = _header_score(rows[row_index])
        if score > best_score:
            best_row_index = row_index
            best_score = score

    return best_row_index if best_score > 0 else None


def _header_columns(header_cells: list[SheetCell]) -> dict[int, str]:
    columns: dict[int, str] = {}
    for cell in header_cells:
        label = cell.value.strip()
        if label:
            columns[cell.column_index] = label
    return columns


def _find_column_index(
    columns: dict[int, str],
    preferred_column: str | None,
    aliases: tuple[str, ...],
) -> int | None:
    preferred = _normalize_header(preferred_column or "")
    normalized = {index: _normalize_header(label) for index, label in columns.items()}

    if preferred:
        for index, value in normalized.items():
            if value == preferred:
                return index

    for alias in aliases:
        for index, value in normalized.items():
            if value == alias:
                return index

    return None


def _infer_text_column(rows: dict[int, list[SheetCell]], header_row_index: int | None) -> int | None:
    counts: dict[int, int] = {}
    for row_index, row_cells in rows.items():
        if header_row_index is not None and row_index <= header_row_index:
            continue
        for cell in row_cells:
            if cell.value.strip():
                counts[cell.column_index] = counts.get(cell.column_index, 0) + 1

    if not counts:
        return None

    return max(counts.items(), key=lambda item: (item[1], -item[0]))[0]


def _make_fallback_columns(rows: dict[int, list[SheetCell]]) -> dict[int, str]:
    columns: dict[int, str] = {}
    for row_cells in rows.values():
        for cell in row_cells:
            columns.setdefault(cell.column_index, f"Column {cell.column_index + 1}")
    return columns


def _sequence_label_for_row(
    row_cells: list[SheetCell],
    row_number: int,
    sequence_column: int | None,
) -> str:
    if sequence_column is not None:
        for cell in row_cells:
            if cell.column_index == sequence_column and cell.value.strip():
                return cell.value.strip()
    return f"row_{row_number}"


def extract_text_entries(
    cells: Iterable[SheetCell],
    preferred_text_column: str | None = None,
) -> tuple[list[SheetTextEntry], list[str], str, int, int | None]:
    ordered_cells = sorted(cells, key=lambda cell: (cell.row_index, cell.column_index))
    rows = _group_cells_by_row(ordered_cells)
    header_row_index = _detect_header_row(rows)
    header_columns = (
        _header_columns(rows.get(header_row_index, []))
        if header_row_index is not None
        else _make_fallback_columns(rows)
    )

    text_column_index = _find_column_index(header_columns, preferred_text_column, TEXT_HEADERS)
    if text_column_index is None:
        text_column_index = _infer_text_column(rows, header_row_index)

    if text_column_index is None:
        raise SheetParseError("Khong xac dinh duoc cot text trong Google Sheet.")

    sequence_column = _find_column_index(header_columns, None, ID_HEADERS)

    entries: list[SheetTextEntry] = []
    skipped_rows = 0
    start_row = (header_row_index + 1) if header_row_index is not None else 0

    for row_index in sorted(rows):
        if row_index < start_row:
            continue
        row_cells = rows[row_index]
        text_value = next(
            (cell.value.strip() for cell in row_cells if cell.column_index == text_column_index and cell.value.strip()),
            "",
        )
        if not text_value:
            skipped_rows += 1
            continue

        entries.append(
            SheetTextEntry(
                sequence_label=_sequence_label_for_row(row_cells, row_index + 1, sequence_column),
                row_index=row_index,
                text=text_value,
            )
        )

    available_columns = [label for _, label in sorted(header_columns.items())]
    selected_text_column = header_columns.get(text_column_index, f"Column {text_column_index + 1}")
    return entries, available_columns, selected_text_column, skipped_rows, header_row_index


def scan_text_sheet(
    sheet_url: str,
    preferred_text_column: str | None = None,
) -> SheetTextScanResult:
    scan_result = scan_sheet(sheet_url)
    entries, available_columns, selected_text_column, skipped_rows, header_row_index = extract_text_entries(
        scan_result.cells,
        preferred_text_column=preferred_text_column,
    )
    return SheetTextScanResult(
        sheet_id=scan_result.sheet_id,
        gid=scan_result.gid,
        sheet_title=scan_result.sheet_title,
        access_mode=scan_result.access_mode,
        text_column=selected_text_column,
        available_columns=available_columns,
        entries=entries,
        skipped_rows=skipped_rows,
        header_row_index=header_row_index,
    )
