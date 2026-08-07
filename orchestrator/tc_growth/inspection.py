"""WP-U5.1 — the read-only Operations Intelligence foundation (issue #82).

Collect → normalize → snapshot → compare → classify. Nothing here writes to anything it
inspects, opens a case, or executes an operation; U5.1 produces evidence and a verdict about
that evidence, and stops.

Three properties are load-bearing, each answering a specific way this kind of system lies:

1. **Identity is supplied, never inferred.** `CollectionContext` requires a profile and an
   environment and refuses to be constructed without them. The platform's older evidence paths
   resolve identity from process-global state with silent fallbacks, so a collection launched
   for one business could record evidence stamped with another's. A U5 observation that cannot
   say whose environment it describes is not evidence (issue #82, amendment 1).

2. **Collection and judgement are separate.** A collector reports what it saw; `classify` and
   `severity_for` decide what that means, deterministically, from a table. A model may explain a
   severity afterwards but never invents one (issue #82 §16) — infrastructure facts are not a
   matter of opinion, and a severity that varies between runs on identical input is not a
   severity.

3. **Freshness is computed when read, not when written.** An observation records when it was
   captured; whether that is still *current* depends on the clock at render time. Freezing it
   into the append-only row would leave yesterday's `current` looking green forever, which is
   the precise dishonesty §15 exists to prevent.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol, runtime_checkable

from . import deploy, envelope

#: Bumped when the meaning of a collector's normalized output changes, so a diff is never
#: computed across two incompatible readings of the same scope.
COLLECTOR_SET_VERSION = "u5/1"

# --- vocabularies -------------------------------------------------------------------------------
# `unknown` is a real state, not a missing one: it means the source could not be read. It never
# renders as healthy and never collapses into ok (issue #82 §14, §16).
STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_ACTION = "action"
STATUS_UNKNOWN = "unknown"
STATUSES = (STATUS_OK, STATUS_WARN, STATUS_ACTION, STATUS_UNKNOWN)

CHANGE_BASELINE = "baseline"          # no predecessor — NOT "unchanged" (issue #82 criterion 7)
CHANGE_UNCHANGED = "unchanged"
CHANGE_CHANGED = "changed"
CHANGE_APPEARED = "appeared"          # scope observable now, unreadable before
CHANGE_DISAPPEARED = "disappeared"    # scope was observable, now is not

FRESH_CURRENT = "current"
FRESH_AGING = "aging"
FRESH_STALE = "stale"
FRESH_UNAVAILABLE = "unavailable"
FRESH_NEVER = "never"

#: Evidence is a bounded, redacted summary. A collector that wants to say more says less.
MAX_EVIDENCE_BYTES = 2000


class CollectionRefused(Exception):
    """Raised before any collection happens when the request itself is not answerable."""


# --- context ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class CollectionContext:
    """Everything a collector is allowed to know, and the identity every row it produces carries.

    There is no default profile or environment on purpose. `CollectionContext()` cannot be
    constructed without saying whose environment is being inspected, so no code path exists that
    quietly inspects one business and files the result under another.
    """

    profile: str
    environment: str
    repo_commit: str = "unknown"
    max_evidence_bytes: int = MAX_EVIDENCE_BYTES
    #: Injected so tests can freeze it; production passes the real clock.
    now: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not (self.profile or "").strip():
            raise CollectionRefused(
                "a collection needs an explicit profile; refusing to inspect on behalf of "
                "whichever business happens to be configured in this process")
        if not (self.environment or "").strip():
            raise CollectionRefused(
                "a collection needs an explicit environment; staging and production evidence "
                "must never be interchangeable")

    def now_iso(self) -> str:
        return self.now().replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class CollectorResult:
    """What a collector saw. It states a status but never a severity — that is policy's job."""

    scope: str
    status: str
    value: dict[str, Any]
    source: str
    evidence: str = ""
    reason: str = ""
    confidence: str | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"not a collector status: {self.status}")


@runtime_checkable
class Collector(Protocol):
    id: str
    version: str
    scope: str

    def collect(self, ctx: CollectionContext) -> CollectorResult: ...


# --- normalization ------------------------------------------------------------------------------

