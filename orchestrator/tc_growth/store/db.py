"""SQLite persistence — connection + schema (provider-neutral, stdlib only).

This is the foundation of the agent's memory. It is deliberately small: three related tables
(`runs`, `cases`, `decisions`) plus a `schema_version`. Structure lives in columns (status,
priority, timestamps, relationships, token cost); the reasoning narrative lives in a `body` text
column. That hybrid is the point — the database is queryable, the prose stays prose.

No AI-provider dependency and no business logic beyond storage, so `store/` sits beside `core/`
under the same portability invariant.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..config import ENV_PATH, get_settings

SCHEMA_VERSION = 1

# One statement per table; CREATE ... IF NOT EXISTS makes init idempotent.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS cases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ref         TEXT UNIQUE,                      -- human id, e.g. INC-2026-02-01
    title       TEXT NOT NULL,
    category    TEXT,                             -- incident | seo | tracking | ...
    status      TEXT NOT NULL DEFAULT 'open',     -- open | monitoring | resolved | closed
    priority    TEXT NOT NULL DEFAULT 'medium',   -- low | medium | high | critical
    confidence  TEXT,                             -- calibrated confidence, if any
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    body        TEXT                              -- narrative markdown
);

CREATE TABLE IF NOT EXISTS runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    kind              TEXT NOT NULL,              -- weekly-report | investigate | test-email | ...
    status            TEXT NOT NULL DEFAULT 'ok', -- ok | error
    model             TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    cost_usd          REAL,
    duration_s        REAL,
    summary           TEXT,                       -- short human summary
    detail            TEXT,                       -- full output / error, optional
    case_id           INTEGER REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    made_at    TEXT NOT NULL,
    title      TEXT NOT NULL,
    rationale  TEXT,
    status     TEXT NOT NULL DEFAULT 'active',    -- active | superseded | reverted
    outcome    TEXT,                              -- worked | failed | unknown (filled in later)
    case_id    INTEGER REFERENCES cases(id)
);

CREATE INDEX IF NOT EXISTS idx_cases_status    ON cases(status);
CREATE INDEX IF NOT EXISTS idx_runs_kind       ON runs(kind);
CREATE INDEX IF NOT EXISTS idx_decisions_case  ON decisions(case_id);
"""


def resolved_db_path() -> Path:
    """Where the SQLite file lives. TC_DB_PATH overrides; default orchestrator/data/tc_growth.db."""
    configured = get_settings().db_path
    if configured:
        return Path(configured).expanduser()
    return ENV_PATH.parent / "data" / "tc_growth.db"


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (and initialise) the database. Pass ':memory:' in tests.

    Foreign keys are enforced and rows come back as sqlite3.Row (dict-like). The schema is created
    on first connect, so callers never deal with migrations by hand.
    """
    if path is None:
        path = resolved_db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if absent and stamp the schema version (idempotent)."""
    conn.executescript(_SCHEMA)
    row = conn.execute("SELECT version FROM schema_version LIMIT 1;").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?);", (SCHEMA_VERSION,))
    conn.commit()
