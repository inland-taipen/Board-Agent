"""Ingestion tests.

The assertions here are about *citability*: a parser that returns text but
attaches it to the wrong page produces a briefing whose audit trail is wrong,
which is worse than one that fails outright.
"""

from __future__ import annotations

from boardlens.ingest import DocKind, classify, parse_file
from boardlens.ingest.base import normalise


def test_pdf_pages_are_sequential_and_located(sample_pack):
    segments = parse_file(sample_pack / "Board Minutes - 118th Meeting.pdf")

    assert segments, "the minutes PDF produced no segments"
    assert [s.page for s in segments] == sorted(s.page for s in segments)
    assert all(s.locator == f"p. {s.page}" for s in segments if s.kind == "body")
    assert any("118TH MEETING" in s.text for s in segments)


def test_pptx_captures_slides_tables_and_speaker_notes(sample_pack):
    segments = parse_file(sample_pack / "Board Deck - 119th Meeting.pptx")

    slides = {s.page for s in segments}
    assert len(slides) >= 8

    # Speaker notes hold the caveats the slide body omits, so they must survive.
    notes = [s for s in segments if s.kind == "notes"]
    assert notes, "speaker notes were not extracted"
    assert any("one-off provision" in s.text for s in notes)
    assert all(s.locator.endswith("(speaker notes)") for s in notes)


def test_xlsx_repeats_header_on_every_band(sample_pack):
    segments = parse_file(sample_pack / "Financial MIS - Q1 FY27.xlsx")

    sheets = {s.meta["sheet"] for s in segments}
    assert {"P&L", "Balance Sheet", "Covenants", "Segments"} <= sheets
    assert all("rows" in s.locator for s in segments)

    covenants = next(s for s in segments if s.meta["sheet"] == "Covenants")
    assert "1.28" in covenants.text
    assert "Debt service coverage ratio" in covenants.text


def test_docx_locators_reference_paragraph_ranges(sample_pack):
    segments = parse_file(sample_pack / "Risk Register and Internal Audit Report.docx")

    assert segments
    assert any("paras" in s.locator for s in segments)
    assert any("show-cause notice" in s.text for s in segments)
    # The document has an explicit page break, so page numbering must advance.
    assert max(s.page for s in segments) >= 2


def test_classification_prefers_minutes_over_audit():
    # "Minutes of the Audit Committee" is minutes, not an audit report - the
    # ordering of the classifier patterns is what guarantees this.
    assert classify("Minutes of the Audit Committee.pdf") == DocKind.PRIOR_MINUTES
    assert classify("Internal Audit Report Q1.pdf") == DocKind.INTERNAL_AUDIT
    assert classify("Risk Register FY27.docx") == DocKind.RISK_REPORT
    assert classify("Financial MIS Q1.xlsx") == DocKind.FINANCIAL_PACK


def test_classification_falls_back_to_extension():
    assert classify("untitled.pptx") == DocKind.BOARD_DECK
    assert classify("untitled.xlsx") == DocKind.FINANCIAL_PACK
    assert classify("untitled.pdf") == DocKind.OTHER


def test_normalise_preserves_line_structure():
    # Risk registers are one item per line; flattening merges unrelated items.
    text = "R-01  Customer   concentration\nR-02  Liquidity\n\n\n\nR-03  Cyber"
    assert normalise(text) == "R-01 Customer concentration\nR-02 Liquidity\n\nR-03 Cyber"
