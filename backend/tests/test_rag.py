"""Chunking, indexing and retrieval tests."""

from __future__ import annotations

from boardlens.ingest import classify, parse_file
from boardlens.ingest.base import Segment
from boardlens.rag import SECTION_PLANS, PackIndex, chunk_segments, gather, render_evidence


def _build(sample_pack) -> PackIndex:
    chunks, counter = [], 0
    for path in sorted(sample_pack.iterdir()):
        segments = parse_file(path)
        kind = classify(path.name, "\n".join(s.text for s in segments[:6]))
        produced = chunk_segments(
            segments,
            doc_id=path.stem,
            doc_name=path.name,
            doc_kind=str(kind),
            start_index=counter,
        )
        counter += len(produced)
        chunks.extend(produced)
    return PackIndex(chunks).build()


def test_chunk_ids_are_unique_and_never_span_pages(sample_pack):
    index = _build(sample_pack)
    ids = [c.chunk_id for c in index.chunks]

    assert len(ids) == len(set(ids)), "chunk IDs collided across documents"
    # A chunk carries exactly one page and one document, or a citation could
    # not resolve to a single source page.
    assert all(isinstance(c.page, int) and c.doc_id for c in index.chunks)


def test_chunker_splits_oversized_segments_with_overlap():
    text = "\n".join(f"Line {i}: the board directed management on item {i}." for i in range(200))
    chunks = chunk_segments(
        [Segment(page=3, text=text, locator="p. 3")],
        doc_id="d1",
        doc_name="minutes.pdf",
        doc_kind="prior_minutes",
        target_tokens=700,
        overlap_tokens=100,
    )

    assert len(chunks) > 1
    assert all(len(c.text) <= 700 * 4 + 200 for c in chunks)
    # Page and locator are inherited by every piece, so all remain citable.
    assert {c.page for c in chunks} == {3}
    assert {c.locator for c in chunks} == {"p. 3"}


def test_retrieval_finds_the_right_document_for_each_section(sample_pack):
    index = _build(sample_pack)

    covenant_hits = index.search("debt service coverage ratio covenant floor", top_k=3)
    assert any("MIS" in h.chunk.doc_name or "Deck" in h.chunk.doc_name for h in covenant_hits)

    audit_hits = index.search("segregation of duties procurement repeat observation", top_k=3)
    assert "Risk Register" in audit_hits[0].chunk.doc_name


def test_section_plans_bias_toward_the_right_document_kinds(sample_pack):
    index = _build(sample_pack)
    plans = {p.key: p for p in SECTION_PLANS}

    actions = gather(index, plans["unresolved_actions"])
    assert actions, "no evidence retrieved for unresolved actions"
    # The plan restricts to minutes and the deck; nothing else should appear.
    assert {c.doc_kind for c in actions} <= {"prior_minutes", "board_deck"}


def test_render_evidence_respects_its_character_budget(sample_pack):
    index = _build(sample_pack)
    rendered = render_evidence(index.chunks, max_chars=1500)

    assert len(rendered) <= 1500
    assert rendered.startswith("[c0000]")


def test_doc_kind_filter_falls_back_when_it_matches_nothing(sample_pack):
    index = _build(sample_pack)
    # No document in the pack has this kind; the search must still return
    # results rather than silently producing an empty evidence set.
    hits = index.search("receivables", top_k=3, doc_kinds=["nonexistent_kind"])
    assert hits
