"""PDF rendering via ReportLab.

ReportLab rather than an HTML-to-PDF engine: it is pure Python, so a client
hosting BoardLens inside their own VPC does not need a headless browser or
system font packages in the image.

The PDF is the circulation copy - fixed pagination, classification stamped on
every page, and a page-number footer directors can refer to in the meeting.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .layout import BriefingDocument, build

_ACCENT = colors.HexColor("#0B3D5C")
_INK = colors.HexColor("#1A1A1A")
_MUTED = colors.HexColor("#5A5A5A")
_ALERT = colors.HexColor("#8B1A1A")
_RULE = colors.HexColor("#C9D6DE")

_MARGIN = 18 * mm


def render(doc: BriefingDocument, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()

    template = BaseDocTemplate(
        str(destination),
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN + 6 * mm,
        bottomMargin=_MARGIN + 4 * mm,
        title=f"Board Briefing - {doc.company} - {doc.meeting_label}",
        author="BoardLens AI",
        subject=doc.classification_banner,
    )
    frame = Frame(
        template.leftMargin,
        template.bottomMargin,
        template.width,
        template.height,
        id="body",
    )
    template.addPageTemplates(
        [PageTemplate(id="main", frames=[frame], onPage=_chrome(doc))]
    )

    story = []
    for block in build(doc):
        story.extend(_render_block(block, styles, template.width))

    template.build(story)
    return destination


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    common = {"fontName": "Helvetica", "textColor": _INK, "leading": 13.5}

    return {
        "title": ParagraphStyle(
            "bl_title", parent=base, fontName="Helvetica-Bold", fontSize=24,
            leading=28, textColor=_ACCENT, spaceBefore=30, spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "bl_subtitle", parent=base, fontName="Helvetica", fontSize=13,
            leading=16, textColor=_MUTED, spaceAfter=18,
        ),
        "h1": ParagraphStyle(
            "bl_h1", parent=base, fontName="Helvetica-Bold", fontSize=14,
            leading=17, textColor=_ACCENT, spaceBefore=16, spaceAfter=2,
            borderWidth=0, borderPadding=0,
        ),
        "h2": ParagraphStyle(
            "bl_h2", parent=base, fontName="Helvetica-Bold", fontSize=11,
            leading=14, textColor=_INK, spaceBefore=11, spaceAfter=3,
        ),
        "para": ParagraphStyle(
            "bl_para", parent=base, fontSize=9.5, alignment=TA_JUSTIFY,
            spaceAfter=5, **common,
        ),
        "kv": ParagraphStyle(
            "bl_kv", parent=base, fontSize=9.5, alignment=TA_JUSTIFY,
            spaceAfter=3, **common,
        ),
        "note": ParagraphStyle(
            "bl_note", parent=base, fontName="Helvetica-Oblique", fontSize=8.5,
            leading=11, textColor=_MUTED, alignment=TA_CENTER, spaceAfter=8,
        ),
        "cite": ParagraphStyle(
            "bl_cite", parent=base, fontName="Helvetica-Oblique", fontSize=8,
            leading=10, textColor=_MUTED, leftIndent=8, spaceAfter=9,
        ),
        "cite_missing": ParagraphStyle(
            "bl_cite_missing", parent=base, fontName="Helvetica-Oblique", fontSize=8,
            leading=10, textColor=_ALERT, leftIndent=8, spaceAfter=9,
        ),
        "bullet": ParagraphStyle(
            "bl_bullet", parent=base, fontSize=9, leading=12.5, leftIndent=12,
            bulletIndent=3, spaceAfter=3, textColor=_INK, fontName="Helvetica",
        ),
        "cell": ParagraphStyle(
            "bl_cell", parent=base, fontName="Helvetica", fontSize=7.5,
            leading=9.5, textColor=_INK,
        ),
        "cell_head": ParagraphStyle(
            "bl_cell_head", parent=base, fontName="Helvetica-Bold", fontSize=8,
            leading=10, textColor=colors.white,
        ),
    }


def _render_block(block, styles: dict, width: float) -> list:
    kind = block.kind

    if kind == "pagebreak":
        return [PageBreak()]

    if kind == "title":
        return [Paragraph(_esc(block.text), styles["title"])]

    if kind == "subtitle":
        return [Paragraph(_esc(block.text), styles["subtitle"])]

    if kind == "h1":
        rule = Table([[""]], colWidths=[width], rowHeights=[1.2])
        rule.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _RULE)]))
        return [Paragraph(_esc(block.text), styles["h1"]), rule, Spacer(1, 6)]

    if kind == "h2":
        return [Paragraph(_esc(block.text), styles["h2"])]

    if kind == "para":
        return [Paragraph(_esc(block.text), styles["para"])]

    if kind == "kv":
        text = (
            f'<font color="#0B3D5C"><b>{_esc(block.label)}:</b></font> '
            f"{_esc(block.text or 'not stated')}"
        )
        return [Paragraph(text, styles["kv"])]

    if kind == "note":
        return [Paragraph(_esc(block.text), styles["note"])]

    if kind == "bullets":
        return [
            Paragraph(_esc(item), styles["bullet"], bulletText="•")
            for item in (block.items or [])
        ]

    if kind == "cite":
        items = block.items or []
        if items:
            return [
                Paragraph("Source: " + _esc("; ".join(items)), styles["cite"])
            ]
        return [Paragraph("Source: no source cited", styles["cite_missing"])]

    if kind == "table":
        return _render_table(block, styles, width)

    return []


def _render_table(block, styles: dict, width: float) -> list:
    rows = block.items or []
    if not rows:
        return []

    n_cols = len(rows[0])
    # The last column of every annexure table holds the long free text, so it
    # gets the remaining width rather than an equal share.
    if n_cols == 4:
        weights = [0.08, 0.24, 0.20, 0.48]
    elif n_cols == 6:
        weights = [0.40, 0.14, 0.13, 0.13, 0.14, 0.06]
    else:
        weights = [1 / n_cols] * n_cols
    col_widths = [width * w for w in weights]

    data = [[Paragraph(_esc(str(c)), styles["cell_head"]) for c in rows[0]]]
    data += [[Paragraph(_esc(str(c)), styles["cell"]) for c in row] for row in rows[1:]]

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.4, _RULE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7F9")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return [table, Spacer(1, 10)]


def _chrome(doc: BriefingDocument):
    """Classification banner and footer, drawn on every page."""

    def draw(canvas, template):
        canvas.saveState()
        width, height = A4

        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(_ALERT)
        canvas.drawCentredString(width / 2, height - 12 * mm, doc.classification_banner)

        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(_MUTED)
        canvas.drawString(_MARGIN, 11 * mm, f"{doc.company}  |  {doc.meeting_label}")
        canvas.drawRightString(width - _MARGIN, 11 * mm, f"Page {canvas.getPageNumber()}")

        canvas.setStrokeColor(_RULE)
        canvas.setLineWidth(0.4)
        canvas.line(_MARGIN, 14 * mm, width - _MARGIN, 14 * mm)
        canvas.restoreState()

    return draw


def _esc(text: str) -> str:
    """Escape for ReportLab's mini-HTML parser.

    Board text routinely contains '&' (entity names) and angle brackets in
    tables; unescaped they abort the whole render.
    """
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("“", "&#8220;")
        .replace("”", "&#8221;")
    )
