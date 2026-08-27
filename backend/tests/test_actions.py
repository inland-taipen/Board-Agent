"""Action-item tracker tests.

The BRD's stated objective is that 100% of unresolved actions appear in every
briefing. That depends on three behaviours tested here: reworded items must
deduplicate, ageing must advance only across cycles, and a client's register
must be unreachable from another client.
"""

from __future__ import annotations

from boardlens.actions import tracker
from boardlens.db import execute, init_db, new_id, now


def _client(name: str) -> str:
    client_id = new_id("cli")
    execute("INSERT INTO clients (id, name, created_at) VALUES (?,?,?)", (client_id, name, now()))
    return client_id


def _pack(client_id: str, label: str) -> str:
    pack_id = new_id("pack")
    execute(
        """
        INSERT INTO packs (id, client_id, meeting_label, meeting_date, created_by, created_at)
        VALUES (?,?,?,?,?,?)
        """,
        (pack_id, client_id, label, "2026-08-21", "test", now()),
    )
    return pack_id


def test_reworded_actions_deduplicate():
    init_db()
    client_id = _client("Meridian")
    pack_a = _pack(client_id, "118th")

    created, matched = tracker.ingest_extracted(
        client_id,
        pack_a,
        [
            {
                "action": "Management to place the IT security roadmap before the Board",
                "owner": "MD",
                "raised_at": "118th meeting",
                "committed_date": "not recorded",
                "evidence": ["c0011"],
            }
        ],
    )
    assert (created, matched) == (1, 0)

    pack_b = _pack(client_id, "119th")
    created, matched = tracker.ingest_extracted(
        client_id,
        pack_b,
        [
            {
                # Same standing item, different voice - must not create a duplicate.
                "action": "The IT security roadmap to be placed before the Board by management",
                "owner": "not recorded",
                "raised_at": "119th meeting",
                "committed_date": "not recorded",
                "evidence": ["c0031"],
            }
        ],
    )
    assert (created, matched) == (0, 1)
    assert len(tracker.register(client_id)) == 1


def test_ageing_advances_across_packs_but_not_on_rerun():
    init_db()
    client_id = _client("Meridian")
    pack_a = _pack(client_id, "118th")
    item = [{"action": "Provide receivables ageing analysis above 180 days", "owner": "CFO",
             "raised_at": "118th", "committed_date": "not recorded", "evidence": []}]

    tracker.ingest_extracted(client_id, pack_a, item)
    assert tracker.register(client_id)[0].ageing_cycles == 0

    # Re-running the same pack must not age the register.
    tracker.ingest_extracted(client_id, pack_a, item)
    assert tracker.register(client_id)[0].ageing_cycles == 0

    pack_b = _pack(client_id, "119th")
    tracker.ingest_extracted(client_id, pack_b, item)
    assert tracker.register(client_id)[0].ageing_cycles == 1


def test_carry_forward_excludes_closed_items_only():
    init_db()
    client_id = _client("Meridian")
    pack_id = _pack(client_id, "118th")

    tracker.ingest_extracted(
        client_id,
        pack_id,
        [
            {"action": "Obtain independent valuation opinion for Kalyani",
             "owner": "MD", "raised_at": "118th", "committed_date": "n/a", "evidence": []},
            {"action": "Circulate cyber insurance adequacy report to directors",
             "owner": "CIO", "raised_at": "118th", "committed_date": "30 days", "evidence": []},
        ],
    )
    carried = tracker.carry_forward(client_id)
    assert len(carried) == 2

    tracker.apply_reconciliation(
        client_id,
        [{"action_id": carried[0].id, "status": "completed",
          "status_basis": "Deck slide 5 records the opinion was commissioned.",
          "evidence": ["c0006"]}],
        pack_id=pack_id,
    )

    remaining = tracker.carry_forward(client_id)
    assert len(remaining) == 1
    # 'unclear' stays carried forward: silence is the finding, not closure.
    assert remaining[0].status in tracker.OPEN_STATUSES


def test_unclear_status_remains_carried_forward():
    init_db()
    client_id = _client("Meridian")
    pack_id = _pack(client_id, "118th")
    tracker.ingest_extracted(
        client_id, pack_id,
        [{"action": "Standardise the ESG disclosure framework across subsidiaries",
          "owner": "CSO", "raised_at": "116th", "committed_date": "30 June 2026", "evidence": []}],
    )
    action_id = tracker.register(client_id)[0].id

    tracker.apply_reconciliation(
        client_id,
        [{"action_id": action_id, "status": "unclear",
          "status_basis": "The current pack does not address this item.", "evidence": []}],
        pack_id=pack_id,
    )
    assert [a.status for a in tracker.carry_forward(client_id)] == ["unclear"]


def test_reconciliation_cannot_cross_client_boundary():
    init_db()
    client_a = _client("Meridian")
    client_b = _client("Northwind")
    pack_a = _pack(client_a, "118th")

    tracker.ingest_extracted(
        client_a, pack_a,
        [{"action": "Report debt service coverage ratio at each meeting",
          "owner": "CFO", "raised_at": "117th", "committed_date": "ongoing", "evidence": []}],
    )
    action_id = tracker.register(client_a)[0].id

    # Client B attempts to reconcile client A's action - it must be ignored.
    updated = tracker.apply_reconciliation(
        client_b,
        [{"action_id": action_id, "status": "completed", "status_basis": "x", "evidence": []}],
    )
    assert updated == 0
    assert tracker.register(client_a)[0].status == "open"


def test_register_renders_for_the_prompt():
    init_db()
    client_id = _client("Meridian")
    pack_id = _pack(client_id, "118th")
    tracker.ingest_extracted(
        client_id, pack_id,
        [{"action": "Complete procurement segregation-of-duties remediation",
          "owner": "CFO", "raised_at": "118th", "committed_date": "30 Sep 2026",
          "evidence": ["c0011"]}],
    )
    rendered = tracker.render_register(tracker.carry_forward(client_id))

    assert "status=open" in rendered
    assert "segregation-of-duties" in rendered
    assert "c0011" in rendered


def test_empty_register_is_explicit_rather_than_blank():
    init_db()
    client_id = _client("Meridian")
    rendered = tracker.render_register(tracker.carry_forward(client_id))
    assert "No actions carried forward" in rendered
