"""Citation verification.

The BRD requires an auditable link from every briefing statement back to a
source document and page. That is only real if something checks it, so this
module resolves every cited chunk ID against the pack index and reports what
did not resolve.

Two failure modes are separated because they mean different things to a
reviewer:

* `invalid` - the model cited an ID that is not in the pack. The statement has
  no traceable source and must be treated as unverified.
* `uncited` - the model made a statement and cited nothing. For most fields
  that is a defect; for an action correctly marked `unclear` (the current pack
  is silent on it) an empty evidence list is the honest answer, so that case is
  excluded rather than counted against the briefing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..rag.index import PackIndex
from .schema import BoardBriefing

# Excerpt length shown in the review UI beside each citation.
_EXCERPT_CHARS = 320

# (attribute on BoardBriefing, human label, field used as the item's title)
_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("critical_risks", "Critical risk", "title"),
    ("unresolved_actions", "Unresolved action", "action"),
    ("performance_changes", "Performance change", "metric"),
    ("management_questions", "Question for management", "question"),
    ("decisions_required", "Decision required", "decision"),
)


@dataclass
class CitationIssue:
    section: str
    item_index: int
    item_label: str
    kind: str  # "invalid" | "uncited"
    detail: str


@dataclass
class VerificationReport:
    total_items: int = 0
    grounded_items: int = 0
    total_citations: int = 0
    resolved_citations: int = 0
    issues: list[CitationIssue] = field(default_factory=list)
    citation_map: dict[str, dict] = field(default_factory=dict)

    @property
    def grounding_rate(self) -> float:
        return (self.grounded_items / self.total_items) if self.total_items else 0.0

    @property
    def citation_validity(self) -> float:
        return (
            (self.resolved_citations / self.total_citations) if self.total_citations else 1.0
        )

    @property
    def passed(self) -> bool:
        """A briefing passes when every citation resolves and every item is grounded.

        Deliberately strict. A briefing that fails still reaches the reviewer -
        it is flagged, not withheld - because a company secretary is better
        placed to judge a partial gap than the pipeline is.
        """
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_items": self.total_items,
            "grounded_items": self.grounded_items,
            "total_citations": self.total_citations,
            "resolved_citations": self.resolved_citations,
            "grounding_rate": round(self.grounding_rate, 4),
            "citation_validity": round(self.citation_validity, 4),
            "passed": self.passed,
            "issues": [
                {
                    "section": i.section,
                    "item_index": i.item_index,
                    "item_label": i.item_label,
                    "kind": i.kind,
                    "detail": i.detail,
                }
                for i in self.issues
            ],
            "citation_map": self.citation_map,
        }


def verify(briefing: BoardBriefing, index: PackIndex) -> VerificationReport:
    report = VerificationReport()

    for attr, label, title_field in _SECTIONS:
        items = getattr(briefing, attr, []) or []
        for position, item in enumerate(items):
            report.total_items += 1
            item_label = str(getattr(item, title_field, ""))[:120]
            evidence = list(getattr(item, "evidence", []) or [])

            resolved: list[str] = []
            for chunk_id in evidence:
                report.total_citations += 1
                chunk = index.get(chunk_id.strip())
                if chunk is None:
                    report.issues.append(
                        CitationIssue(
                            section=label,
                            item_index=position,
                            item_label=item_label,
                            kind="invalid",
                            detail=(
                                f"Cited '{chunk_id}', which is not a chunk in this pack. "
                                "This statement has no traceable source."
                            ),
                        )
                    )
                    continue

                report.resolved_citations += 1
                resolved.append(chunk_id)
                if chunk_id not in report.citation_map:
                    report.citation_map[chunk_id] = {
                        "chunk_id": chunk.chunk_id,
                        "document_id": chunk.doc_id,
                        "document": chunk.doc_name,
                        "document_kind": chunk.doc_kind,
                        "page": chunk.page,
                        "locator": chunk.locator,
                        "citation": chunk.citation,
                        "excerpt": _excerpt(chunk.text),
                    }

            if resolved:
                report.grounded_items += 1
            elif not _absence_is_valid(attr, item):
                report.issues.append(
                    CitationIssue(
                        section=label,
                        item_index=position,
                        item_label=item_label,
                        kind="uncited",
                        detail="No source citation was supplied for this item.",
                    )
                )

    return report


def _absence_is_valid(attr: str, item: Any) -> bool:
    """An action marked `unclear` has nothing in the current pack to cite.

    That is the finding itself - the board directed something and the pack is
    silent - so demanding a citation would push the model to attach a
    loosely-related chunk just to satisfy the check.
    """
    return attr == "unresolved_actions" and getattr(item, "status", None) == "unclear"


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= _EXCERPT_CHARS:
        return flat
    return flat[:_EXCERPT_CHARS].rsplit(" ", 1)[0] + "..."


def resolve_citations(evidence: list[str], citation_map: dict[str, dict]) -> list[dict]:
    """Expand an item's evidence IDs into display-ready citation records."""
    out = []
    for chunk_id in evidence:
        record = citation_map.get(chunk_id.strip())
        if record:
            out.append(record)
    return out
