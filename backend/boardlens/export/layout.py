"""Shared document layout for the DOCX and PDF exports.

Both renderers consume the same block stream, so the two formats cannot drift
apart. A director reading the PDF and a company secretary editing the DOCX must
be looking at the same briefing, in the same order, with the same citations.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any

CLASSIFICATION_LABELS = {
    "public": "PUBLIC",
    "internal": "INTERNAL",
    "confidential": "CONFIDENTIAL - FOR BOARD MEMBERS ONLY",
    "strictly_confidential": "STRICTLY CONFIDENTIAL - NOT FOR CIRCULATION",
}

SEVERITY_LABELS = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}

STATUS_LABELS = {
    "open": "Open",
    "in_progress": "In progress",
    "completed": "Completed",
    "superseded": "Superseded",
    "unclear": "Not addressed in this pack",
}

DIRECTION_LABELS = {
    "improvement": "Improvement",
    "deterioration": "Deterioration",
    "mixed": "Mixed",
    "neutral": "Neutral",
}


@dataclass
class Block:
    kind: str  # title | subtitle | h1 | h2 | h3 | para | kv | bullets | cite | note | table | pagebreak
    text: str = ""
    items: list[Any] | None = None
    label: str = ""


@dataclass
class BriefingDocument:
    company: str
    meeting_label: str
    meeting_date: str
    classification: str
    generated_at: str
    model: str
    briefing: dict
    citation_map: dict[str, dict]
    verification: dict
    action_register: list[dict]

    @property
    def classification_banner(self) -> str:
        return CLASSIFICATION_LABELS.get(self.classification, self.classification.upper())

    @property
    def title(self) -> str:
        return "Board Briefing"


def citations_for(evidence: list[str], citation_map: dict[str, dict]) -> list[str]:
    """Render an item's evidence as human-readable source references.

    An unresolved ID is shown as such rather than dropped. Silently hiding it
    would leave a statement looking sourced when it is not.
    """
    out: list[str] = []
    for chunk_id in evidence or []:
        record = citation_map.get(chunk_id.strip())
        if record:
            out.append(f"{record['document']}, {record['locator']}")
        else:
            out.append(f"[unverified reference {chunk_id}]")
    # Preserve order, drop duplicates - the same page often supports two facts.
    seen: set[str] = set()
    unique = []
    for item in out:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def build(doc: BriefingDocument) -> Iterator[Block]:
    b = doc.briefing
    cmap = doc.citation_map

    # --- Cover ---------------------------------------------------------------
    yield Block("note", doc.classification_banner)
    yield Block("title", doc.title)
    yield Block("subtitle", doc.company)
    yield Block("kv", label="Meeting", text=doc.meeting_label)
    yield Block("kv", label="Meeting date", text=_pretty_date(doc.meeting_date))
    yield Block("kv", label="Briefing prepared", text=_pretty_date(doc.generated_at))
    yield Block(
        "kv",
        label="Prepared by",
        text=f"BoardLens AI ({doc.model}) - reviewed by the company secretary before circulation",
    )

    verification = doc.verification or {}
    if verification:
        yield Block(
            "kv",
            label="Source verification",
            text=(
                f"{verification.get('resolved_citations', 0)} of "
                f"{verification.get('total_citations', 0)} citations resolved to source pages; "
                f"{verification.get('grounded_items', 0)} of {verification.get('total_items', 0)} "
                f"findings carry a source reference"
            ),
        )

    yield Block(
        "note",
        "Every statement in this briefing carries a reference to the source document and "
        "page it was drawn from. References appear in italics beneath each finding.",
    )
    yield Block("pagebreak")

    # --- Context -------------------------------------------------------------
    if b.get("meeting_context"):
        yield Block("h1", "Meeting context")
        yield Block("para", b["meeting_context"])

    # --- 1. Critical risks ---------------------------------------------------
    yield Block("h1", "1. Critical risks for board attention")
    risks = b.get("critical_risks") or []
    if not risks:
        yield Block("para", "No critical risks were identified in this pack.")
    for index, risk in enumerate(risks, start=1):
        yield Block(
            "h2",
            f"1.{index}  {risk.get('title', 'Untitled risk')}"
            f"  [{SEVERITY_LABELS.get(risk.get('severity', ''), risk.get('severity', ''))}]",
        )
        yield Block("kv", label="Why now", text=risk.get("why_now", ""))
        yield Block("kv", label="Exposure", text=risk.get("exposure", ""))
        yield Block("kv", label="Management position", text=risk.get("management_position", ""))
        yield Block("kv", label="What the pack does not say", text=risk.get("gap", ""))
        yield Block("cite", items=citations_for(risk.get("evidence", []), cmap))

    # --- 2. Unresolved actions -----------------------------------------------
    yield Block("h1", "2. Unresolved actions from previous meetings")
    actions = b.get("unresolved_actions") or []
    if not actions:
        yield Block("para", "No unresolved actions were carried into this meeting.")
    for index, action in enumerate(actions, start=1):
        status = STATUS_LABELS.get(action.get("status", ""), action.get("status", ""))
        ageing = action.get("ageing_cycles", 0)
        ageing_text = (
            f"open across {ageing} meeting cycle{'s' if ageing != 1 else ''}"
            if ageing
            else "first cycle"
        )
        yield Block("h2", f"2.{index}  {_truncate(action.get('action', ''), 140)}")
        yield Block("kv", label="Status", text=f"{status} ({ageing_text})")
        yield Block("kv", label="Owner", text=action.get("owner", "not recorded"))
        yield Block(
            "kv",
            label="Raised / committed",
            text=f"{action.get('raised_at', 'not recorded')} / "
            f"{action.get('committed_date', 'not recorded')}",
        )
        yield Block("kv", label="Basis for status", text=action.get("status_basis", ""))
        yield Block("cite", items=citations_for(action.get("evidence", []), cmap))

    # --- 3. Performance ------------------------------------------------------
    yield Block("h1", "3. Material performance changes")
    changes = b.get("performance_changes") or []
    if not changes:
        yield Block("para", "No material performance changes were identified in this pack.")
    for index, change in enumerate(changes, start=1):
        direction = DIRECTION_LABELS.get(change.get("direction", ""), change.get("direction", ""))
        yield Block("h2", f"3.{index}  {change.get('metric', '')}  [{direction}]")
        yield Block("kv", label="Movement", text=change.get("movement", ""))
        yield Block("kv", label="Why it matters", text=change.get("materiality", ""))
        yield Block(
            "kv", label="Explanation offered", text=change.get("explanation_given", "")
        )
        yield Block("cite", items=citations_for(change.get("evidence", []), cmap))

    # --- 4. Questions --------------------------------------------------------
    yield Block("h1", "4. Questions the board should put to management")
    questions = b.get("management_questions") or []
    if not questions:
        yield Block("para", "No questions were generated from this pack.")
    for index, question in enumerate(questions, start=1):
        priority = SEVERITY_LABELS.get(question.get("priority", ""), question.get("priority", ""))
        yield Block(
            "h2",
            f"4.{index}  To {question.get('directed_to', 'management')}  [{priority} priority]",
        )
        yield Block("para", f"“{question.get('question', '')}”")
        yield Block("kv", label="Why ask it", text=question.get("rationale", ""))
        yield Block("cite", items=citations_for(question.get("evidence", []), cmap))

    # --- 5. Decisions --------------------------------------------------------
    yield Block("h1", "5. Decisions required at this meeting")
    decisions = b.get("decisions_required") or []
    if not decisions:
        yield Block("para", "This pack puts no decisions to the board for this meeting.")
    for index, decision in enumerate(decisions, start=1):
        yield Block("h2", f"5.{index}  {_truncate(decision.get('decision', ''), 140)}")
        yield Block("kv", label="Proposed by", text=decision.get("proposed_by", ""))
        yield Block("kv", label="Financial impact", text=decision.get("financial_impact", ""))
        yield Block("kv", label="Basis for approval", text=decision.get("approval_basis", ""))
        yield Block("kv", label="Is the board equipped to decide", text=decision.get("readiness", ""))
        yield Block("kv", label="Governance considerations", text=decision.get("considerations", ""))
        yield Block("cite", items=citations_for(decision.get("evidence", []), cmap))

    # --- Coverage ------------------------------------------------------------
    yield Block("h1", "Coverage and limitations")
    yield Block("para", b.get("coverage_note", "Not stated."))

    issues = verification.get("issues") or []
    if issues:
        yield Block("h2", "Statements requiring reviewer attention")
        yield Block(
            "para",
            "The following findings could not be resolved to a source page. They are "
            "retained so the reviewer can judge them, and should be confirmed or removed "
            "before the briefing is circulated to directors.",
        )
        yield Block(
            "bullets",
            items=[f"{i['section']}: {i['item_label']} - {i['detail']}" for i in issues],
        )

    # --- Annexure: full action register --------------------------------------
    if doc.action_register:
        yield Block("pagebreak")
        yield Block("h1", "Annexure A - Complete action register")
        yield Block(
            "para",
            "Section 2 carries the five actions most needing board time. This annexure "
            "is the complete standing register for this board, so that no item is lost "
            "between meetings.",
        )
        yield Block(
            "table",
            label="Action register",
            items=[
                ["Action", "Owner", "Raised", "Due", "Status", "Cycles"],
                *[
                    [
                        _truncate(a.get("action", ""), 220),
                        a.get("owner", ""),
                        a.get("raised_at", ""),
                        a.get("committed_date", ""),
                        STATUS_LABELS.get(a.get("status", ""), a.get("status", "")),
                        str(a.get("ageing_cycles", 0)),
                    ]
                    for a in doc.action_register
                ],
            ],
        )

    # --- Annexure: source index ----------------------------------------------
    if cmap:
        yield Block("pagebreak")
        yield Block("h1", "Annexure B - Source index")
        yield Block(
            "para",
            "Every reference used in this briefing, with the passage it was drawn from.",
        )
        yield Block(
            "table",
            label="Source index",
            items=[
                ["Ref", "Document", "Location", "Passage"],
                *[
                    [
                        record["chunk_id"],
                        record["document"],
                        record["locator"],
                        record["excerpt"],
                    ]
                    for record in sorted(cmap.values(), key=lambda r: r["chunk_id"])
                ],
            ],
        )


def _truncate(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def _pretty_date(value: str) -> str:
    if not value:
        return "not stated"
    try:
        return date.fromisoformat(value[:10]).strftime("%d %B %Y")
    except ValueError:
        return value
