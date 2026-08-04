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

SCHEMA_VERSION = 4

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
                                                  -- v4 lifecycle: proposed | approved | rejected | executed
    outcome    TEXT,                              -- worked | failed | unknown (filled in later)
    made_by    TEXT,                              -- agent | human (v2)
    case_id    INTEGER REFERENCES cases(id),
    -- v4 (WP-U4): the approval workflow. All nullable — legacy decisions render but are NOT
    -- approvable via U4 controls (no envelope = nothing to bind an approval to).
    kind               TEXT,                      -- e.g. seo_meta_update
    envelope           TEXT,                      -- canonical JSON (envelope.canonical_json)
    envelope_sha256    TEXT,                      -- sha256 of the canonical UTF-8 bytes
    revision           INTEGER NOT NULL DEFAULT 0, -- optimistic concurrency (stale-tab guard)
    evidence           TEXT,                      -- pointer(s) to evidence, human-readable
    impact             TEXT,                      -- provenance JSON {value,label,method,source,as_of}
    confidence         TEXT,                      -- provenance JSON, same shape
    approved_at        TEXT,
    approved_by        TEXT,
    executed_at        TEXT,
    execution_evidence TEXT                       -- pointer to the terminal verify attempt (U4b)
);

CREATE TABLE IF NOT EXISTS decision_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     INTEGER NOT NULL REFERENCES decisions(id),
    at              TEXT NOT NULL,
    actor           TEXT NOT NULL,                -- 'owner' today (single-operator Console)
    action          TEXT NOT NULL,                -- propose | approve | reject | unapprove | re-propose
    from_status     TEXT,
    to_status       TEXT NOT NULL,
    revision        INTEGER NOT NULL,             -- decision revision AFTER this mutation
    envelope_sha256 TEXT,                         -- the envelope this act bound to
    detail          TEXT                          -- e.g. the rejection reason
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
    delivered_at      TEXT,
    -- v4: best-effort recommendation count parsed at persist time; NULL (rendered "unknown")
    -- beats an invented zero, and it can never affect report validity or the validator. Not
    -- covered by the immutability trigger (adding it there would need a trigger rebuild across
    -- migrated stores for a nullable metadata field no API path ever updates).
    recommendations_count INTEGER
);

CREATE INDEX IF NOT EXISTS idx_cases_status    ON cases(status);
CREATE INDEX IF NOT EXISTS idx_runs_kind       ON runs(kind);
CREATE INDEX IF NOT EXISTS idx_decisions_case  ON decisions(case_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_kind  ON report_artifacts(kind);
CREATE INDEX IF NOT EXISTS idx_artifacts_sha   ON report_artifacts(content_sha256);
CREATE INDEX IF NOT EXISTS idx_decision_events ON decision_events(decision_id);

-- Audit rows are append-only evidence (WP-U4): every lifecycle act records actor, timestamp,
-- revision, old/new state and the bound envelope hash — and no act, including a later success,
-- may rewrite or remove an earlier one.
CREATE TRIGGER IF NOT EXISTS trg_decision_events_no_update
BEFORE UPDATE ON decision_events
BEGIN SELECT RAISE(ABORT, 'decision events are immutable (append-only audit trail)'); END;

CREATE TRIGGER IF NOT EXISTS trg_decision_events_no_delete
BEFORE DELETE ON decision_events
BEGIN SELECT RAISE(ABORT, 'decision events are immutable (append-only audit trail)'); END;

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

# WP-U4 lifecycle triggers live OUTSIDE _SCHEMA on purpose: they reference v4 columns, and on a
# pre-v4 store _SCHEMA executes BEFORE the ALTER TABLE migration adds those columns — creating
# them there would fail with "no such column". init_db applies them after migration, when the
# columns exist on every path (fresh create and migrated alike).
_DECISION_TRIGGERS = """
-- The spec's one rule for approved envelopes (WP-U4 state machine): an approved envelope is
-- immutable AT THE STORAGE LAYER; the only path to editing is explicit Unapprove (a status
-- change, which this trigger permits) followed by the edit in 'proposed'. No silent auto-void.
CREATE TRIGGER IF NOT EXISTS trg_decisions_approved_envelope_immutable
BEFORE UPDATE ON decisions
WHEN OLD.status = 'approved'
 AND (OLD.envelope        IS NOT NEW.envelope
   OR OLD.envelope_sha256 IS NOT NEW.envelope_sha256
   OR OLD.kind            IS NOT NEW.kind)
BEGIN
    SELECT RAISE(ABORT, 'approved envelope is immutable — unapprove first, then edit');
END;

-- Executed is terminal (WP-U4 state machine): corrections are NEW decisions, never edits of an
-- outcome that evidence already points at.
CREATE TRIGGER IF NOT EXISTS trg_decisions_executed_terminal
BEFORE UPDATE ON decisions
WHEN OLD.status = 'executed'
BEGIN
    SELECT RAISE(ABORT, 'executed decision is terminal — record a new decision instead');
END;

-- The legal transition graph for WORKFLOW rows (envelope-bearing), enforced independently of
-- the Store API (review #71 finding 3): even raw SQL cannot move a workflow decision along an
-- edge the spec's state machine does not list. Legacy rows (no envelope) are untouched — their
-- lifecycle predates this machine. NOTE the honest boundary: triggers enforce WHICH transitions
-- are possible; that every transition also appends its audit event is the Store API's
-- transactional guarantee, not the database's.
CREATE TRIGGER IF NOT EXISTS trg_decisions_workflow_transitions
BEFORE UPDATE ON decisions
WHEN OLD.envelope_sha256 IS NOT NULL
 AND NEW.status IS NOT OLD.status
 AND NOT (
      (OLD.status = 'proposed' AND NEW.status IN ('approved', 'rejected'))
   OR (OLD.status = 'approved' AND NEW.status IN ('proposed', 'executed'))
   OR (OLD.status = 'rejected' AND NEW.status = 'proposed'))
BEGIN
    SELECT RAISE(ABORT, 'illegal decision transition — not in the U4 state machine');
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
    # After migration on purpose — these triggers reference v4 columns (see _DECISION_TRIGGERS).
    conn.executescript(_DECISION_TRIGGERS)
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
    if from_version < 4:
        # v3 -> v4 (WP-U4): approval-workflow columns on decisions + recommendations_count on
        # report_artifacts. decision_events and all v4 triggers come from _SCHEMA /
        # _DECISION_TRIGGERS. Existing rows keep NULL (legacy = visible, not approvable) and
        # revision 0.
        for stmt in (
            "ALTER TABLE decisions ADD COLUMN kind TEXT;",
            "ALTER TABLE decisions ADD COLUMN envelope TEXT;",
            "ALTER TABLE decisions ADD COLUMN envelope_sha256 TEXT;",
            "ALTER TABLE decisions ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;",
            "ALTER TABLE decisions ADD COLUMN evidence TEXT;",
            "ALTER TABLE decisions ADD COLUMN impact TEXT;",
            "ALTER TABLE decisions ADD COLUMN confidence TEXT;",
            "ALTER TABLE decisions ADD COLUMN approved_at TEXT;",
            "ALTER TABLE decisions ADD COLUMN approved_by TEXT;",
            "ALTER TABLE decisions ADD COLUMN executed_at TEXT;",
            "ALTER TABLE decisions ADD COLUMN execution_evidence TEXT;",
            "ALTER TABLE report_artifacts ADD COLUMN recommendations_count INTEGER;",
        ):
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
