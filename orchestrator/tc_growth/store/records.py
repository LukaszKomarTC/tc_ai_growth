"""Typed data access for the store — dataclasses + CRUD, no SQL leaks past this module.

Deliberately thin. The one non-trivial helper is `find_open_cases`, which supports the discipline
that matters most for a memory system: *search for an existing case before opening a new one*, so
the agent updates a known issue instead of rediscovering it every week.
"""

from __future__ import annotations

import datetime as dt
import json
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
    # v4 (WP-U4) — defaults keep every pre-v4 construction site working; legacy rows carry None.
    kind: str | None = None
    envelope: str | None = None
    envelope_sha256: str | None = None
    revision: int = 0
    evidence: str | None = None
    impact: str | None = None
    confidence: str | None = None
    approved_at: str | None = None
    approved_by: str | None = None
    executed_at: str | None = None
    execution_evidence: str | None = None


@dataclass
class VerifyAttempt:
    id: int
    decision_id: int
    revision: int
    envelope_sha256: str
    read_number: int
    pair_id: int | None
    started_at: str
    finished_at: str
    outcome: str
    detail: str


@dataclass
class DecisionEvent:
    id: int
    decision_id: int
    at: str
    actor: str
    action: str
    from_status: str | None
    to_status: str
    revision: int
    envelope_sha256: str | None
    detail: str | None


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
    """Update a decision's status/outcome/rationale — the LEGACY approve/reject path.

    Envelope-bearing (v4) decisions must change status through the lifecycle API below, which
    enforces the state machine, revision concurrency and the audit trail; letting this generic
    setter flip their status would be a silent bypass of all three."""
    bad = set(fields) - _DECISION_UPDATABLE
    if bad:
        raise ValueError(f"Not updatable: {sorted(bad)}")
    if not fields:
        return
    if "status" in fields:
        row = conn.execute(
            "SELECT envelope_sha256 FROM decisions WHERE id = ?;", (decision_id,)).fetchone()
        if row is not None and row["envelope_sha256"]:
            raise ValueError(
                f"decision {decision_id} is a workflow decision (bound envelope) — its status "
                "changes only via approve/reject/unapprove, in the Console at "
                f"/decision/{decision_id}")
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


# -- decision approval workflow (WP-U4a) ----------------------------------------------------------
#
# The state machine is EXHAUSTIVE (spec table); anything not listed below is refused loudly.
# Every mutation carries the caller's expected `revision` and lands atomically via
# `UPDATE ... WHERE id AND revision AND status` — a stale tab can never silently overwrite a
# fresher state. The guarantee split is deliberate and precisely this (review #71): DATABASE
# TRIGGERS (db.py) enforce approved-envelope immutability, executed terminality, append-only
# audit rows, and the legal transition graph for workflow rows — even raw SQL cannot cross
# them. The STORE API (these functions) enforces revision concurrency, context checks, and
# that every successful transition appends its decision_events row in the same transaction —
# audit-event coupling is an API guarantee, not a trigger guarantee.


class DecisionError(Exception):
    """Base for decision-lifecycle refusals — the message is owner-readable on purpose."""


class StaleRevision(DecisionError):
    """The decision changed underneath the caller's view (optimistic-concurrency mismatch)."""


class InvalidTransition(DecisionError):
    """The requested act is not in the state machine's allowed-transitions table."""


class NotApprovable(DecisionError):
    """The decision has no bound envelope — nothing for an approval to bind to (legacy row)."""


def _record_event(conn: sqlite3.Connection, *, decision_id: int, actor: str, action: str,
                  from_status: str | None, to_status: str, revision: int,
                  envelope_sha256: str | None, detail: str | None = None) -> None:
    conn.execute(
        "INSERT INTO decision_events (decision_id, at, actor, action, from_status, to_status, "
        "revision, envelope_sha256, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
        (decision_id, _now(), actor, action, from_status, to_status, revision,
         envelope_sha256, detail))


