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


@dataclass
class Snapshot:
    """One observed site-structure snapshot (WP-06). Payload/drift are JSON text.

    Three-state discipline: `payload` is OBSERVED current state; SITE_PROFILE.md is APPROVED
    knowledge (human-maintained, never written by this table); `drift` is the diff vs the
    previous snapshot — UNEXPLAINED until a report or human accounts for it.
    """

    id: int
    taken_at: str
    source: str
    item_count: int
    payload: str
    drift: str | None


def save_snapshot(
    conn: sqlite3.Connection,
    *,
    payload: str,
    item_count: int,
    drift: str | None = None,
    source: str = "wp_site_structure",
    keep: int = 30,
) -> int:
    """INSERT-only (history is immutable — there is deliberately no update path for this
    table). Retention: after each save, rows beyond the newest `keep` are pruned so the
    snapshot store stays bounded (weekly cadence -> ~7 months of history at the default)."""
    cur = conn.execute(
        "INSERT INTO site_snapshots (taken_at, source, item_count, payload, drift) "
        "VALUES (?, ?, ?, ?, ?);",
        (_now(), source, item_count, payload, drift),
    )
    conn.execute(
        "DELETE FROM site_snapshots WHERE id NOT IN "
        "(SELECT id FROM site_snapshots ORDER BY id DESC LIMIT ?);",
        (max(1, keep),),
    )
    conn.commit()
    return int(cur.lastrowid)


def latest_snapshot(conn: sqlite3.Connection) -> Snapshot | None:
    row = conn.execute(
        "SELECT * FROM site_snapshots ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    return Snapshot(**row) if row else None


def list_snapshots(conn: sqlite3.Connection, *, limit: int = 20) -> list[Snapshot]:
    rows = conn.execute(
        "SELECT id, taken_at, source, item_count, length(payload) AS payload, drift "
        "FROM site_snapshots ORDER BY id DESC LIMIT ?;", (limit,)
    ).fetchall()
    # payload column carries its LENGTH in listings (summaries must stay light).
    return [Snapshot(**{**dict(r), "payload": str(r["payload"])}) for r in rows]
