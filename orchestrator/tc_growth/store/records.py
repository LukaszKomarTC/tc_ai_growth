"""Typed data access for the store — dataclasses + CRUD, no SQL leaks past this module.

Deliberately thin. The one non-trivial helper is `find_open_cases`, which supports the discipline
that matters most for a memory system: *search for an existing case before opening a new one*, so
the agent updates a known issue instead of rediscovering it every week.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass


def _now() -> str:
    """ISO-8601 UTC timestamp, second precision — SQLite stores datetimes as text."""
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


@dataclass
class Case:
    id: int
    ref: str | None
    title: str
    category: str | None
    status: str
    priority: str
    confidence: str | None
    created_at: str
    updated_at: str
    opened_by: str | None
    closed_by: str | None
    body: str | None


@dataclass
class Run:
    id: int
    started_at: str
    finished_at: str | None
    kind: str
    status: str
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    duration_s: float | None
    summary: str | None
    detail: str | None
    case_id: int | None


@dataclass
class Decision:
    id: int
    made_at: str
    title: str
    rationale: str | None
    status: str
    outcome: str | None
    made_by: str | None
    case_id: int | None


# --- cases -----------------------------------------------------------------

_OPEN_STATES = ("open", "monitoring")


def create_case(
    conn: sqlite3.Connection,
    *,
    title: str,
    ref: str | None = None,
    category: str | None = None,
    status: str = "open",
    priority: str = "medium",
    confidence: str | None = None,
    opened_by: str | None = None,
    body: str | None = None,
) -> int:
    """Insert a case; returns its id. Raises sqlite3.IntegrityError on a duplicate `ref`."""
    now = _now()
    cur = conn.execute(
        "INSERT INTO cases (ref, title, category, status, priority, confidence, created_at, "
        "updated_at, opened_by, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
        (ref, title, category, status, priority, confidence, now, now, opened_by, body),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_case(conn: sqlite3.Connection, case_id: int) -> Case | None:
    row = conn.execute("SELECT * FROM cases WHERE id = ?;", (case_id,)).fetchone()
    return Case(**row) if row else None


def get_case_by_ref(conn: sqlite3.Connection, ref: str) -> Case | None:
    row = conn.execute("SELECT * FROM cases WHERE ref = ?;", (ref,)).fetchone()
    return Case(**row) if row else None


def list_cases(conn: sqlite3.Connection, *, status: str | None = None, limit: int = 50) -> list[Case]:
    if status:
        rows = conn.execute(
            "SELECT * FROM cases WHERE status = ? ORDER BY updated_at DESC LIMIT ?;",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM cases ORDER BY updated_at DESC LIMIT ?;", (limit,)
        ).fetchall()
    return [Case(**r) for r in rows]


def find_cases(
    conn: sqlite3.Connection,
    query: str,
    *,
    statuses: tuple[str, ...] | None = None,
    limit: int = 10,
) -> list[Case]:
    """Keyword search over cases (title + body), optionally filtered by status.

    statuses=None searches ALL cases — resolved ones included, deliberately: an observation that
    matches a RESOLVED case is the "possible recurrence, consider reopening" signal, and hiding
    closed history from duplicate checks is how the agent re-discovers old incidents as new.
    Splits the query into words and matches ANY word, most-recently updated first. Intentionally
    simple substring matching; a future semantic layer can replace it without changing callers.
    """
    words = [w for w in query.replace("/", " ").split() if len(w) > 2]
    if not words:
        return []
    placeholders = " OR ".join(["(title LIKE ? OR body LIKE ?)"] * len(words))
    params: list[str] = []
    for w in words:
        like = f"%{w}%"
        params.extend([like, like])
    status_clause = ""
    status_params: tuple[str, ...] = ()
    if statuses:
        status_clause = f"status IN ({','.join('?' * len(statuses))}) AND "
        status_params = statuses
    rows = conn.execute(
        f"SELECT * FROM cases WHERE {status_clause}({placeholders}) "
        f"ORDER BY updated_at DESC LIMIT ?;",
        (*status_params, *params, limit),
    ).fetchall()
    return [Case(**r) for r in rows]


def find_open_cases(conn: sqlite3.Connection, query: str, *, limit: int = 10) -> list[Case]:
    """find_cases restricted to open/monitoring — the 'what is live right now' view."""
    return find_cases(conn, query, statuses=_OPEN_STATES, limit=limit)


_CASE_UPDATABLE = {"title", "category", "status", "priority", "confidence", "body", "closed_by"}


def update_case(conn: sqlite3.Connection, case_id: int, **fields: object) -> None:
    """Update allowed columns and bump updated_at. Unknown fields raise, to catch typos early."""
    bad = set(fields) - _CASE_UPDATABLE
    if bad:
        raise ValueError(f"Not updatable: {sorted(bad)}")
    if not fields:
        return
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE cases SET {assignments}, updated_at = ? WHERE id = ?;",
        (*fields.values(), _now(), case_id),
    )
    conn.commit()


def append_observation(
    conn: sqlite3.Connection, case_id: int, text: str, *, author: str = "agent"
) -> None:
    """Append a timestamped observation to the case narrative and bump updated_at.

    Cases evolve as an append-only journal — prior narrative is never rewritten, so the
    reasoning trail (including wrong turns) is preserved.
    """
    row = conn.execute("SELECT body FROM cases WHERE id = ?;", (case_id,)).fetchone()
    if row is None:
        raise ValueError(f"No case with id {case_id}")
    entry = f"\n\n---\n**{_now()} ({author}):** {text.strip()}"
    conn.execute(
        "UPDATE cases SET body = COALESCE(body, '') || ?, updated_at = ? WHERE id = ?;",
        (entry, _now(), case_id),
    )
    conn.commit()


# --- runs ------------------------------------------------------------------


def record_run(
    conn: sqlite3.Connection,
    *,
    kind: str,
    status: str = "ok",
    model: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost_usd: float | None = None,
    duration_s: float | None = None,
    summary: str | None = None,
    detail: str | None = None,
    case_id: int | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> int:
    """Log one agent execution. Token/cost fields are nullable — you can't backfill them, so
    capture what you have now and enrich later."""
    now = _now()
    cur = conn.execute(
        "INSERT INTO runs (started_at, finished_at, kind, status, model, prompt_tokens, "
        "completion_tokens, cost_usd, duration_s, summary, detail, case_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
        (started_at or now, finished_at or now, kind, status, model, prompt_tokens,
         completion_tokens, cost_usd, duration_s, summary, detail, case_id),
    )
    conn.commit()
    return int(cur.lastrowid)


def log_run(
    conn: sqlite3.Connection,
    *,
    kind: str,
    model: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    duration_s: float | None = None,
    status: str = "ok",
    summary: str | None = None,
    detail: str | None = None,
    case_id: int | None = None,
    started_at: str | None = None,
) -> int:
    """record_run + cost estimation in one call. The convenience entry point for the app layer."""
    from ..core.cost import estimate_cost

    return record_run(
        conn, kind=kind, status=status, model=model,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        cost_usd=estimate_cost(model, prompt_tokens, completion_tokens),
        duration_s=duration_s, summary=summary, detail=detail, case_id=case_id,
        started_at=started_at,
    )


def list_runs(conn: sqlite3.Connection, *, kind: str | None = None, limit: int = 20) -> list[Run]:
    if kind:
        rows = conn.execute(
            "SELECT * FROM runs WHERE kind = ? ORDER BY id DESC LIMIT ?;", (kind, limit)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?;", (limit,)).fetchall()
    return [Run(**r) for r in rows]


# --- decisions -------------------------------------------------------------


def record_decision(
    conn: sqlite3.Connection,
    *,
    title: str,
    rationale: str | None = None,
    status: str = "active",
    outcome: str | None = None,
    made_by: str | None = None,
    case_id: int | None = None,
    made_at: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO decisions (made_at, title, rationale, status, outcome, made_by, case_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?);",
        (made_at or _now(), title, rationale, status, outcome, made_by, case_id),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_decision(conn: sqlite3.Connection, decision_id: int) -> Decision | None:
    row = conn.execute("SELECT * FROM decisions WHERE id = ?;", (decision_id,)).fetchone()
    return Decision(**row) if row else None


_DECISION_UPDATABLE = {"status", "outcome", "rationale"}


def update_decision(conn: sqlite3.Connection, decision_id: int, **fields: object) -> None:
    """Update a decision's status/outcome/rationale (the approve/reject path)."""
    bad = set(fields) - _DECISION_UPDATABLE
    if bad:
        raise ValueError(f"Not updatable: {sorted(bad)}")
    if not fields:
        return
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE decisions SET {assignments} WHERE id = ?;", (*fields.values(), decision_id)
    )
    conn.commit()


