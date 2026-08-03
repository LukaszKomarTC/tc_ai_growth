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

from ..config import BASE_DIR, active_site, get_settings

SCHEMA_VERSION = 3

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
    confidence  TEXT,                             -- calibrated: a 0-1 number or a label
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    opened_by   TEXT,                             -- agent | human (v2)
    closed_by   TEXT,                             -- agent | human (v2)
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
    status     TEXT NOT NULL DEFAULT 'active',    -- proposed | active | superseded | reverted
    outcome    TEXT,                              -- worked | failed | unknown (filled in later)
    made_by    TEXT,                              -- agent | human (v2)
    case_id    INTEGER REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS report_artifacts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER REFERENCES runs(id),  -- ledger linkage (nullable: run log may fail)
    kind              TEXT NOT NULL,                -- weekly-report | weekly-report-validation
    profile           TEXT,                         -- site label at generation time
    window            TEXT,                         -- reporting window as stated in the body (best-effort)
    generated_at      TEXT NOT NULL,
    format_version    TEXT NOT NULL,                -- artifact format, e.g. 'md/1'
    validator_version TEXT NOT NULL,                -- which validator heuristics judged it
    validator_ok      INTEGER NOT NULL,             -- 1 accepted / 0 rejected (stored either way)
    validator_reason  TEXT,                         -- rejection reason when validator_ok = 0
    model             TEXT,
    cost_usd          REAL,
    content_sha256    TEXT NOT NULL,                -- sha256 of body EXACTLY as delivered
    body              TEXT NOT NULL,                -- the immutable original artifact
    delivery_status   TEXT NOT NULL DEFAULT 'pending',  -- pending | delivered | send_failed
    delivery_attempts INTEGER NOT NULL DEFAULT 0,         -- one artifact, many attempts (review)
    delivered_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_cases_status    ON cases(status);
CREATE INDEX IF NOT EXISTS idx_runs_kind       ON runs(kind);
CREATE INDEX IF NOT EXISTS idx_decisions_case  ON decisions(case_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_kind  ON report_artifacts(kind);
CREATE INDEX IF NOT EXISTS idx_artifacts_sha   ON report_artifacts(content_sha256);

-- The trust chain's storage guarantee (WP-CONSOLE-USABILITY U3a): the artifact core is
-- IMMUTABLE at the database layer, not merely by API convention. Only the delivery fields
-- (status/attempts/timestamp — mutable metadata AROUND the immutable core) may ever change.
CREATE TRIGGER IF NOT EXISTS trg_report_artifacts_immutable
BEFORE UPDATE ON report_artifacts
WHEN OLD.body            IS NOT NEW.body
  OR OLD.content_sha256  IS NOT NEW.content_sha256
  OR OLD.kind            IS NOT NEW.kind
  OR OLD.profile         IS NOT NEW.profile
  OR OLD.window          IS NOT NEW.window
  OR OLD.generated_at    IS NOT NEW.generated_at
  OR OLD.format_version  IS NOT NEW.format_version
  OR OLD.validator_version IS NOT NEW.validator_version
  OR OLD.validator_ok    IS NOT NEW.validator_ok
  OR OLD.validator_reason IS NOT NEW.validator_reason
  OR OLD.model           IS NOT NEW.model
  OR OLD.cost_usd        IS NOT NEW.cost_usd
  OR OLD.run_id          IS NOT NEW.run_id
BEGIN
    SELECT RAISE(ABORT, 'report artifact is immutable (only delivery status/attempts/timestamp may change)');
END;
"""


def resolved_db_path() -> Path:
    """Where the SQLite file lives. TC_DB_PATH overrides; otherwise each site profile gets its
    OWN store (memory is per-business — sites must never share cases/decisions):
    data/tc_growth.db classic, data/tc_growth-<site>.db when TC_SITE is set."""
    configured = get_settings().db_path
    if configured:
        return Path(configured).expanduser()
    site = active_site()
    name = f"tc_growth-{site}.db" if site else "tc_growth.db"
    return BASE_DIR / "data" / name


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
    """Create tables if absent, migrate older schemas forward, stamp the version (idempotent)."""
    conn.executescript(_SCHEMA)
    row = conn.execute("SELECT version FROM schema_version LIMIT 1;").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?);", (SCHEMA_VERSION,))
    elif row[0] < SCHEMA_VERSION:
        _migrate(conn, from_version=row[0])
        conn.execute("UPDATE schema_version SET version = ?;", (SCHEMA_VERSION,))
    conn.commit()


def _migrate(conn: sqlite3.Connection, *, from_version: int) -> None:
    """Forward-only, additive migrations. Existing rows keep NULL in the new columns."""
    if from_version < 2:
        # v1 -> v2: provenance columns (who opened/closed a case, who made a decision).
        for stmt in (
            "ALTER TABLE cases ADD COLUMN opened_by TEXT;",
            "ALTER TABLE cases ADD COLUMN closed_by TEXT;",
            "ALTER TABLE decisions ADD COLUMN made_by TEXT;",
        ):
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError as exc:  # column already there (fresh-create race)
                if "duplicate column" not in str(exc).lower():
                    raise
    if from_version < 3:
        # v2 -> v3: report_artifacts table + immutability trigger — purely additive, created by
        # the CREATE IF NOT EXISTS statements in _SCHEMA (which init_db runs before migrating).
        pass
