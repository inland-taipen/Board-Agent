"""Cross-cycle action-item store.

This is the component that makes the BRD's "100% of unresolved actions in every
briefing" objective achievable. Extraction alone is not enough: an item raised
three meetings ago, never mentioned since, appears in no document in the
current pack. It survives only because it is in this table.

Deduplication is by fingerprint over the significant words of the action text.
Minutes reword the same standing item between cycles ("management to place the
IT security roadmap before the Board" / "the IT security roadmap to be placed
before the Board"), and treating those as two items would inflate the register
until directors stopped reading it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..db import audit, execute, new_id, now, query, transaction
from ..rag.index import tokenize

# Fingerprinting on the most distinctive words survives reordering and
# voice changes while still separating genuinely different actions.
_FINGERPRINT_TERMS = 12

OPEN_STATUSES = ("open", "in_progress", "unclear")


@dataclass
class ActionRecord:
    id: str
    action: str
    owner: str
    raised_at: str
    committed_date: str
    status: str
    status_basis: str
    ageing_cycles: int
    evidence: list[str] = field(default_factory=list)
    first_seen_pack: str = ""
    last_seen_pack: str = ""

    @classmethod
    def from_row(cls, row) -> ActionRecord:
        return cls(
            id=row["id"],
            action=row["action"],
            owner=row["owner"],
            raised_at=row["raised_at"],
            committed_date=row["committed_date"],
            status=row["status"],
            status_basis=row["status_basis"],
            ageing_cycles=row["ageing_cycles"],
            evidence=json.loads(row["evidence"] or "[]"),
            first_seen_pack=row["first_seen_pack"],
            last_seen_pack=row["last_seen_pack"],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action": self.action,
            "owner": self.owner,
            "raised_at": self.raised_at,
            "committed_date": self.committed_date,
            "status": self.status,
            "status_basis": self.status_basis,
            "ageing_cycles": self.ageing_cycles,
            "evidence": self.evidence,
        }


def _stem(token: str) -> str:
    """Conservative suffix stripping, used only for fingerprinting.

    Minutes restate a standing item in a different voice from cycle to cycle -
    "management to place the roadmap before the Board" becomes "the roadmap to
    be placed before the Board". Without stemming, place/placed/placing produce
    three fingerprints and the register fills with duplicates of one item.

    Retrieval deliberately does NOT stem: BM25 matching on exact terms is what
    makes "Ind AS 116" and "DSCR" findable, and stemming those would cost more
    than it gains.
    """
    if len(token) <= 4:
        return token

    for suffix, replacement in (("ing", ""), ("ed", ""), ("ies", "y"), ("es", "")):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            token = token[: -len(suffix)] + replacement
            break
    else:
        if token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]

    if len(token) > 3 and token.endswith("e"):
        token = token[:-1]
    return token


def fingerprint(action: str) -> str:
    terms = sorted({_stem(t) for t in tokenize(action)})[:_FINGERPRINT_TERMS]
    if not terms:
        terms = [action.strip().lower()[:80]]
    return hashlib.sha256(" ".join(terms).encode()).hexdigest()[:32]


def carry_forward(client_id: str) -> list[ActionRecord]:
    """Every action not yet demonstrably closed, oldest first."""
    rows = query(
        """
        SELECT * FROM action_items
        WHERE client_id = ? AND status IN (?, ?, ?)
        ORDER BY ageing_cycles DESC, created_at ASC
        """,
        (client_id, *OPEN_STATUSES),
    )
    return [ActionRecord.from_row(r) for r in rows]


def register(client_id: str, *, include_closed: bool = True) -> list[ActionRecord]:
    sql = "SELECT * FROM action_items WHERE client_id = ?"
    params: tuple = (client_id,)
    if not include_closed:
        sql += " AND status IN (?,?,?)"
        params = (client_id, *OPEN_STATUSES)
    sql += " ORDER BY CASE status WHEN 'unclear' THEN 0 WHEN 'open' THEN 1 "
    sql += "WHEN 'in_progress' THEN 2 ELSE 3 END, ageing_cycles DESC"
    return [ActionRecord.from_row(r) for r in query(sql, params)]


def ingest_extracted(
    client_id: str,
    pack_id: str,
    extracted: list[dict],
    *,
    user_id: str = "",
) -> tuple[int, int]:
    """Merge freshly extracted actions into the store.

    Returns (created, matched). An action already in the store has its ageing
    incremented only when it reappears in a *later* pack, so re-running the
    briefing for the same meeting does not age the register.
    """
    created = matched = 0
    timestamp = now()

    with transaction() as conn:
        for item in extracted:
            action_text = (item.get("action") or "").strip()
            if not action_text:
                continue

            fp = fingerprint(action_text)
            existing = conn.execute(
                "SELECT * FROM action_items WHERE client_id = ? AND fingerprint = ?",
                (client_id, fp),
            ).fetchone()

            if existing:
                matched += 1
                ageing = existing["ageing_cycles"]
                if existing["last_seen_pack"] != pack_id:
                    ageing += 1
                conn.execute(
                    """
                    UPDATE action_items
                       SET last_seen_pack = ?, ageing_cycles = ?, updated_at = ?,
                           owner = CASE WHEN owner = 'not recorded' THEN ? ELSE owner END,
                           committed_date = CASE WHEN committed_date = 'not recorded'
                                            THEN ? ELSE committed_date END
                     WHERE id = ?
                    """,
                    (
                        pack_id,
                        ageing,
                        timestamp,
                        item.get("owner") or "not recorded",
                        item.get("committed_date") or "not recorded",
                        existing["id"],
                    ),
                )
                continue

            created += 1
            conn.execute(
                """
                INSERT INTO action_items
                    (id, client_id, action, owner, raised_at, committed_date, status,
                     status_basis, ageing_cycles, fingerprint, evidence,
                     first_seen_pack, last_seen_pack, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    new_id("act"),
                    client_id,
                    action_text,
                    item.get("owner") or "not recorded",
                    item.get("raised_at") or "not recorded",
                    item.get("committed_date") or "not recorded",
                    "open",
                    "Newly extracted from prior minutes; not yet reconciled.",
                    0,
                    fp,
                    json.dumps(item.get("evidence") or []),
                    pack_id,
                    pack_id,
                    timestamp,
                    timestamp,
                ),
            )

    audit(
        "actions.ingest",
        user_id=user_id,
        client_id=client_id,
        detail={"pack_id": pack_id, "created": created, "matched": matched},
    )
    return created, matched


