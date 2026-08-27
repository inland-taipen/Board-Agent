"""PDF ingestion via PyMuPDF.

PDFs are the dominant board-pack format and the only one with a native page
concept, so their locators are exact. Pages that yield no extractable text are
reported as `needs_ocr` rather than silently dropped - a scanned annexure that
vanishes from the index would produce a briefing with an invisible blind spot.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from .base import Segment, normalise

# Below this, a page is almost certainly a scan or a full-bleed image.
_MIN_TEXT_CHARS = 20


def parse(path: Path) -> list[Segment]:
    segments: list[Segment] = []
    with pymupdf.open(path) as doc:
        for page_no, page in enumerate(doc, start=1):
            raw = page.get_text("text") or ""
            text = normalise(raw)
            locator = f"p. {page_no}"

            if len(text) < _MIN_TEXT_CHARS:
                has_images = bool(page.get_images(full=False))
                segments.append(
                    Segment(
                        page=page_no,
                        text=text or "[no extractable text on this page]",
                        locator=locator,
                        kind="body",
                        meta={"needs_ocr": has_images, "empty": True},
                    )
                )
                continue

            segments.append(
                Segment(
                    page=page_no,
                    text=text,
                    locator=locator,
                    heading=_leading_heading(text),
                    kind="body",
                )
            )

            for t_index, table in enumerate(_tables(page), start=1):
                if table:
                    segments.append(
                        Segment(
                            page=page_no,
                            text=table,
                            locator=f"{locator}, table {t_index}",
                            kind="table",
                        )
                    )
    return segments


def _tables(page) -> list[str]:
    """Extract tables as pipe-delimited text.

    Financial MIS lives in tables, and PyMuPDF's linear text extraction
    scrambles column relationships badly enough that figures get attached to
    the wrong line item. `find_tables` is best-effort and version-dependent,
    so failure here degrades to text-only rather than failing the upload.
    """
    try:
        finder = page.find_tables()
    except Exception:
        return []

    out: list[str] = []
    for table in getattr(finder, "tables", []):
        try:
            rows = table.extract()
        except Exception:
            continue
        lines = [
            " | ".join("" if cell is None else str(cell).strip() for cell in row)
            for row in rows
            if any(cell not in (None, "") for cell in row)
        ]
        if lines:
            out.append("\n".join(lines))
    return out


def _leading_heading(text: str) -> str | None:
    first = text.split("\n", 1)[0].strip()
    if 3 <= len(first) <= 120:
        return first
    return None
