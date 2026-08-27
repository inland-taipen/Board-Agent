"""SQLite persistence.

Client segregation is enforced structurally: every row that can hold client
content carries `client_id`, every query in the API layer is scoped by the
caller's memberships, and blobs are stored under a per-client directory. There
is no global "all packs" query anywhere in the codebase.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from .config import get_settings

_local = threading.local()

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS clients (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin','secretary','director')),
    display_name  TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);

-- Membership is the segregation boundary. An admin still needs a row here to
-- read a client's content; the role grants capability, not access.
CREATE TABLE IF NOT EXISTS user_clients (
    user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, client_id)
);

CREATE TABLE IF NOT EXISTS packs (
    id             TEXT PRIMARY KEY,
    client_id      TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    meeting_label  TEXT NOT NULL,
    meeting_date   TEXT NOT NULL,
    classification TEXT NOT NULL DEFAULT 'confidential',
    status         TEXT NOT NULL DEFAULT 'draft',
    progress       TEXT NOT NULL DEFAULT '',
    error          TEXT NOT NULL DEFAULT '',
    created_by     TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_packs_client ON packs(client_id, created_at DESC);

CREATE TABLE IF NOT EXISTS documents (
    id             TEXT PRIMARY KEY,
    pack_id        TEXT NOT NULL REFERENCES packs(id) ON DELETE CASCADE,
    client_id      TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    filename       TEXT NOT NULL,
    doc_kind       TEXT NOT NULL,
    classification TEXT NOT NULL DEFAULT 'confidential',
    blob_path      TEXT NOT NULL,
    sha256         TEXT NOT NULL,
    size_bytes     INTEGER NOT NULL DEFAULT 0,
    pages          INTEGER NOT NULL DEFAULT 0,
    chunk_count    INTEGER NOT NULL DEFAULT 0,
    ocr_pages      TEXT NOT NULL DEFAULT '[]',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_pack ON documents(pack_id);

-- The action-item store persists ACROSS meeting cycles; this is what stops
-- items being lost between meetings.
CREATE TABLE IF NOT EXISTS action_items (
    id                TEXT PRIMARY KEY,
    client_id         TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    action            TEXT NOT NULL,
    owner             TEXT NOT NULL DEFAULT 'not recorded',
    raised_at         TEXT NOT NULL DEFAULT 'not recorded',
    committed_date    TEXT NOT NULL DEFAULT 'not recorded',
    status            TEXT NOT NULL DEFAULT 'open',
    status_basis      TEXT NOT NULL DEFAULT '',
    ageing_cycles     INTEGER NOT NULL DEFAULT 0,
    fingerprint       TEXT NOT NULL,
    evidence          TEXT NOT NULL DEFAULT '[]',
    first_seen_pack   TEXT NOT NULL,
    last_seen_pack    TEXT NOT NULL,
    closed_at         TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_actions_client ON action_items(client_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_actions_fingerprint
    ON action_items(client_id, fingerprint);

CREATE TABLE IF NOT EXISTS briefings (
    id            TEXT PRIMARY KEY,
    pack_id       TEXT NOT NULL REFERENCES packs(id) ON DELETE CASCADE,
    client_id     TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    content       TEXT NOT NULL,
    verification  TEXT NOT NULL DEFAULT '{}',
    model         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_briefings_pack ON briefings(pack_id, created_at DESC);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    user_id    TEXT NOT NULL DEFAULT '',
    client_id  TEXT NOT NULL DEFAULT '',
    action     TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def connect() -> sqlite3.Connection:
    """One connection per thread. FastAPI runs sync endpoints on a threadpool."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        settings = get_settings()
        conn = sqlite3.connect(settings.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        _local.conn = conn
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()


def query(sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
    return connect().execute(sql, params).fetchall()


def query_one(sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
    return connect().execute(sql, params).fetchone()


def execute(sql: str, params: tuple | dict = ()) -> None:
    with transaction() as conn:
        conn.execute(sql, params)


def audit(action: str, *, user_id: str = "", client_id: str = "", detail: Any = "") -> None:
    """Append-only audit trail.

    Written for every mutation and every briefing read - listed-company boards
    are asked who saw what and when, and 'we did not log it' is not an answer.
    """
    payload = detail if isinstance(detail, str) else json.dumps(detail, default=str)
    execute(
        "INSERT INTO audit_log (ts, user_id, client_id, action, detail) VALUES (?,?,?,?,?)",
        (now(), user_id, client_id, action, payload),
    )
