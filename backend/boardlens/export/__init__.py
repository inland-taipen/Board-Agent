from pathlib import Path

from . import docx_export, pdf_export
from .layout import CLASSIFICATION_LABELS, BriefingDocument, build


def render_docx(doc: BriefingDocument, destination: Path) -> Path:
    return docx_export.render(doc, destination)


def render_pdf(doc: BriefingDocument, destination: Path) -> Path:
    return pdf_export.render(doc, destination)


__all__ = [
    "CLASSIFICATION_LABELS",
    "BriefingDocument",
    "build",
    "render_docx",
    "render_pdf",
]
