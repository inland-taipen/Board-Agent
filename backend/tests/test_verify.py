"""Citation verification tests.

This is the check that makes the BRD's audit requirement real, so the tests
are about what it must catch and what it must not flag.
"""

from __future__ import annotations

import copy

from fixtures import BRIEFING

from boardlens.brief.verify import verify
from boardlens.ingest import classify, parse_file
from boardlens.rag import PackIndex, chunk_segments


def _index(sample_pack) -> PackIndex:
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


def test_invalid_chunk_id_is_caught(sample_pack):
    report = verify(BRIEFING, _index(sample_pack))

    invalid = [i for i in report.issues if i.kind == "invalid"]
    assert len(invalid) == 1
    assert "c9999" in invalid[0].detail
    assert invalid[0].section == "Decision required"
    assert not report.passed


def test_unclear_actions_are_not_penalised_for_citing_nothing(sample_pack):
    report = verify(BRIEFING, _index(sample_pack))

    # Two actions are marked 'unclear' with empty evidence. The current pack is
    # silent on them - that silence is the finding, so it must not be an issue.
    uncited = [i for i in report.issues if i.kind == "uncited"]
    assert uncited == []


def test_a_normal_item_with_no_evidence_is_flagged(sample_pack):
    briefing = copy.deepcopy(BRIEFING)
    briefing.critical_risks[0].evidence = []

    report = verify(briefing, _index(sample_pack))
    uncited = [i for i in report.issues if i.kind == "uncited"]

    assert len(uncited) == 1
    assert uncited[0].section == "Critical risk"


def test_citation_map_resolves_to_document_and_page(sample_pack):
    report = verify(BRIEFING, _index(sample_pack))

    assert report.citation_map, "no citations resolved"
    for record in report.citation_map.values():
        assert record["document"]
        assert record["locator"]
        assert isinstance(record["page"], int)
        assert record["excerpt"]

    # The invalid ID must not appear in the map - nothing may look sourced
    # when it is not.
    assert "c9999" not in report.citation_map


def test_a_fully_grounded_briefing_passes(sample_pack):
    briefing = copy.deepcopy(BRIEFING)
    briefing.decisions_required[1].evidence = ["c0007"]

    report = verify(briefing, _index(sample_pack))

    assert report.passed
    assert report.citation_validity == 1.0
    # Two actions are correctly marked 'unclear' and cite nothing, so the
    # grounding rate is honestly below 1.0 even though the briefing passes.
    # `passed` is the pass signal; grounding_rate is a coverage statistic.
    assert report.grounded_items == 16
    assert report.total_items == 18


def test_report_serialises_for_storage(sample_pack):
    payload = verify(BRIEFING, _index(sample_pack)).to_dict()

    assert set(payload) >= {
        "total_items",
        "grounded_items",
        "total_citations",
        "resolved_citations",
        "grounding_rate",
        "citation_validity",
        "passed",
        "issues",
        "citation_map",
    }
    assert payload["total_items"] == 18  # 3 + 5 + 3 + 5 + 2
