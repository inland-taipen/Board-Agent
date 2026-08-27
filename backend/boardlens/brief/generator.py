"""The briefing pipeline.

Five passes, in order:

1. DIGEST      - each document is read in windows and reduced to a structured
                 digest. This is the only pass that sees every page, and it is
                 what lets a 500-page pack reach synthesis without truncation.
2. EXTRACT     - prior minutes are read again, separately, for action items.
                 A dedicated pass beats asking the digest to do double duty:
                 exhaustive extraction and executive summarisation pull in
                 opposite directions.
3. RECONCILE   - every carried-forward action is checked against evidence
                 retrieved from the CURRENT pack, and its status written back.
4. SYNTHESISE  - digests, the reconciled register and section-targeted evidence
                 are reasoned across to produce the briefing.
5. VERIFY      - every citation is resolved against the index; one repair pass
                 is attempted if any citation is unsupported.

Passes 1 and 2 fan out across documents; the rest are sequential because each
depends on the last.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from ..actions import tracker
from ..config import get_settings
from ..ingest.base import DocKind
from ..llm import LLMError, generate_structured
from ..rag import SECTION_PLANS, Chunk, PackIndex, gather, render_evidence
from . import prompts
from .schema import (
    ActionExtraction,
    BoardBriefing,
    DocumentDigest,
    ReconciliationBatch,
)
from .verify import VerificationReport, verify

log = logging.getLogger(__name__)

# Characters of evidence per pass. Kept well inside the context window so that
# thinking and output have room, and so a single oversized document cannot
# starve the others.
DIGEST_WINDOW_CHARS = 60_000
EXTRACTION_WINDOW_CHARS = 45_000
RECONCILE_EVIDENCE_CHARS = 40_000
SECTION_EVIDENCE_CHARS = 26_000

RECONCILE_BATCH = 10
MAX_PARALLEL_PASSES = 4

ProgressFn = Callable[[str], None]


@dataclass
class DocumentInput:
    doc_id: str
    name: str
    kind: str
    chunks: list[Chunk]
    ocr_pages: list[int] = field(default_factory=list)


@dataclass
class BriefingResult:
    briefing: BoardBriefing
    verification: VerificationReport
    digests: dict[str, DocumentDigest]
    actions_created: int
    actions_matched: int
    actions_reconciled: int
    coverage_warnings: list[str]


def generate_briefing(
    *,
    client_id: str,
    pack_id: str,
    company: str,
    meeting_label: str,
    documents: list[DocumentInput],
    index: PackIndex,
    user_id: str = "",
    progress: ProgressFn | None = None,
) -> BriefingResult:
    settings = get_settings()
    emit = progress or (lambda _msg: None)
    warnings = _coverage_warnings(documents)

    # --- 1. Digest ----------------------------------------------------------
    emit(f"Reading {len(documents)} documents ({sum(len(d.chunks) for d in documents)} chunks)")
    digests = _digest_documents(documents, effort=settings.digest_effort, emit=emit)
    for doc in documents:
        if doc.doc_id not in digests:
            warnings.append(
                f"{doc.name}: the digest pass failed, so this document reached synthesis "
                "only through retrieved evidence."
            )

    # --- 2. Extract actions from prior minutes ------------------------------
    minutes = [d for d in documents if d.kind == DocKind.PRIOR_MINUTES]
    created = matched = 0
    if minutes:
        emit(f"Extracting action items from {len(minutes)} minutes document(s)")
        extracted = _extract_actions(minutes, emit=emit)
        created, matched = tracker.ingest_extracted(
            client_id, pack_id, extracted, user_id=user_id
        )
        emit(f"Action register: {created} new, {matched} already tracked")
    else:
        warnings.append(
            "No prior minutes were uploaded with this pack. Unresolved actions are "
            "reported from the standing register only; items raised at the last "
            "meeting will not appear until its minutes are uploaded."
        )

    # --- 3. Reconcile against the current pack ------------------------------
    carried = tracker.carry_forward(client_id)
    reconciled = 0
    if carried:
        emit(f"Reconciling {len(carried)} carried-forward actions against this pack")
        reconciliations = _reconcile_actions(carried, index, emit=emit)
        reconciled = tracker.apply_reconciliation(
            client_id, reconciliations, pack_id=pack_id, user_id=user_id
        )
        carried = tracker.carry_forward(client_id)
    else:
        warnings.append(
            "The action register is empty for this board, so no items could be "
            "carried forward into this briefing."
        )

    # --- 4. Synthesise ------------------------------------------------------
    emit("Retrieving section evidence")
    section_evidence = _section_evidence(index)

    emit("Synthesising the board briefing")
    user_prompt = prompts.synthesis_user_prompt(
        company=company,
        meeting_label=meeting_label,
        pack_manifest=_manifest(documents),
        digests=_render_digests(documents, digests),
        action_register=tracker.render_register(carried),
        section_evidence=section_evidence,
        coverage_warnings="\n".join(f"- {w}" for w in warnings),
    )

    briefing = generate_structured(
        system=prompts.SYNTHESIS_SYSTEM,
        user=user_prompt,
        output_model=BoardBriefing,
        effort=settings.effort,
        max_tokens=32_000,
    )

    # --- 5. Verify (and repair once) ----------------------------------------
    emit("Verifying citations against source pages")
    report = verify(briefing, index)

    if report.issues:
        emit(f"Repairing {len(report.issues)} unsupported citation(s)")
        try:
            briefing = _repair(briefing, report, user_prompt, settings.effort)
            report = verify(briefing, index)
        except LLMError as exc:
            log.warning("citation repair pass failed: %s", exc)
            warnings.append(
                "A citation repair pass was attempted and did not complete; the "
                "flagged items below remain unverified."
            )

    emit(
        f"Briefing ready - {report.grounded_items}/{report.total_items} items grounded, "
        f"{report.resolved_citations}/{report.total_citations} citations resolved"
    )

    return BriefingResult(
        briefing=briefing,
        verification=report,
        digests=digests,
        actions_created=created,
        actions_matched=matched,
        actions_reconciled=reconciled,
        coverage_warnings=warnings,
    )


# --- Pass 1: digests ---------------------------------------------------------


def _digest_documents(
    documents: list[DocumentInput], *, effort: str, emit: ProgressFn
) -> dict[str, DocumentDigest]:
    jobs: list[tuple[DocumentInput, int, str]] = []
    for doc in documents:
        for window_no, window in enumerate(_windows(doc.chunks, DIGEST_WINDOW_CHARS), start=1):
            jobs.append((doc, window_no, window))

    results: dict[str, list[DocumentDigest]] = {}
    completed = 0

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_PASSES) as pool:
        futures = {
            pool.submit(
                generate_structured,
                system=prompts.DIGEST_SYSTEM,
                user=prompts.digest_user_prompt(doc.name, doc.kind, window),
                output_model=DocumentDigest,
                effort=effort,
                max_tokens=12_000,
            ): (doc, window_no)
            for doc, window_no, window in jobs
        }

        for future in as_completed(futures):
            doc, window_no = futures[future]
            completed += 1
            try:
                results.setdefault(doc.doc_id, []).append(future.result())
            except LLMError as exc:
                log.warning("digest failed for %s window %s: %s", doc.name, window_no, exc)
            emit(f"Read {completed}/{len(jobs)} document sections")

    return {doc_id: _merge_digests(parts) for doc_id, parts in results.items() if parts}


def _merge_digests(parts: list[DocumentDigest]) -> DocumentDigest:
    if len(parts) == 1:
        return parts[0]
    return DocumentDigest(
        document_purpose=parts[0].document_purpose,
        key_points=_dedupe(p for part in parts for p in part.key_points),
        risks_flagged=_dedupe(p for part in parts for p in part.risks_flagged),
        decisions_sought=_dedupe(p for part in parts for p in part.decisions_sought),
        figures_of_note=_dedupe(p for part in parts for p in part.figures_of_note),
        anomalies=_dedupe(p for part in parts for p in part.anomalies),
    )


def _dedupe(items) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = " ".join(item.lower().split())
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


# --- Pass 2: action extraction -----------------------------------------------


def _extract_actions(minutes: list[DocumentInput], *, emit: ProgressFn) -> list[dict]:
    jobs = [
        window
        for doc in minutes
        for window in _windows(doc.chunks, EXTRACTION_WINDOW_CHARS)
    ]

    collected: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_PASSES) as pool:
        futures = [
            pool.submit(
                generate_structured,
                system=prompts.ACTION_EXTRACTION_SYSTEM,
                user=prompts.action_extraction_user_prompt(window),
                output_model=ActionExtraction,
                effort="high",  # Exhaustiveness is the whole point of this pass.
                max_tokens=16_000,
            )
            for window in jobs
        ]
        for done, future in enumerate(as_completed(futures), start=1):
            try:
                collected.extend(a.model_dump() for a in future.result().actions)
            except LLMError as exc:
                log.warning("action extraction failed: %s", exc)
            emit(f"Scanned {done}/{len(jobs)} minutes section(s)")

    return collected


# --- Pass 3: reconciliation --------------------------------------------------


def _reconcile_actions(
    carried: list[tracker.ActionRecord], index: PackIndex, *, emit: ProgressFn
) -> list[dict]:
    out: list[dict] = []
    batches = [
        carried[i : i + RECONCILE_BATCH] for i in range(0, len(carried), RECONCILE_BATCH)
    ]

    for batch_no, batch in enumerate(batches, start=1):
        action_block = "\n".join(
            f"[{r.id}] {r.action}\n"
            f"    owner: {r.owner} | raised: {r.raised_at} | committed: {r.committed_date}"
            for r in batch
        )

        # Retrieve against each action's own text so the model sees whatever the
        # current pack says about that specific item, if anything.
        evidence_chunks: dict[str, Chunk] = {}
        for record in batch:
            for hit in index.search(record.action, top_k=5):
                evidence_chunks.setdefault(hit.chunk.chunk_id, hit.chunk)

        evidence = render_evidence(
            list(evidence_chunks.values()), max_chars=RECONCILE_EVIDENCE_CHARS
        )

        try:
            result = generate_structured(
                system=prompts.RECONCILE_SYSTEM,
                user=prompts.reconcile_user_prompt(action_block, evidence),
                output_model=ReconciliationBatch,
                effort="medium",
                max_tokens=12_000,
            )
            out.extend(r.model_dump() for r in result.reconciliations)
        except LLMError as exc:
            log.warning("reconciliation batch %s failed: %s", batch_no, exc)

        emit(f"Reconciled batch {batch_no}/{len(batches)}")

    return out


# --- Pass 4 support: evidence assembly ---------------------------------------


def _section_evidence(index: PackIndex) -> str:
    blocks: list[str] = []
    for plan in SECTION_PLANS:
        chunks = gather(index, plan)
        rendered = render_evidence(chunks, max_chars=SECTION_EVIDENCE_CHARS)
        heading = plan.key.replace("_", " ").upper()
        blocks.append(
            f"--- EVIDENCE FOR {heading} ---\n"
            f"{rendered or '(no evidence retrieved for this section)'}"
        )
    return "\n\n".join(blocks)


def _manifest(documents: list[DocumentInput]) -> str:
    lines = []
    for doc in documents:
        pages = max((c.page for c in doc.chunks), default=0)
        note = f", {len(doc.ocr_pages)} page(s) not machine-readable" if doc.ocr_pages else ""
        lines.append(
            f"- {doc.name} [{doc.kind.replace('_', ' ')}] - "
            f"{pages} page(s)/slide(s), {len(doc.chunks)} chunks{note}"
        )
    return "\n".join(lines)


def _render_digests(
    documents: list[DocumentInput], digests: dict[str, DocumentDigest]
) -> str:
    blocks = []
    for doc in documents:
        digest = digests.get(doc.doc_id)
        if digest is None:
            blocks.append(f"### {doc.name}\n(digest unavailable - see coverage gaps)")
            continue
        blocks.append(
            f"### {doc.name} [{doc.kind.replace('_', ' ')}]\n"
            f"Purpose: {digest.document_purpose}\n"
            f"Key points:\n{_bullets(digest.key_points)}\n"
            f"Risks flagged:\n{_bullets(digest.risks_flagged)}\n"
            f"Decisions sought:\n{_bullets(digest.decisions_sought)}\n"
            f"Figures of note:\n{_bullets(digest.figures_of_note)}\n"
            f"Anomalies:\n{_bullets(digest.anomalies)}"
        )
    return "\n\n".join(blocks)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"  - {i}" for i in items) if items else "  - none"


def _windows(chunks: list[Chunk], max_chars: int) -> list[str]:
    """Group chunks into prompt-sized windows, preserving document order."""
    windows: list[str] = []
    buf: list[str] = []
    size = 0
    for chunk in chunks:
        rendered = chunk.render()
        if size + len(rendered) > max_chars and buf:
            windows.append("\n\n".join(buf))
            buf, size = [], 0
        buf.append(rendered)
        size += len(rendered) + 2
    if buf:
        windows.append("\n\n".join(buf))
    return windows


def _coverage_warnings(documents: list[DocumentInput]) -> list[str]:
    warnings: list[str] = []
    for doc in documents:
        if doc.ocr_pages:
            pages = ", ".join(str(p) for p in doc.ocr_pages[:12])
            more = "..." if len(doc.ocr_pages) > 12 else ""
            warnings.append(
                f"{doc.name}: pages {pages}{more} contain no extractable text "
                "(scanned or image-only) and were not assessed."
            )
        if not doc.chunks:
            warnings.append(f"{doc.name}: no readable content was extracted from this file.")
    return warnings


# --- Pass 5: repair ----------------------------------------------------------


def _repair(
    briefing: BoardBriefing,
    report: VerificationReport,
    original_prompt: str,
    effort: str,
) -> BoardBriefing:
    """One corrective pass over unsupported citations.

    The model is given its own draft and the specific failures, and asked to fix
    only those - either by citing a real chunk or by withdrawing the claim. It
    is explicitly told that withdrawing is acceptable, because the alternative
    is that it invents a different wrong ID to fill the slot.
    """
    problems = "\n".join(
        f"- [{i.section} #{i.item_index + 1}] {i.item_label}: {i.detail}"
        for i in report.issues
    )
    instruction = (
        f"{original_prompt}\n\n"
        f"PREVIOUS DRAFT\n==============\n{briefing.model_dump_json(indent=2)}\n\n"
        f"CITATION FAILURES TO CORRECT\n============================\n{problems}\n\n"
        "Re-issue the complete briefing. Leave every item that verified cleanly "
        "exactly as it stands - do not reword it, do not reorder sections. For each "
        "failure listed above, either cite a chunk ID that genuinely appears in the "
        "evidence above and supports the statement, or remove the unsupported claim "
        "and replace it with one you can ground. Withdrawing a claim you cannot "
        "support is the correct outcome; substituting a different unverified ID is not."
    )
    return generate_structured(
        system=prompts.SYNTHESIS_SYSTEM,
        user=instruction,
        output_model=BoardBriefing,
        effort=effort,
        max_tokens=32_000,
    )