def apply_reconciliation(
    client_id: str,
    reconciliations: list[dict],
    *,
    pack_id: str = "",
    user_id: str = "",
) -> int:
    """Write back statuses decided against the current pack."""
    updated = 0
    timestamp = now()

    with transaction() as conn:
        for rec in reconciliations:
            action_id = rec.get("action_id")
            status = rec.get("status")
            if not action_id or status not in (
                "open",
                "in_progress",
                "completed",
                "superseded",
                "unclear",
            ):
                continue

            row = conn.execute(
                "SELECT id FROM action_items WHERE id = ? AND client_id = ?",
                (action_id, client_id),
            ).fetchone()
            if row is None:
                # Scoped by client_id, so a reconciliation naming an action from
                # another client silently does nothing rather than crossing the
                # segregation boundary.
                continue

            closed_at = timestamp if status in ("completed", "superseded") else None
            conn.execute(
                """
                UPDATE action_items
                   SET status = ?, status_basis = ?, evidence = ?, closed_at = ?,
                       updated_at = ?, last_seen_pack = COALESCE(NULLIF(?, ''), last_seen_pack)
                 WHERE id = ?
                """,
                (
                    status,
                    rec.get("status_basis") or "",
                    json.dumps(rec.get("evidence") or []),
                    closed_at,
                    timestamp,
                    pack_id,
                    action_id,
                ),
            )
            updated += 1

    audit(
        "actions.reconcile",
        user_id=user_id,
        client_id=client_id,
        detail={"pack_id": pack_id, "updated": updated},
    )
    return updated


def set_status(
    client_id: str, action_id: str, status: str, basis: str, *, user_id: str = ""
) -> bool:
    """Manual override by a company secretary reviewing the register."""
    if status not in ("open", "in_progress", "completed", "superseded", "unclear"):
        return False
    timestamp = now()
    closed_at = timestamp if status in ("completed", "superseded") else None
    execute(
        """
        UPDATE action_items
           SET status = ?, status_basis = ?, closed_at = ?, updated_at = ?
         WHERE id = ? AND client_id = ?
        """,
        (status, basis, closed_at, timestamp, action_id, client_id),
    )
    audit(
        "actions.override",
        user_id=user_id,
        client_id=client_id,
        detail={"action_id": action_id, "status": status},
    )
    return True


def render_register(records: list[ActionRecord]) -> str:
    """Render the register for the synthesis prompt."""
    if not records:
        return "No actions carried forward. (No prior minutes have been processed for this board.)"
    lines = []
    for r in records:
        lines.append(
            f"[{r.id}] status={r.status} | cycles_open={r.ageing_cycles} | "
            f"owner={r.owner} | raised={r.raised_at} | committed={r.committed_date}\n"
            f"    action: {r.action}\n"
            f"    basis:  {r.status_basis or 'not yet reconciled'}\n"
            f"    source: {', '.join(r.evidence) if r.evidence else 'no chunk evidence'}"
        )
    return "\n".join(lines)
