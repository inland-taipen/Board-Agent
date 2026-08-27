"""Structured output contract for the Board Briefing.

These models are passed straight to `client.messages.parse(output_format=...)`,
so their shape *is* the JSON schema the model is constrained to. Two
conventions matter:

* Every field is required. Optional fields in a strict schema invite the model
  to omit the awkward ones - and the awkward field here is usually `evidence`,
  which is the one thing the BRD makes non-negotiable.
* `evidence` is always a list of chunk IDs, never free text. Verification
  resolves those IDs against the index; anything the model invents is caught
  rather than published.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low"]
Direction = Literal["improvement", "deterioration", "mixed", "neutral"]
ActionStatus = Literal["open", "in_progress", "completed", "superseded", "unclear"]


class Evidenced(BaseModel):
    """Base for anything that must be traceable to source pages."""

    evidence: list[str] = Field(
        description="Chunk IDs (e.g. 'c0042') that directly support this item. "
        "Cite only IDs present in the supplied evidence. Minimum one."
    )


class CriticalRisk(Evidenced):
    title: str = Field(description="Short risk name, under 12 words.")
    severity: Severity
    why_now: str = Field(
        description="Why this risk demands board attention at THIS meeting rather than "
        "being a standing concern. Two to three sentences."
    )
    exposure: str = Field(
        description="The quantified or qualified exposure, using figures from the pack "
        "where available. State 'not quantified in the pack' if absent."
    )
    management_position: str = Field(
        description="What management says about it in the pack, or 'not addressed in the pack'."
    )
    gap: str = Field(
        description="What the pack does not tell the board about this risk."
    )


class UnresolvedAction(Evidenced):
    action: str = Field(description="The action as recorded, in the board's own language.")
    owner: str = Field(description="Named owner or function; 'not recorded' if absent.")
    raised_at: str = Field(
        description="Meeting or date at which it was raised, as recorded in the minutes."
    )
    committed_date: str = Field(
        description="Target date as recorded; 'not recorded' if the minutes gave none."
    )
    status: ActionStatus
    status_basis: str = Field(
        description="The evidence for the status call - what in the current pack shows "
        "this was or was not closed. If nothing in the current pack addresses it, say so "
        "explicitly; that silence is itself the finding."
    )
    ageing_cycles: int = Field(
        description="Number of meeting cycles this item has been open, 0 if unknown."
    )


class PerformanceChange(Evidenced):
    metric: str = Field(description="The metric or line item, named as the pack names it.")
    movement: str = Field(
        description="The movement with both figures and the basis of comparison, "
        "e.g. 'EBITDA margin 14.2% vs 17.8% in Q2 FY26'."
    )
    direction: Direction
    materiality: str = Field(
        description="Why this movement is material to the board - scale relative to the "
        "business, covenant proximity, guidance impact, or trend break."
    )
    explanation_given: str = Field(
        description="The explanation management offers in the pack, or 'no explanation "
        "given in the pack' - an unexplained material movement is a finding."
    )


class ManagementQuestion(Evidenced):
    question: str = Field(
        description="The question, phrased as a director would put it to management in the "
        "meeting. Specific and answerable, not rhetorical."
    )
    rationale: str = Field(description="What in the pack prompts this question.")
    directed_to: str = Field(description="Role best placed to answer, e.g. 'CFO', 'CRO'.")
    priority: Severity


class DecisionRequired(Evidenced):
    decision: str = Field(description="The decision sought, as the pack frames it.")
    proposed_by: str = Field(description="Who is putting it to the board.")
    financial_impact: str = Field(
        description="Quantified impact, or 'not quantified in the pack'."
    )
    approval_basis: str = Field(
        description="What the board is being asked to rely on - the paper, an external "
        "opinion, a committee recommendation."
    )
    readiness: str = Field(
        description="Whether the pack contains what the board needs to decide. Name what "
        "is missing if it does not."
    )
    considerations: str = Field(
        description="Governance considerations - related-party angle, conflicts, statutory "
        "approval, disclosure obligation. 'None identified' is a valid answer."
    )


class BoardBriefing(BaseModel):
    """The full briefing, matching the BRD's mandated five-section structure."""

    meeting_context: str = Field(
        description="Two to four sentences orienting the reader: the company, the meeting, "
        "the period covered, and what the pack is principally about."
    )
    critical_risks: list[CriticalRisk] = Field(
        description="Exactly three, ordered most critical first."
    )
    unresolved_actions: list[UnresolvedAction] = Field(
        description="The five most consequential unresolved actions, ordered by consequence."
    )
    performance_changes: list[PerformanceChange] = Field(
        description="Three to six material performance movements."
    )
    management_questions: list[ManagementQuestion] = Field(
        description="Five to eight questions, ordered by priority."
    )
    decisions_required: list[DecisionRequired] = Field(
        description="Every decision the pack puts to this meeting. Empty list if none."
    )
    coverage_note: str = Field(
        description="What of the pack could not be assessed and why - unparsed scans, "
        "absent prior minutes, sections outside the evidence supplied. State 'full pack "
        "assessed' only if genuinely true."
    )


# --- Intermediate structures used inside the pipeline ------------------------


class ExtractedAction(BaseModel):
    """One action item lifted from prior minutes during the extraction pass."""

    action: str
    owner: str
    raised_at: str
    committed_date: str
    evidence: list[str]


class ActionExtraction(BaseModel):
    """Exhaustive extraction from a slice of prior minutes.

    Exhaustiveness is the point: the BRD's stated objective is that 100% of
    unresolved actions surface in every briefing, so this pass is instructed to
    over-collect and let the reconciliation pass decide what is closed.
    """

    actions: list[ExtractedAction]


class DocumentDigest(BaseModel):
    """Per-document summary produced in the map phase."""

    document_purpose: str
    key_points: list[str] = Field(
        description="Substantive findings with figures, each ending with its supporting "
        "chunk IDs in square brackets, e.g. '... [c0042, c0043]'."
    )
    risks_flagged: list[str]
    decisions_sought: list[str]
    figures_of_note: list[str]
    anomalies: list[str] = Field(
        description="Internal inconsistencies, unexplained movements, or claims made "
        "without support anywhere in the document."
    )


class ActionReconciliation(BaseModel):
    """Status call for one carried-forward action against the current pack."""

    action_id: str
    status: ActionStatus
    status_basis: str
    evidence: list[str]


class ReconciliationBatch(BaseModel):
    """List-shaped root for the reconciliation pass.

    JSON schema output must have an object at the root, so a batch of
    reconciliations is wrapped rather than returned as a bare array.
    """

    reconciliations: list[ActionReconciliation]