def canonical_value(value: dict[str, Any]) -> str:
    """One canonical text form per value, so equal readings hash equally.

    Reuses the envelope's canonicalization (stable key order, no insignificant whitespace, real
    Unicode) rather than re-deriving it — two digest disciplines in one codebase is one too many.
    The envelope TYPE is not reused: that is approval-bound and rightly closed.
    """
    return envelope.canonical_json(value)


def value_digest(value: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(canonical_value(value).encode("utf-8")).hexdigest()


def bound_evidence(text: str, *, limit: int = MAX_EVIDENCE_BYTES) -> str:
    """Redact, then truncate, then say so. Order matters: truncating first could cut a secret in
    half and leave the readable half in the record."""
    if not text:
        return ""
    safe = deploy.redact(text)
    raw = safe.encode("utf-8")
    if len(raw) <= limit:
        return safe
    kept = raw[:limit].decode("utf-8", errors="ignore")
    return f"{kept}\n[... truncated at {limit} bytes of {len(raw)}]"


# --- classification -----------------------------------------------------------------------------

def classify(previous: dict | None, current: CollectorResult) -> str:
    """What changed, decided from the durable predecessor row and the fresh reading.

    A first observation is `baseline`. Reporting it as `unchanged` would be a claim about a
    comparison that never happened, and it is the single easiest way for this kind of system to
    look reassuring on day one (issue #82 criterion 7).
    """
    if previous is None:
        return CHANGE_BASELINE
    was_unknown = previous["status"] == STATUS_UNKNOWN
    is_unknown = current.status == STATUS_UNKNOWN
    if was_unknown and not is_unknown:
        return CHANGE_APPEARED
    if is_unknown and not was_unknown:
        return CHANGE_DISAPPEARED
    if is_unknown and was_unknown:
        # Still unreadable. Nothing was compared, so nothing changed — but it is not healthy
        # either; the severity table keeps it `unknown`.
        return CHANGE_UNCHANGED
    if previous["value_digest"] == value_digest(current.value):
        return CHANGE_UNCHANGED
    return CHANGE_CHANGED


#: (change_class) -> severity, applied when the collector itself reported `ok`.
#:
#: Conservative and explainable beats clever (issue #82 §16). A diff is NOT automatically an
#: alert: a changed fact with no demonstrated failure is something to keep an eye on, not
#: something to wake the owner for. Per-scope overrides land in U5.2 with the real collectors,
#: where there is evidence to justify them.
_CHANGE_SEVERITY: dict[str, str] = {
    CHANGE_BASELINE: STATUS_OK,
    CHANGE_UNCHANGED: STATUS_OK,
    CHANGE_CHANGED: STATUS_WARN,
    CHANGE_APPEARED: STATUS_OK,
    CHANGE_DISAPPEARED: STATUS_UNKNOWN,
}


def severity_for(result: CollectorResult, change_class: str) -> str:
    """The deterministic severity. Same inputs, same answer, every time.

    A collector that reports `warn` or `action` has seen something policy cannot soften — a
    threshold breach is a threshold breach whether or not it also changed. `unknown` dominates
    everything: a source that could not be read cannot be called healthy.
    """
    if result.status == STATUS_UNKNOWN:
        return STATUS_UNKNOWN
    if result.status in (STATUS_WARN, STATUS_ACTION):
        return result.status
    return _CHANGE_SEVERITY.get(change_class, STATUS_UNKNOWN)


# --- freshness ----------------------------------------------------------------------------------
#
# Evaluated at READ time against the observation's captured_at. Defaults are deliberately
# generous for U5.1, which has no scheduled collection yet; U5.2 ties them to policy per scope.

AGING_AFTER = timedelta(hours=26)
STALE_AFTER = timedelta(hours=50)


def freshness(captured_at: str | None, *, now: datetime,
              aging_after: timedelta = AGING_AFTER,
              stale_after: timedelta = STALE_AFTER) -> str:
    """How much the age of this reading should be allowed to reassure the owner.

    Never observed is not fresh, and an unparseable timestamp is not fresh either — a record we
    cannot date cannot be vouched for.
    """
    if not captured_at:
        return FRESH_NEVER
    try:
        seen = datetime.fromisoformat(captured_at)
    except ValueError:
        return FRESH_UNAVAILABLE
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    age = now - seen
    if age >= stale_after:
        return FRESH_STALE
    if age >= aging_after:
        return FRESH_AGING
    return FRESH_CURRENT


def effective_status(observation: dict, *, now: datetime) -> str:
    """What the owner surface must show for this row, right now.

    A stale observation cannot keep asserting health however green it was when written. It
    degrades to `unknown` rather than to `ok`, because the honest statement is "we do not
    currently know", not "it was fine yesterday" (issue #82 §15, criterion 6).
    """
    fresh = freshness(observation.get("captured_at"), now=now)
    severity = observation.get("severity", STATUS_UNKNOWN)
    if fresh in (FRESH_STALE, FRESH_UNAVAILABLE, FRESH_NEVER):
        # A real problem stays a real problem — going stale never downgrades an alarm.
        return STATUS_UNKNOWN if severity == STATUS_OK else severity
    return severity


#: Worst-first, so a single unreadable source cannot be averaged away by healthy neighbours.
_ROLLUP_ORDER = (STATUS_ACTION, STATUS_UNKNOWN, STATUS_WARN, STATUS_OK)


def rollup(statuses: list[str]) -> str:
    """The one state at the top of the page. `unknown` outranks `warn` deliberately: not knowing
    whether the backups exist is worse than knowing a disk is filling slowly."""
    if not statuses:
        return STATUS_UNKNOWN
    for candidate in _ROLLUP_ORDER:
        if candidate in statuses:
            return candidate
    return STATUS_UNKNOWN


# --- the sweep ----------------------------------------------------------------------------------

def _unknown_result(collector: Collector, exc: Exception) -> CollectorResult:
    """A collector that raised still owes the record an answer — naming what it could not reach.

    Silence would be indistinguishable from "nothing to report", which is how a monitoring system
    ends up quietly watching nothing (issue #82 §14).
    """
    return CollectorResult(
        scope=getattr(collector, "scope", getattr(collector, "id", "unknown")),
        status=STATUS_UNKNOWN,
        value={"error": type(exc).__name__},
        source=getattr(collector, "id", "unknown"),
        evidence=bound_evidence(f"{type(exc).__name__}: {exc}"),
        reason="this source could not be read, so its state is unknown — not healthy",
    )


def run_inspection(store, collectors: list[Collector], ctx: CollectionContext, *,
                   trigger: str = "cli") -> int:
    """One sweep: every collector, each recorded against its own predecessor.

    Collectors are independent. One blowing up produces an `unknown` observation for its scope
    and nothing more — the rest of the page still renders, because a monitoring surface that
    disappears when one probe fails tells the owner less than no surface at all.
    """
    run_id = store.begin_inspection_run(
        profile=ctx.profile, environment=ctx.environment, trigger=trigger,
        collector_set_version=COLLECTOR_SET_VERSION, repo_commit=ctx.repo_commit)

    severities: list[str] = []
    for collector in collectors:
        try:
            result = collector.collect(ctx)
        except Exception as exc:  # noqa: BLE001 — an unreadable source is evidence, not a crash
            result = _unknown_result(collector, exc)

        previous = store.latest_observation(profile=ctx.profile, environment=ctx.environment,
                                            scope=result.scope)
        change_class = classify(previous, result)
        severity = severity_for(result, change_class)
        severities.append(severity)
        store.record_observation(
            run_id,
            collector_id=collector.id,
            collector_version=collector.version,
            scope=result.scope,
            source=result.source,
            profile=ctx.profile,
            environment=ctx.environment,
            captured_at=ctx.now_iso(),
            status=result.status,
            value_json=canonical_value(result.value),
            value_digest=value_digest(result.value),
            evidence=bound_evidence(result.evidence, limit=ctx.max_evidence_bytes),
            predecessor_id=previous["id"] if previous else None,
            change_class=change_class,
            severity=severity,
            confidence=result.confidence,
            reason=result.reason or None,
            # case_id is deliberately never passed: U5.1/U5.2 create no cases (amendment 2).
        )

    overall = rollup(severities)
    store.finish_inspection_run(
        run_id, summary=f"{len(collectors)} collector(s), {overall}")
    return run_id


def repo_commit() -> str:
    """The deployed commit, as pinned at deploy time. Never guessed."""
    return os.environ.get("TC_BUILD_COMMIT", "unknown")


def observation_value(observation: dict) -> dict:
    """Parse a stored value back, tolerating nothing — a row we cannot read is not evidence."""
    try:
        parsed = json.loads(observation["value_json"])
    except (KeyError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
