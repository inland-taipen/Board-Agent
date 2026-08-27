"""Format dispatch and document-kind classification."""

from __future__ import annotations

import re
from pathlib import Path

from . import docx_parser, pdf_parser, pptx_parser, xlsx_parser
from .base import DocKind, Segment, UnsupportedFormat

_PARSERS = {
    ".pdf": pdf_parser.parse,
    ".docx": docx_parser.parse,
    ".pptx": pptx_parser.parse,
    ".xlsx": xlsx_parser.parse,
    ".xlsm": xlsx_parser.parse,
}

SUPPORTED_EXTENSIONS = tuple(sorted(_PARSERS))


def parse_file(path: Path) -> list[Segment]:
    suffix = path.suffix.lower()
    parser = _PARSERS.get(suffix)
    if parser is None:
        raise UnsupportedFormat(
            f"{path.name}: '{suffix}' is not supported. "
            f"Accepted formats: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    return parser(path)


# Ordered most-specific first: "minutes of the audit committee" is minutes,
# not an audit report, so PRIOR_MINUTES must win over INTERNAL_AUDIT.
_KIND_PATTERNS: list[tuple[DocKind, re.Pattern[str]]] = [
    (DocKind.PRIOR_MINUTES, re.compile(r"\b(minutes|mom|proceedings|resolutions?)\b", re.I)),
    (DocKind.INTERNAL_AUDIT, re.compile(r"\b(internal audit|ia report|audit (report|findings)|iar)\b", re.I)),
    (DocKind.RISK_REPORT, re.compile(r"\b(risk register|risk report|erm|risk management|rmc)\b", re.I)),
    (DocKind.FINANCIAL_PACK, re.compile(r"\b(mis|financial|finance|p&l|pnl|balance sheet|cash ?flow|results|quarterly numbers)\b", re.I)),
    (DocKind.BOARD_DECK, re.compile(r"\b(board (deck|pack|presentation)|agenda|bm[- ]?\d+|deck)\b", re.I)),
    (DocKind.BUSINESS_UPDATE, re.compile(r"\b(business update|ceo (update|report)|operations? review|md report)\b", re.I)),
]


def classify(filename: str, sample_text: str = "") -> DocKind:
    """Infer document kind from filename, falling back to leading content.

    The operator can always override this in the UI - classification steers
    which specialist prompt reads the document, so a wrong guess degrades the
    briefing rather than breaking it.
    """
    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    for kind, pattern in _KIND_PATTERNS:
        if pattern.search(stem):
            return kind

    head = sample_text[:4000]
    for kind, pattern in _KIND_PATTERNS:
        if pattern.search(head):
            return kind

    suffix = Path(filename).suffix.lower()
    if suffix == ".pptx":
        return DocKind.BOARD_DECK
    if suffix in (".xlsx", ".xlsm"):
        return DocKind.FINANCIAL_PACK
    return DocKind.OTHER
