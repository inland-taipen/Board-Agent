"""Common types for document ingestion.

Every parser reduces a source file to an ordered list of `Segment`s. A segment
is the smallest unit that still carries a *citable location* - a PDF page, a
DOCX page-equivalent block, a PPTX slide, or an XLSX sheet region. Citation
grounding in the briefing resolves back to these locators, so parsers must
never emit a segment whose `locator` they cannot justify.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class DocKind(StrEnum):
    """Board-pack document taxonomy (BRD Phase 1: source document taxonomy)."""

    PRIOR_MINUTES = "prior_minutes"
    BOARD_DECK = "board_deck"
    FINANCIAL_PACK = "financial_pack"
    RISK_REPORT = "risk_report"
    INTERNAL_AUDIT = "internal_audit"
    BUSINESS_UPDATE = "business_update"
    OTHER = "other"


class Confidentiality(StrEnum):
    """Classification carried end-to-end and stamped on every export."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    STRICTLY_CONFIDENTIAL = "strictly_confidential"


@dataclass(slots=True)
class Segment:
    """A parsed, citable region of a source document."""

    page: int  # 1-indexed page / slide / sheet ordinal
    text: str
    locator: str  # human-readable, e.g. "p. 14", "Slide 7", "Sheet 'P&L' rows 1-40"
    heading: str | None = None
    kind: str = "body"  # body | table | notes | title
    meta: dict = field(default_factory=dict)


# PDF extraction emits U+00A0 constantly; collapsing it is the point.
_WS = re.compile(r"[ \t ]+")  # noqa: RUF001
_BLANK = re.compile(r"\n{3,}")


def normalise(text: str) -> str:
    """Collapse parser whitespace artefacts without destroying line structure.

    Line structure matters: minutes and risk registers are frequently laid out
    as one item per line, and flattening them merges unrelated action items.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANK.sub("\n\n", text).strip()


class UnsupportedFormat(ValueError):
    """Raised when an uploaded file is not one of PDF / DOCX / PPTX / XLSX."""