def _provenance_json(value: dict | None, field: str) -> str | None:
    """Impact/confidence are provenance objects, never bare numbers (spec pt 6). None is honest
    (renders 'unknown'); anything else must be a dict so the UI can look for value/label/method."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a provenance object "
                         '({"value", "label", "method", "source", "as_of"}) or None')
    import json

    return json.dumps(value, ensure_ascii=False)


# The owner-facing headline is enforced HERE, at proposal creation — not rewritten cosmetically
# in the browser (review #75). The constraint is deliberately OBJECTIVE (required, single line,
# length-capped) rather than a "does this look technical?" heuristic: this boundary fails closed,
# and a guess that refuses a legitimate title would block real work. Long technical description
# belongs in `rationale`, which the detail page renders under "Recommendation".
MAX_TITLE_CHARS = 60


def validate_headline(title: object) -> str:
    """Return the trimmed owner-facing headline, or raise ValueError explaining the rule."""
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required — it is the owner-facing headline")
    t = title.strip()
    if "\n" in t or "\r" in t:
        raise ValueError("title must be a single line — the headline the owner reads first")
    if len(t) > MAX_TITLE_CHARS:
        raise ValueError(
            f"title is the OWNER-FACING HEADLINE and must be at most {MAX_TITLE_CHARS} "
            f"characters (got {len(t)}). Write what the owner gains — e.g. 'Improve homepage "
            "SEO' — and move the technical description to `rationale`.")
    return t


def _check_envelope_context(envelope: dict, *, expected_profile: str,
                            allowed_environments: tuple[str, ...],
                            allowed_hosts: tuple[str, ...]) -> None:
    """The proposal boundary's CONTEXT check (review #71 finding 1): the envelope states a
    profile/environment/target, but it must never be its own authority — the caller supplies
    what the RUNTIME actually is (active profile, permitted TARGET environments, the profile's
    legitimate URL hosts) and a mismatch fails closed BEFORE anything persists. Hashing a wrong
    profile makes the error tamper-evident; this check makes it impossible.

    Every piece is MANDATORY — there is deliberately no unconstrained mode at this boundary
    (review #71 round 2): a caller without host context has no business proposing, and a
    bypass would have to be a separate, loudly-named function that does not exist."""
    from ..envelope import url_host

    if not (expected_profile or "").strip():
        raise ValueError("proposal context requires expected_profile (the active profile id)")
    if not allowed_environments:
        raise ValueError("proposal context requires allowed_environments")
    if not allowed_hosts:
        raise ValueError("proposal context requires allowed_hosts (the profile's legitimate "
                         "target-URL hosts) — an unconstrained host set is not a default")
    if envelope.get("profile") != expected_profile:
        raise ValueError(
            f"envelope profile {envelope.get('profile')!r} does not match the active profile "
            f"{expected_profile!r} — refusing to propose into a store the envelope does not "
            "belong to")
    if envelope.get("environment") not in allowed_environments:
        raise ValueError(
            f"envelope environment {envelope.get('environment')!r} is not permitted in this "
            f"context (allowed: {', '.join(allowed_environments)})")
    allowed = {h.lower() for h in allowed_hosts}
    for lang, url in (envelope.get("target", {}).get("expected_urls") or {}).items():
        host = url_host(str(url))
        if host is None or host not in allowed:
            raise ValueError(
                f"target URL host {host!r} ({lang}) is not among this profile's allowed "
                f"hosts ({', '.join(sorted(allowed))}) — refusing an off-profile target")


def propose_decision(
    conn: sqlite3.Connection,
    *,
    title: str,
    envelope: dict,
    expected_profile: str,
    allowed_environments: tuple[str, ...],
    allowed_hosts: tuple[str, ...],
    rationale: str | None = None,
    evidence: str | None = None,
    impact: dict | None = None,
    confidence: dict | None = None,
    case_id: int | None = None,
    made_by: str = "agent",
) -> int:
    """Create a v4 workflow decision: validated envelope, canonical text + hash stored at birth.
    `expected_profile` / `allowed_environments` (and `allowed_hosts` where the caller has them)
    come from RUNTIME context, never from the envelope — see _check_envelope_context. The
    envelope's `kind` is denormalized onto the row for querying; the hashed truth stays the
    envelope itself."""
    from ..envelope import canonical_json, envelope_sha256, validate_envelope

    headline = validate_headline(title)
    problems = validate_envelope(envelope)
    if problems:
        raise ValueError("invalid envelope: " + "; ".join(problems))
    _check_envelope_context(envelope, expected_profile=expected_profile,
                            allowed_environments=allowed_environments,
                            allowed_hosts=allowed_hosts)
    cur = conn.execute(
        "INSERT INTO decisions (made_at, title, rationale, status, made_by, case_id, kind, "
        "envelope, envelope_sha256, revision, evidence, impact, confidence) "
        "VALUES (?, ?, ?, 'proposed', ?, ?, ?, ?, ?, 0, ?, ?, ?);",
        (_now(), headline, rationale, made_by, case_id, envelope["kind"],
         canonical_json(envelope), envelope_sha256(envelope), evidence,
         _provenance_json(impact, "impact"), _provenance_json(confidence, "confidence")))
    decision_id = int(cur.lastrowid)
    _record_event(conn, decision_id=decision_id, actor=made_by, action="propose",
                  from_status=None, to_status="proposed", revision=0,
                  envelope_sha256=envelope_sha256(envelope))
    conn.commit()
    return decision_id


def _workflow_decision(conn: sqlite3.Connection, decision_id: int) -> Decision:
    d = get_decision(conn, decision_id)
    if d is None:
        raise DecisionError(f"no decision with id {decision_id}")
    if not d.envelope_sha256:
        raise NotApprovable(
            f"decision D#{d.id} predates the approval workflow — it has no bound envelope, so "
            "there is nothing for an approval to bind to. Record a new decision to act on it.")
    return d


def _transition(conn: sqlite3.Connection, d: Decision, *, expected_revision: int,
                from_status: str, set_sql: str, params: tuple) -> None:
    """The one atomic mutation shape: succeed only against the exact (revision, status) the
    caller saw. rowcount 0 -> re-read and raise the precise refusal."""
    cur = conn.execute(
        f"UPDATE decisions SET {set_sql}, revision = revision + 1 "
        "WHERE id = ? AND revision = ? AND status = ?;",
        (*params, d.id, expected_revision, from_status))
    if cur.rowcount == 0:
        conn.rollback()
        now = get_decision(conn, d.id)
        if now is not None and now.status != from_status:
            raise InvalidTransition(
                f"decision D#{d.id} is {now.status!r}, not {from_status!r} — this act no longer "
                "applies. Reload and review the current state.")
        raise StaleRevision(
            f"decision D#{d.id} changed underneath this page (expected revision "
            f"{expected_revision}, now {getattr(now, 'revision', '?')}) — reload and review "
            "before acting.")


def approve_decision(conn: sqlite3.Connection, decision_id: int, *, expected_revision: int,
                     actor: str = "owner") -> str:
    """proposed -> approved. Returns 'approved', or 'already-approved' for the one sanctioned
    idempotent case: re-approving the identical envelope that is already approved (a duplicate
    submission must be a no-op success, never a scary error — spec concurrency rule)."""
    d = _workflow_decision(conn, decision_id)
    if d.status == "approved":
        return "already-approved"  # envelope identity is guaranteed: approved envelopes are immutable
    if d.status != "proposed":
        raise InvalidTransition(
            f"cannot approve decision D#{d.id}: it is {d.status!r}, and only proposed decisions "
            "can be approved.")
    _transition(conn, d, expected_revision=expected_revision, from_status="proposed",
                set_sql="status = 'approved', approved_at = ?, approved_by = ?",
                params=(_now(), actor))
    _record_event(conn, decision_id=d.id, actor=actor, action="approve",
                  from_status="proposed", to_status="approved",
                  revision=expected_revision + 1, envelope_sha256=d.envelope_sha256)
    conn.commit()
    return "approved"


def reject_decision(conn: sqlite3.Connection, decision_id: int, *, expected_revision: int,
                    reason: str, actor: str = "owner") -> None:
    """proposed -> rejected. The reason is REQUIRED (spec): a rejection with no why teaches the
    platform nothing and leaves the audit trail mute."""
    if not (reason or "").strip():
        raise ValueError("a rejection reason is required")
    d = _workflow_decision(conn, decision_id)
    if d.status != "proposed":
        raise InvalidTransition(
            f"cannot reject decision D#{d.id}: it is {d.status!r}, and only proposed decisions "
            "can be rejected.")
    _transition(conn, d, expected_revision=expected_revision, from_status="proposed",
                set_sql="status = 'rejected'", params=())
    _record_event(conn, decision_id=d.id, actor=actor, action="reject",
                  from_status="proposed", to_status="rejected",
                  revision=expected_revision + 1, envelope_sha256=d.envelope_sha256,
                  detail=reason.strip())
    conn.commit()


def unapprove_decision(conn: sqlite3.Connection, decision_id: int, *, expected_revision: int,
                       actor: str = "owner") -> None:
    """approved -> proposed, the ONLY path away from an approved envelope (explicit human act;
    the storage trigger refuses every other edit). Approval fields are cleared — the audit trail
    keeps who had approved what."""
    d = _workflow_decision(conn, decision_id)
    if d.status != "approved":
        raise InvalidTransition(
            f"cannot unapprove decision D#{d.id}: it is {d.status!r}, not approved.")
    _transition(conn, d, expected_revision=expected_revision, from_status="approved",
                set_sql="status = 'proposed', approved_at = NULL, approved_by = NULL",
                params=())
    _record_event(conn, decision_id=d.id, actor=actor, action="unapprove",
                  from_status="approved", to_status="proposed",
                  revision=expected_revision + 1, envelope_sha256=d.envelope_sha256)
    conn.commit()


def repropose_decision(conn: sqlite3.Connection, decision_id: int, *, expected_revision: int,
                       envelope: dict | None = None,
                       expected_profile: str | None = None,
                       allowed_environments: tuple[str, ...] | None = None,
                       allowed_hosts: tuple[str, ...] | None = None,
                       actor: str = "owner") -> None:
    """rejected -> proposed (spec: new revision; a new envelope is allowed here — and ONLY
    here, because the decision is neither approved nor terminal). A NEW envelope re-enters
    through the full proposal boundary: validation AND runtime-context checks, exactly like
    propose_decision — re-propose must never be the context-check bypass."""
    d = _workflow_decision(conn, decision_id)
    if d.status != "rejected":
        raise InvalidTransition(
            f"cannot re-propose decision D#{d.id}: it is {d.status!r}, not rejected.")
    if envelope is not None:
        from ..envelope import canonical_json, envelope_sha256, validate_envelope

        problems = validate_envelope(envelope)
        if problems:
            raise ValueError("invalid envelope: " + "; ".join(problems))
        if expected_profile is None or allowed_environments is None or allowed_hosts is None:
            raise ValueError("re-proposing a NEW envelope requires the full proposal context "
                             "(expected_profile, allowed_environments, allowed_hosts)")
        _check_envelope_context(envelope, expected_profile=expected_profile,
                                allowed_environments=allowed_environments,
                                allowed_hosts=allowed_hosts)
        new_canon, new_sha = canonical_json(envelope), envelope_sha256(envelope)
        new_kind = envelope["kind"]
    else:
        new_canon, new_sha, new_kind = d.envelope, d.envelope_sha256, d.kind
    _transition(conn, d, expected_revision=expected_revision, from_status="rejected",
                set_sql="status = 'proposed', envelope = ?, envelope_sha256 = ?, kind = ?",
                params=(new_canon, new_sha, new_kind))
    _record_event(conn, decision_id=d.id, actor=actor, action="re-propose",
                  from_status="rejected", to_status="proposed",
                  revision=expected_revision + 1, envelope_sha256=new_sha)
    conn.commit()


def record_verify_attempt(
    conn: sqlite3.Connection,
    *,
    decision_id: int,
    revision: int,
    envelope_sha256: str,
    read_number: int,
    outcome: str,
    detail: str,
    started_at: str,
    pair_id: int | None = None,
) -> int:
    """Append one immutable verification-read row (WP-U4b evidence). finished_at is stamped
    here — the row records when the read actually completed."""
    cur = conn.execute(
        "INSERT INTO decision_verify_attempts (decision_id, revision, envelope_sha256, "
        "read_number, pair_id, started_at, finished_at, outcome, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
        (decision_id, revision, envelope_sha256, read_number, pair_id, started_at, _now(),
         outcome, detail))
    conn.commit()
    return int(cur.lastrowid)


def list_verify_attempts(conn: sqlite3.Connection, decision_id: int) -> list[VerifyAttempt]:
    rows = conn.execute(
        "SELECT * FROM decision_verify_attempts WHERE decision_id = ? ORDER BY id ASC;",
        (decision_id,)).fetchall()
    return [VerifyAttempt(**r) for r in rows]


def pending_verify_attempt(conn: sqlite3.Connection, decision_id: int, *,
                           revision: int) -> VerifyAttempt | None:
    """The store-backed pending state (spec: survives reloads, sign-outs and restarts): the
    newest MATCHING read #1 for the CURRENT revision that no read #2 has answered yet. A
    revision change (unapprove/re-approve) orphans old reads by construction — verification
    can never confirm against an envelope the owner has since revisited."""
    row = conn.execute(
        "SELECT * FROM decision_verify_attempts a WHERE a.decision_id = ? AND a.revision = ? "
        "AND a.read_number = 1 AND a.outcome = 'match' "
        "AND NOT EXISTS (SELECT 1 FROM decision_verify_attempts b WHERE b.pair_id = a.id) "
        "ORDER BY a.id DESC LIMIT 1;",
        (decision_id, revision)).fetchone()
    return VerifyAttempt(**row) if row else None


def execute_decision(conn: sqlite3.Connection, decision_id: int, *, expected_revision: int,
                     evidence_attempt_id: int, actor: str = "platform") -> None:
    """approved -> executed (terminal): only the verification service calls this, and only on
    two consistent full matches. execution_evidence POINTS at the terminal successful attempt —
    it never restates it, and prior failed attempts stay untouched (append-only table)."""
    d = _workflow_decision(conn, decision_id)
    if d.status != "approved":
        raise InvalidTransition(
            f"cannot execute decision D#{d.id}: it is {d.status!r}, not approved.")
    _transition(conn, d, expected_revision=expected_revision, from_status="approved",
                set_sql="status = 'executed', executed_at = ?, execution_evidence = ?",
                params=(_now(), f"verify_attempt:{evidence_attempt_id}"))
    _record_event(conn, decision_id=d.id, actor=actor, action="execute",
                  from_status="approved", to_status="executed",
                  revision=expected_revision + 1, envelope_sha256=d.envelope_sha256,
                  detail=f"verified live (attempt #{evidence_attempt_id})")
    conn.commit()


def adopt_key(*, source_id: int, source_revision: int, envelope_sha256: str,
              snapshot_digest: str) -> str:
    """The exact, durable identity of one adoption: which decision, at which revision, bound to
    which envelope, from which displayed snapshot. Never a substring search over prose."""
    return f"{source_id}:{source_revision}:{envelope_sha256}:{snapshot_digest}"


def adopted_decision_id(conn: sqlite3.Connection, key: str) -> int | None:
    """The decision this exact adoption already created, or None. An O(1) keyed lookup — it
    keeps working when the archive holds a hundred thousand decisions (review #76)."""
    row = conn.execute(
        "SELECT created_decision_id FROM decision_adoptions WHERE adopt_key = ?;",
        (key,)).fetchone()
    return row["created_decision_id"] if row else None


def claim_adoption(conn: sqlite3.Connection, key: str, *, source_id: int,
                   source_revision: int, envelope_sha256: str, snapshot_digest: str) -> bool:
    """Reserve the key before creating anything. False = it is already taken by a COMPLETED
    adoption (the caller redirects to it). A claim left incomplete by a failed attempt is
    reclaimed here rather than blocking retries forever — an interrupted adoption must not
    become a permanent refusal."""
    row = conn.execute("SELECT created_decision_id FROM decision_adoptions WHERE adopt_key = ?;",
                       (key,)).fetchone()
    if row is not None:
        if row["created_decision_id"] is not None:
            return False
        conn.execute("DELETE FROM decision_adoptions WHERE adopt_key = ?;", (key,))
    try:
        conn.execute(
            "INSERT INTO decision_adoptions (adopt_key, source_id, source_revision, "
            "source_envelope, snapshot_digest, at) VALUES (?, ?, ?, ?, ?, ?);",
            (key, source_id, source_revision, envelope_sha256, snapshot_digest, _now()))
    except sqlite3.IntegrityError:
        # Distinguish the two IntegrityErrors that can land here (review #76's own lesson,
        # applied one level down): a DUPLICATE KEY means someone else claimed it — that is
        # policy, answer False. Anything else (e.g. a foreign-key violation from a bad
        # source_id) is a DEFECT and must stay loud rather than look like a refusal.
        taken = conn.execute("SELECT 1 FROM decision_adoptions WHERE adopt_key = ?;",
                             (key,)).fetchone()
        if taken is None:
            raise
        return False
    conn.commit()
    return True


def complete_adoption(conn: sqlite3.Connection, key: str, decision_id: int) -> None:
    conn.execute("UPDATE decision_adoptions SET created_decision_id = ? WHERE adopt_key = ?;",
                 (decision_id, key))
    conn.commit()


def list_decision_events(conn: sqlite3.Connection, decision_id: int) -> list[DecisionEvent]:
    rows = conn.execute(
        "SELECT * FROM decision_events WHERE decision_id = ? ORDER BY id ASC;",
        (decision_id,)).fetchall()
    return [DecisionEvent(**r) for r in rows]


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
    delivery_attempts: int
    delivered_at: str | None
    recommendations_count: int | None = None  # v4: best-effort parse; None renders "unknown"


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
    recommendations_count: int | None = None,
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
        "content_sha256, body, recommendations_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
        (run_id, kind, profile, window, generated_at or _now(), format_version,
         validator_version, 1 if validator_ok else 0, validator_reason, model, cost_usd,
         hashlib.sha256(raw).hexdigest(), body, recommendations_count),
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
    conn.execute("UPDATE report_artifacts SET delivery_status = ?, delivered_at = ?, "
                 "delivery_attempts = delivery_attempts + 1 WHERE id = ?;",
                 (status, _now(), artifact_id))
    conn.commit()


def set_artifact_delivery_by_hash(conn: sqlite3.Connection, content_sha256: str, status: str) -> bool:
    """Mark the LATEST artifact with this exact content hash. Hash-keyed on purpose: delivery is
    recorded against the precise bytes that were sent, never against 'whatever row is newest' —
    the chain stays self-verifying end to end. Returns False when no artifact matches."""
    cur = conn.execute(
        "UPDATE report_artifacts SET delivery_status = ?, delivered_at = ?, "
        "delivery_attempts = delivery_attempts + 1 WHERE id = "
        "(SELECT id FROM report_artifacts WHERE content_sha256 = ? ORDER BY id DESC LIMIT 1);",
        (status, _now(), content_sha256))
    conn.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------- WP-U4d deploy runs

def plan_deploy(conn: sqlite3.Connection, *, sha: str, plan: dict, plan_digest: str,
                requested_by: str) -> int:
    """Record an authorized deployment target. The ROW is the authorization: `execute` refuses
    any run that is not `planned`, and the triggers refuse to let `sha`, `plan` or `plan_digest`
    be edited afterwards, so a reviewed plan can never come to execute a different commit."""
    cur = conn.execute(
        "INSERT INTO deploy_runs (sha, requested_at, requested_by, plan, plan_digest, status) "
        "VALUES (?, ?, ?, ?, ?, 'planned')",
        (sha, _now(), requested_by, json.dumps(plan, sort_keys=True, ensure_ascii=False),
         plan_digest))
    conn.commit()
    return int(cur.lastrowid)


def get_deploy_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM deploy_runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_deploy_runs(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM deploy_runs ORDER BY id DESC LIMIT ?", (limit,))]


def start_deploy_run(conn: sqlite3.Connection, run_id: int, *, pid: int) -> bool:
    """planned -> running, exactly once. The WHERE clause is the concurrency control: two
    runners racing on the same row means only one wins and the loser refuses to proceed."""
    cur = conn.execute(
        "UPDATE deploy_runs SET status='running', started_at=?, runner_pid=? "
        "WHERE id=? AND status='planned'", (_now(), int(pid), run_id))
    conn.commit()
    return cur.rowcount == 1


def finish_deploy_run(conn: sqlite3.Connection, run_id: int, *, status: str,
                      outcome: str) -> None:
    if status not in ("succeeded", "failed", "refused"):
        raise ValueError(f"not a terminal deploy status: {status}")
    conn.execute("UPDATE deploy_runs SET status=?, finished_at=?, outcome=? WHERE id=?",
                 (status, _now(), outcome, run_id))
    conn.commit()


def record_deploy_step(conn: sqlite3.Connection, run_id: int, *, seq: int, name: str,
                       status: str, summary: str, detail: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO deploy_steps (run_id, seq, at, name, status, summary, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, int(seq), _now(), name, status, summary, detail))
    conn.commit()
    return int(cur.lastrowid)


def list_deploy_steps(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM deploy_steps WHERE run_id = ? ORDER BY seq", (run_id,))]


# --------------------------------------------------------------------- WP-U4d.2 acceptance runs

ACCEPTANCE_VERDICTS = ("PASS", "FAILED SAFELY", "BLOCKED")


def begin_acceptance_run(conn: sqlite3.Connection, *, requested_by: str, root: str) -> int | None:
    """Create the run row, or return None if a live (non-terminal) acceptance already exists.

    The INSERT ... WHERE NOT EXISTS is the concurrency control: two racing requests resolve in
    the database, not in application code, so at most one acceptance is ever live — the run
    mutates real host state and two of them interleaving would corrupt each other's evidence."""
    cur = conn.execute(
        "INSERT INTO acceptance_runs (requested_at, requested_by, root, status) "
        "SELECT ?, ?, ?, 'requested' "
        "WHERE NOT EXISTS (SELECT 1 FROM acceptance_runs WHERE status != 'done')",
        (_now(), requested_by, root))
    conn.commit()
    return int(cur.lastrowid) if cur.rowcount == 1 else None


def set_acceptance_root(conn: sqlite3.Connection, run_id: int, root: str) -> bool:
    """Stamp the server-derived run directory. The root is derived FROM the row id, so it can
    only be known after the insert; this is the second half of that one creation, allowed only
    while the row is still 'requested' and still carries the 'pending' placeholder."""
    cur = conn.execute(
        "UPDATE acceptance_runs SET root=? WHERE id=? AND status='requested' AND root='pending'",
        (root, run_id))
    conn.commit()
    return cur.rowcount == 1


def get_acceptance_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM acceptance_runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_acceptance_runs(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM acceptance_runs ORDER BY id DESC LIMIT ?", (limit,))]


def claim_acceptance_run(conn: sqlite3.Connection, run_id: int) -> bool:
    """requested -> running, exactly once — same shape as start_deploy_run."""
    cur = conn.execute(
        "UPDATE acceptance_runs SET status='running', started_at=? "
        "WHERE id=? AND status='requested'", (_now(), run_id))
    conn.commit()
    return cur.rowcount == 1


def finish_acceptance_run(conn: sqlite3.Connection, run_id: int, *, verdict: str,
                          summary: str) -> None:
    if verdict not in ACCEPTANCE_VERDICTS:
        raise ValueError(f"not an acceptance verdict: {verdict}")
    conn.execute(
        "UPDATE acceptance_runs SET status='done', finished_at=?, verdict=?, summary=? "
        "WHERE id=?", (_now(), verdict, summary, run_id))
    conn.commit()


def record_acceptance_phase(conn: sqlite3.Connection, run_id: int, *, seq: int, name: str,
                            status: str, detail: str | None = None) -> int:
    if status not in ("ok", "deferred", "failed", "refused"):
        raise ValueError(f"not an acceptance phase status: {status}")
    cur = conn.execute(
        "INSERT INTO acceptance_phases (run_id, seq, at, name, status, detail) "
        "VALUES (?, ?, ?, ?, ?, ?)", (run_id, int(seq), _now(), name, status, detail))
    conn.commit()
    return int(cur.lastrowid)


def list_acceptance_phases(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM acceptance_phases WHERE run_id = ? ORDER BY seq", (run_id,))]


# --- WP-U5.1: inspection runs and observations --------------------------------------------------
#
# Every function here takes `profile` and `environment` as required keyword arguments. There is
# deliberately no "resolve it from the environment if omitted" convenience: the older evidence
# paths do exactly that and it is what allows a run's identity to disagree with its rows.

_OBSERVATION_STATUSES = ("ok", "warn", "action", "unknown")
_CHANGE_CLASSES = ("baseline", "unchanged", "changed", "appeared", "disappeared")


def _require_identity(profile: str, environment: str) -> tuple[str, str]:
    p, e = (profile or "").strip(), (environment or "").strip()
    if not p or not e:
        raise ValueError(
            "an inspection needs an explicit profile and environment; refusing to record "
            "evidence whose subject is unknown (issue #82 amendment 1)")
    return p, e


def begin_inspection_run(conn: sqlite3.Connection, *, profile: str, environment: str,
                         trigger: str, collector_set_version: str, repo_commit: str) -> int:
    profile, environment = _require_identity(profile, environment)
    if trigger not in ("console", "schedule", "cli"):
        raise ValueError(f"not an inspection trigger: {trigger}")
    cur = conn.execute(
        "INSERT INTO inspection_runs (started_at, profile, environment, trigger, "
        "collector_set_version, repo_commit, status) VALUES (?, ?, ?, ?, ?, ?, 'running')",
        (_now(), profile, environment, trigger, collector_set_version, repo_commit or "unknown"))
    conn.commit()
    return int(cur.lastrowid)


def finish_inspection_run(conn: sqlite3.Connection, run_id: int, *, summary: str) -> None:
    conn.execute(
        "UPDATE inspection_runs SET status='done', finished_at=?, summary=? WHERE id=?",
        (_now(), summary, run_id))
    conn.commit()


def get_inspection_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM inspection_runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def latest_inspection_run(conn: sqlite3.Connection, *, profile: str,
                          environment: str) -> dict | None:
    profile, environment = _require_identity(profile, environment)
    row = conn.execute(
        "SELECT * FROM inspection_runs WHERE profile = ? AND environment = ? "
        "ORDER BY id DESC LIMIT 1", (profile, environment)).fetchone()
    return dict(row) if row else None


def latest_observation(conn: sqlite3.Connection, *, profile: str, environment: str,
                       scope: str) -> dict | None:
    """The predecessor for a scope, scoped to ONE identity.

    The identity columns are part of the WHERE clause rather than a filter applied afterwards,
    so a diff cannot be computed against another business's or environment's history even if the
    scope names collide — which they will, since every profile has a `host.capacity`.
    """
    profile, environment = _require_identity(profile, environment)
    row = conn.execute(
        "SELECT * FROM observations WHERE profile = ? AND environment = ? AND scope = ? "
        "ORDER BY id DESC LIMIT 1", (profile, environment, scope)).fetchone()
    return dict(row) if row else None


def record_observation(conn: sqlite3.Connection, run_id: int, *, collector_id: str,
                       collector_version: str, scope: str, source: str, profile: str,
                       environment: str, captured_at: str, status: str, value_json: str,
                       value_digest: str, evidence: str | None, predecessor_id: int | None,
                       change_class: str, severity: str, confidence: str | None,
                       reason: str | None, material_json: str | None = None,
                       material_digest: str | None = None) -> int:
    profile, environment = _require_identity(profile, environment)
    if status not in _OBSERVATION_STATUSES:
        raise ValueError(f"not an observation status: {status}")
    if severity not in _OBSERVATION_STATUSES:
        raise ValueError(f"not an observation severity: {severity}")
    if change_class not in _CHANGE_CLASSES:
        raise ValueError(f"not a change class: {change_class}")
    # The run's identity is authoritative; an observation may not be filed under a different one.
    run = conn.execute("SELECT profile, environment FROM inspection_runs WHERE id = ?",
                       (run_id,)).fetchone()
    if run is None:
        raise ValueError(f"no such inspection run: {run_id}")
    if (run["profile"], run["environment"]) != (profile, environment):
        raise ValueError(
            f"observation identity {profile}/{environment} does not match its inspection run "
            f"{run['profile']}/{run['environment']} — refusing to split one run's identity")
    cur = conn.execute(
        "INSERT INTO observations (run_id, collector_id, collector_version, scope, source, "
        "profile, environment, captured_at, status, value_json, value_digest, evidence, "
        "predecessor_id, change_class, severity, confidence, reason, material_json, "
        "material_digest) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, collector_id, collector_version, scope, source, profile, environment,
         captured_at, status, value_json, value_digest, evidence, predecessor_id, change_class,
         severity, confidence, reason, material_json, material_digest))
    conn.commit()
    return int(cur.lastrowid)


def list_observations(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM observations WHERE run_id = ? ORDER BY scope, id", (run_id,))]


def latest_observations(conn: sqlite3.Connection, *, profile: str,
                        environment: str) -> list[dict]:
    """The newest observation per scope for one identity — what the owner surface renders."""
    profile, environment = _require_identity(profile, environment)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM observations WHERE id IN ("
        "  SELECT MAX(id) FROM observations WHERE profile = ? AND environment = ? GROUP BY scope"
        ") ORDER BY scope", (profile, environment))]
