"""XLSX ingestion via openpyxl.

Financial packs are the highest-stakes numbers in the briefing, so sheets are
emitted as row bands with the header row repeated on every band. Without the
repeated header, a retrieved band of figures loses its column meaning and the
model has to guess which column is "current quarter" - exactly the failure a
board briefing cannot afford.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import openpyxl

from .base import Segment

# Rows per band. Small enough to retrieve precisely, large enough to keep a
# quarter's line items together.
_BAND_ROWS = 40
_MAX_COLS = 40
_MAX_ROWS = 5000


def parse(path: Path) -> list[Segment]:
    workbook = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    segments: list[Segment] = []

    try:
        for sheet_index, sheet in enumerate(workbook.worksheets, start=1):
            rows = _read_rows(sheet)
            if not rows:
                continue

            header = rows[0]
            header_line = " | ".join(header)
            has_header = any(cell and not _looks_numeric(cell) for cell in header)

            for start in range(0, len(rows), _BAND_ROWS):
                band = rows[start : start + _BAND_ROWS]
                lines = [" | ".join(r) for r in band if any(r)]
                if not lines:
                    continue

                first_row = start + 1
                last_row = start + len(band)
                body = "\n".join(lines)
                if has_header and start > 0:
                    body = f"{header_line}\n{body}"

                segments.append(
                    Segment(
                        page=sheet_index,
                        text=f"Sheet: {sheet.title}\n{body}",
                        locator=f"Sheet '{sheet.title}', rows {first_row}-{last_row}",
                        heading=sheet.title,
                        kind="table",
                        meta={"sheet": sheet.title, "first_row": first_row, "last_row": last_row},
                    )
                )
    finally:
        workbook.close()

    return segments


def _read_rows(sheet) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in sheet.iter_rows(max_row=_MAX_ROWS, max_col=_MAX_COLS, values_only=True):
        cells = [_fmt(v) for v in row]
        while cells and cells[-1] == "":
            cells.pop()
        rows.append(cells)

    while rows and not any(rows[-1]):
        rows.pop()
    return rows


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        # Board figures are read, not recomputed - keep them legible.
        return f"{value:,.2f}".rstrip("0").rstrip(".") if value % 1 else f"{int(value):,}"
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()[:10]
    return str(value).strip()


def _looks_numeric(cell: str) -> bool:
    try:
        float(cell.replace(",", ""))
    except ValueError:
        return False
    return True
