"""Section-aware evidence gathering.

Each briefing section has a different notion of "relevant", and a single
generic query per section retrieves shallowly. Instead every section fans out
across several phrasings and biases toward the document kinds that actually
carry that answer - unresolved actions live in minutes, not in the deck.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ingest.base import DocKind
from .chunker import Chunk
from .index import Hit, PackIndex


@dataclass(frozen=True)
class SectionPlan:
    key: str
    queries: tuple[str, ...]
    doc_kinds: tuple[str, ...]
    top_k: int


SECTION_PLANS: tuple[SectionPlan, ...] = (
    SectionPlan(
        key="critical_risks",
        queries=(
            "principal risk exposure escalating severity likelihood mitigation owner",
            "regulatory non-compliance penalty notice show cause litigation contingent liability",
            "internal audit adverse finding control failure repeat observation unresolved",
            "liquidity covenant breach receivables concentration credit exposure going concern",
            "cyber security incident data breach IT outage business continuity",
            "key management attrition succession single point of dependency",
        ),
        doc_kinds=(
            DocKind.RISK_REPORT,
            DocKind.INTERNAL_AUDIT,
            DocKind.BOARD_DECK,
            DocKind.FINANCIAL_PACK,
            DocKind.BUSINESS_UPDATE,
        ),
        top_k=14,
    ),
    SectionPlan(
        key="unresolved_actions",
        queries=(
            "action point owner responsibility target date to be placed before the board",
            "management was advised directed requested to revert at the next meeting",
            "deferred carried forward pending awaiting update status open item",
            "the board noted and directed that action taken report",
        ),
        doc_kinds=(DocKind.PRIOR_MINUTES, DocKind.BOARD_DECK),
        top_k=18,
    ),
    SectionPlan(
        key="performance_changes",
        queries=(
            "revenue growth decline versus prior quarter year on year variance",
            "EBITDA margin contraction expansion cost escalation gross margin",
            "cash flow working capital debtor days inventory borrowings net debt",
            "budget versus actual shortfall overrun guidance revision forecast",
            "segment performance order book pipeline volumes realisation",
        ),
        doc_kinds=(DocKind.FINANCIAL_PACK, DocKind.BOARD_DECK, DocKind.BUSINESS_UPDATE),
        top_k=16,
    ),
    SectionPlan(
        key="management_questions",
        queries=(
            "assumption underlying projection sensitivity basis of estimate",
            "explanation for variance reason attributed to management commentary",
            "capital expenditure commitment approval investment rationale payback",
            "related party transaction subsidiary guarantee inter-corporate deposit",
            "one-off exceptional item provision write-off impairment reversal",
        ),
        doc_kinds=(),  # Questions can arise anywhere in the pack.
        top_k=14,
    ),
    SectionPlan(
        key="decisions_required",
        queries=(
            "for the approval of the board resolution proposed recommended",
            "seeking approval sanction ratification noting item agenda item",
            "recommend that the board approve authorise adopt",
            "matters reserved for the board delegation of authority limits",
        ),
        doc_kinds=(DocKind.BOARD_DECK, DocKind.PRIOR_MINUTES, DocKind.OTHER),
        top_k=14,
    ),
)

PLANS_BY_KEY = {p.key: p for p in SECTION_PLANS}


def gather(index: PackIndex, plan: SectionPlan) -> list[Chunk]:
    """Run a section plan and return de-duplicated chunks in relevance order.

    Chunks are scored by the best rank they achieved across the plan's
    queries, so a chunk that is the top hit for one phrasing outranks one that
    is mediocre for several.
    """
    best: dict[str, tuple[float, Chunk]] = {}

    for query in plan.queries:
        hits: list[Hit] = index.search(
            query, top_k=plan.top_k, doc_kinds=list(plan.doc_kinds) or None
        )
        for rank, hit in enumerate(hits):
            weight = 1.0 / (rank + 1)
            current = best.get(hit.chunk.chunk_id)
            if current is None or weight > current[0]:
                best[hit.chunk.chunk_id] = (weight, hit.chunk)

    ordered = sorted(best.values(), key=lambda kv: -kv[0])
    return [chunk for _, chunk in ordered[: plan.top_k]]


def render_evidence(chunks: list[Chunk], max_chars: int = 120_000) -> str:
    """Render chunks for the prompt, truncating at a hard character budget.

    Truncation is reported rather than silent - the caller surfaces it so a
    reviewer knows the section did not see the full evidence set.
    """
    parts: list[str] = []
    used = 0
    for chunk in chunks:
        rendered = chunk.render()
        if used + len(rendered) > max_chars:
            break
        parts.append(rendered)
        used += len(rendered) + 2
    return "\n\n".join(parts)