def list_decisions(
    conn: sqlite3.Connection, *, case_id: int | None = None, limit: int = 50
) -> list[Decision]:
    if case_id is not None:
        rows = conn.execute(
            "SELECT * FROM decisions WHERE case_id = ? ORDER BY id DESC LIMIT ?;", (case_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM decisions ORDER BY id DESC LIMIT ?;", (limit,)
        ).fetchall()
    return [Decision(**r) for r in rows]


# -- report artifacts (WP-CONSOLE-USABILITY U3a) --------------------------------------------------
#
# The trust chain: generation → validated immutable artifact → hash → persisted artifact →
# email delivery → dashboard display. The body stored here is byte-identical to the body that was
# validated and delivered; content_sha256 is computed HERE, over exactly what is stored, so a
# stored artifact can always be re-verified against the delivered email. The immutability trigger
# in db.py enforces that only the delivery fields ever change.

MAX_ARTIFACT_BYTES = 2_000_000  # sanity ceiling: a weekly report is ~15 KB; 2 MB means a bug


@dataclass
class ReportArtifact:
    id: int
    run_id: int | None
    kind: str
    profile: str | None
    window: str | None
    generated_at: str
    format_version: str
    validator_version: str
    validator_ok: int
    validator_reason: str | None
    model: str | None
    cost_usd: float | None
    content_sha256: str
    body: str
    delivery_status: str
    delivered_at: str | None


def persist_report_artifact(
    conn: sqlite3.Connection,
    *,
    kind: str,
    body: str,
    validator_ok: bool,
    validator_reason: str | None,
    validator_version: str,
    run_id: int | None = None,
    profile: str | None = None,
    window: str | None = None,
    model: str | None = None,
    cost_usd: float | None = None,
    format_version: str = "md/1",
    generated_at: str | None = None,
) -> int:
    """Store the artifact and return its id. Rejected artifacts are stored too (validator_ok=0) —
    a failed report is evidence, and the corpus of real bodies is how the validator improves."""
    import hashlib

    raw = body.encode("utf-8")
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ValueError(f"report artifact too large ({len(raw)} bytes > {MAX_ARTIFACT_BYTES})")
    cur = conn.execute(
        "INSERT INTO report_artifacts (run_id, kind, profile, window, generated_at, "
        "format_version, validator_version, validator_ok, validator_reason, model, cost_usd, "
        "content_sha256, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
        (run_id, kind, profile, window, generated_at or _now(), format_version,
         validator_version, 1 if validator_ok else 0, validator_reason, model, cost_usd,
         hashlib.sha256(raw).hexdigest(), body),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_report_artifact(conn: sqlite3.Connection, artifact_id: int) -> ReportArtifact | None:
    row = conn.execute("SELECT * FROM report_artifacts WHERE id = ?;", (artifact_id,)).fetchone()
    return ReportArtifact(**row) if row else None


def latest_report_artifact(conn: sqlite3.Connection, *, kind: str | None = None) -> ReportArtifact | None:
    if kind:
        row = conn.execute("SELECT * FROM report_artifacts WHERE kind = ? "
                           "ORDER BY id DESC LIMIT 1;", (kind,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM report_artifacts ORDER BY id DESC LIMIT 1;").fetchone()
    return ReportArtifact(**row) if row else None


def list_report_artifacts(conn: sqlite3.Connection, *, kind: str | None = None,
                          limit: int = 20) -> list[ReportArtifact]:
    if kind:
        rows = conn.execute("SELECT * FROM report_artifacts WHERE kind = ? "
                            "ORDER BY id DESC LIMIT ?;", (kind, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM report_artifacts ORDER BY id DESC LIMIT ?;",
                            (limit,)).fetchall()
    return [ReportArtifact(**r) for r in rows]


def set_artifact_delivery(conn: sqlite3.Connection, artifact_id: int, status: str) -> None:
    """The ONLY sanctioned mutation — delivery metadata around the immutable core."""
    conn.execute("UPDATE report_artifacts SET delivery_status = ?, delivered_at = ? WHERE id = ?;",
                 (status, _now(), artifact_id))
    conn.commit()


def set_artifact_delivery_by_hash(conn: sqlite3.Connection, content_sha256: str, status: str) -> bool:
    """Mark the LATEST artifact with this exact content hash. Hash-keyed on purpose: delivery is
    recorded against the precise bytes that were sent, never against 'whatever row is newest' —
    the chain stays self-verifying end to end. Returns False when no artifact matches."""
    cur = conn.execute(
        "UPDATE report_artifacts SET delivery_status = ?, delivered_at = ? WHERE id = "
        "(SELECT id FROM report_artifacts WHERE content_sha256 = ? ORDER BY id DESC LIMIT 1);",
        (status, _now(), content_sha256))
    conn.commit()
    return cur.rowcount > 0
