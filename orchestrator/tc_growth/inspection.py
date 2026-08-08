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
import re
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
#: The normalized value is bounded too, and for the same reason. It is structured rather than
#: prose, so it gets its own (larger) budget — an inventory of plugins is legitimately bigger
#: than a log excerpt.
MAX_VALUE_BYTES = 8000

#: Keys whose VALUE is secret whatever it looks like. `deploy.redact` masks secret-shaped text
#: (`NAME=value`, `Bearer …`), which is the right tool for prose — but it needs the name and the
#: value to be adjacent, and canonical JSON renders `{"api_token":"xyz"}` with a quote between
#: them, so a structured secret slips straight past it. Hence a structural pass as well.
#:
#: Segments are matched with separators on both sides so `keywords` and `monkey` are not
#: mistaken for secrets. Where the two disagree, over-redaction wins: a masked plugin field is
#: an inconvenience, a leaked credential in an append-only table is permanent.
_SECRET_KEY_RE = re.compile(
    r"(?i)(?:^|[_\-.])(?:api[_\-.]?key|access[_\-.]?key|private[_\-.]?key|secret[_\-.]?key|"
    r"token|secret|password|passwd|pwd|credential|credentials|authorization|"
    r"session[_\-.]?id|cookie)(?:$|[_\-.])")
_REDACTED = "***redacted***"
#: Depth guard: a collector returning a deeply nested structure is a bug, and recursing into it
#: to find out is how a monitoring sweep takes down the Console.
_MAX_VALUE_DEPTH = 12

#: An owner-facing sentence, not a place to put a log excerpt.
MAX_REASON_BYTES = 400
#: `confidence` is a label ('high'), not prose.
MAX_CONFIDENCE_BYTES = 64
#: Identifiers are authored by collector CODE, never derived from inspected data, so they can be
#: held to a strict contract rather than merely sanitized. Anything outside it is a collector
#: bug, and the honest response is to keep the evidence but stop trusting the reading.
MAX_IDENTIFIER_LEN = 64
_IDENTIFIER_ALLOWED = re.compile(r"[^A-Za-z0-9._\-]+")


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
    max_value_bytes: int = MAX_VALUE_BYTES
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
    #: The MATERIAL state — the part of `value` whose change means something. `None` means the
    #: whole value is material, which is only true for a collector whose reading does not move
    #: on its own. See `MATERIAL STATE` below for why this exists.
    material: dict[str, Any] | None = None

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


def redact_value(obj: Any, *, depth: int = 0) -> Any:
    """Mask secrets inside a NORMALIZED value, structurally.

    Two passes, because one is not enough. Every string leaf goes through `deploy.redact`, which
    catches secret-shaped prose a collector scraped from somewhere. Separately, any key whose
    NAME says its value is a credential has that value replaced outright — the value of a field
    called `api_token` is a secret whether or not it happens to look like one.

    This runs at the common collection boundary rather than in each collector, so it protects
    collectors nobody has written yet. Relying on future authors to remember is not a boundary.
    """
    if depth > _MAX_VALUE_DEPTH:
        return "[too deeply nested to record]"
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            name = str(key)
            if _SECRET_KEY_RE.search(name):
                out[name] = _REDACTED
            else:
                out[name] = redact_value(value, depth=depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact_value(v, depth=depth + 1) for v in obj]
    if isinstance(obj, str):
        return deploy.redact(obj)
    return obj


@dataclass(frozen=True)
class NormalizedValue:
    """What actually gets stored: the safe value, its canonical bytes, and its digest.

    The digest is taken over the SAFE value, so it binds what the record contains rather than
    source material the record deliberately does not hold. It also has to be this way for drift
    to work at all: a digest of the raw value could never match the stored predecessor's, and
    every sweep would report change forever.
    """

    value: dict[str, Any]
    canonical: str
    digest: str
    oversized: bool


def prepare_value(value: dict[str, Any], *, limit: int = MAX_VALUE_BYTES) -> NormalizedValue:
    """Redact, then bound, then canonicalize and digest — in that order.

    An oversized value is not silently truncated: half a JSON document is not evidence, and a
    truncated structure would digest differently on every run and read as permanent drift. It is
    replaced by an honest statement of its size, and the caller degrades the observation to
    `unknown` — we saw something and could not record it faithfully, which is precisely what
    `unknown` means.
    """
    safe = redact_value(value if isinstance(value, dict) else {"value": value})
    canonical = canonical_value(safe)
    if len(canonical.encode("utf-8")) > limit:
        safe = {"error": "value exceeded the permitted size and was not recorded",
                "bytes": len(canonical.encode("utf-8")), "limit": limit}
        canonical = canonical_value(safe)
        return NormalizedValue(safe, canonical, _sha256(canonical), True)
    return NormalizedValue(safe, canonical, _sha256(canonical), False)


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- MATERIAL STATE ------------------------------------------------------------------------------
#
# Drift is computed over the MATERIAL state, not over the whole reading. The difference is not a
# refinement; without it the feature reports change on every sweep of a host where nothing
# happened, which was measured on the U5.2 collectors as merged:
#
#     platform.services   changed   warn      <- ages recomputed against now(); ALWAYS differs
#     host.capacity       changed   warn      <- free space moved 0.2 GB in ten minutes
#     logs.signatures     changed   warn      <- the same error occurred once more
#
# Every one of those is a WARN the owner must read and dismiss, on a host where nothing changed.
# That is the alert fatigue issue #82 §7 forbids, arriving by a route nobody looked at: the
# collectors were each judged sound in isolation, and the defect lives in what the digest is
# taken OVER. `platform.services` is the clearest case — `last_trigger_age_hours` is `now` minus
# a fixed instant, so its digest cannot be equal to its predecessor's, ever, by construction.
#
# So a collector separates two things it was previously conflating:
#
# * `value`    — everything observed, stored in full as evidence. Ages, byte counts, percentages.
# * `material` — the state whose CHANGE is a fact about the host rather than about the clock.
#                A judged band (`low`), a verdict (`overdue`), a set of signatures, a version.
#
# Two digests follow, and they answer different questions:
#
# * `value_digest`    — binds the exact bytes this row holds. Integrity. Unchanged in meaning.
# * `material_digest` — what `classify` compares. Drift.
#
# The alternative — an override in `_SCOPE_CHANGE_SEVERITY` per noisy scope — was rejected: with
# every scope overridden to `ok`, change detection would still be wrong on every sweep and would
# additionally have stopped saying so. Suppressing the alarm is not fixing the smoke.

def material_of(result: "CollectorResult") -> dict[str, Any]:
    """The material state to compare, defaulting to the whole value.

    A collector that declares nothing gets exactly the pre-existing behaviour. That default is
    right for a genuinely stable reading and wrong for a moving one, which is why the moving ones
    declare.
    """
    material = result.material
    if material is None:
        return result.value if isinstance(result.value, dict) else {"value": result.value}
    return material if isinstance(material, dict) else {"material": material}


def safe_text(text: object, *, limit: int) -> str:
    """Redact, then truncate, then say so.

    Order matters: truncating first could cut a secret in half and leave the readable half in
    the record. Every collector-originated string reaching durable evidence or the owner surface
    goes through here — `reason` and `confidence` as much as `evidence`, because a field's
    intended purpose is not a security property (PR #85 re-review).
    """
    if not text:
        return ""
    safe = deploy.redact(str(text))
    raw = safe.encode("utf-8")
    if len(raw) <= limit:
        return safe
    kept = raw[:limit].decode("utf-8", errors="ignore")
    return f"{kept}\n[... truncated at {limit} bytes of {len(raw)}]"


def bound_evidence(text: str, *, limit: int = MAX_EVIDENCE_BYTES) -> str:
    """Evidence, redacted and bounded. Kept as its own name because it is the field most likely
    to carry scraped source text, and reads better at the call site."""
    return safe_text(text, limit=limit)


def safe_identifier(raw: object, *, fallback: str) -> tuple[str, bool]:
    """Hold an identifier to a strict contract; return it and whether it already complied.

    `scope` is the key drift is computed against and `source`/`collector_id` are rendered, so an
    identifier carrying markup, a URL or a credential is both a display hazard and a diff
    hazard. These fields are written by collector code rather than derived from the systems
    being inspected, so a strict `[A-Za-z0-9._-]` contract costs a well-behaved collector
    nothing — and a violation is a bug worth surfacing rather than quietly cleaning up.

    A non-conforming identifier is replaced ENTIRELY, never cleaned up in place. Stripping the
    offending characters looks like sanitizing and is not: it turns
    `https://user:pa55w0rd@host` into `httpsuserpa55w0rdhost`, which still contains the
    password and now looks harmless. The replacement carries a short digest of the original so
    it stays deterministic — the same bad identifier always lands on the same safe one, so drift
    still works and two different broken collectors do not collide — while carrying not one
    character of the source text. The caller degrades the reading to `unknown`, because a
    collector that cannot name its own scope is not one whose reading should be believed.
    """
    text = str(raw or "").strip()
    if not text:
        return fallback, False
    if len(text) <= MAX_IDENTIFIER_LEN and not _IDENTIFIER_ALLOWED.search(text):
        return text, True
    return f"{fallback}.{_sha256(text)[:8]}", False


# --- classification -----------------------------------------------------------------------------

def classify(previous: dict | None, *, status: str, digest: str,
             value_digest: str | None = None) -> str:
    """What changed, decided from the durable predecessor row and the fresh reading.

    `digest` is the MATERIAL digest — see `MATERIAL STATE` above. Both digests are taken over
    SAFE stored values, so this compares what the record holds against what the record held.
    Comparing a raw reading against a redacted predecessor would never match, and every sweep
    would report drift forever.

    A first observation is `baseline`. Reporting it as `unchanged` would be a claim about a
    comparison that never happened, and it is the single easiest way for this kind of system to
    look reassuring on day one (issue #82 criterion 7).
    """
    if previous is None:
        return CHANGE_BASELINE
    was_unknown = previous["status"] == STATUS_UNKNOWN
    is_unknown = status == STATUS_UNKNOWN
    if was_unknown and not is_unknown:
        return CHANGE_APPEARED
    if is_unknown and not was_unknown:
        return CHANGE_DISAPPEARED
    if is_unknown and was_unknown:
        # Still unreadable. Nothing was compared, so nothing changed — but it is not healthy
        # either; the severity table keeps it `unknown`.
        return CHANGE_UNCHANGED
    stored = previous.get("material_digest")
    if stored:
        return CHANGE_UNCHANGED if stored == digest else CHANGE_CHANGED
    # A predecessor written before schema v10 has no material digest. Compare it the way it was
    # written rather than against a digest of a different thing — otherwise the upgrade itself
    # would report every scope as changed on the first sweep after it, which is a fact about the
    # migration and not about the host. `value_digest` defaults to `digest` so a caller with one
    # digest (a collector that declares no material state) behaves exactly as before.
    legacy = digest if value_digest is None else value_digest
    return CHANGE_UNCHANGED if previous["value_digest"] == legacy else CHANGE_CHANGED


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


#: Per-scope override of how a CHANGE is judged, where the default is wrong for that scope.
#:
#: This table is for scopes where a MATERIAL change is real but already accounted for elsewhere —
#: not for quietening scopes that report change spuriously. That failure is fixed at the source,
#: by narrowing what the digest is taken over (see `MATERIAL STATE`); an override there would
#: leave the wrong comparison in place and merely stop it speaking.
#:
#: `wp.inventory` — plugin and theme versions change because somebody applied an update, which is
#: routine maintenance rather than an incident. What IS worth attention is not "a version moved"
#: but "something active went missing", which `_DIFFERS` below decides from the values and
#: escalates on its own.
#:
#: `host.capacity` — a material change here is a threshold band moving, and the collector already
#: returns `warn`/`action` when a band is breached. That status dominates severity, so the only
#: change this override can affect is the OTHER direction: a filesystem recovering from `low`
#: back to healthy. Warning an owner because a disk got emptier is not a defensible page.
#:
#: `platform.services` and `logs.signatures` are deliberately absent. A unit's judged verdict
#: changing, or an error signature appearing that was not there yesterday, is exactly the kind of
#: thing a monitoring sweep exists to raise, and neither is implied by the collector's own status.
_SCOPE_CHANGE_SEVERITY: dict[str, dict[str, str]] = {
    "wp.inventory": {CHANGE_CHANGED: STATUS_OK},
    "host.capacity": {CHANGE_CHANGED: STATUS_OK},
}


def _wp_inventory_diff(previous: dict, current: dict) -> tuple[str | None, str]:
    """Turn two inventories into the sentence an owner actually wants, and decide if it matters.

    Escalates only for plugins that were active and no longer are. A plugin vanishing or being
    deactivated is the shape of both a broken update and a compromise; a version moving forward
    is Tuesday.
    """
    def _by_name(value: dict) -> dict[str, dict]:
        return {p.get("name", ""): p for p in value.get("plugins", []) if isinstance(p, dict)}

    prev, cur = _by_name(previous), _by_name(current)
    was_active = {n for n, p in prev.items() if p.get("status") == "active"}
    gone = sorted(n for n in was_active if n not in cur)
    deactivated = sorted(n for n in was_active
                         if n in cur and cur[n].get("status") != "active")
    added = sorted(set(cur) - set(prev))
    upgraded = sorted(n for n in set(prev) & set(cur)
                      if prev[n].get("version") != cur[n].get("version"))

    if gone or deactivated:
        missing = ", ".join(gone + deactivated)
        return STATUS_WARN, (f"active plugin(s) no longer active: {missing} — worth confirming "
                             f"this was intended")
    notes = []
    if upgraded:
        notes.append(f"{len(upgraded)} plugin version(s) changed ({', '.join(upgraded[:5])})")
    if added:
        notes.append(f"{len(added)} new plugin(s)")
    return None, "; ".join(notes) if notes else ""


#: Scope -> (previous_value, current_value) -> (severity override or None, owner-facing note).
_DIFFERS: dict[str, Callable[[dict, dict], tuple[str | None, str]]] = {
    "wp.inventory": _wp_inventory_diff,
}


def describe_change(scope: str, previous: dict | None, current: dict) -> tuple[str | None, str]:
    """What changed within a scope's value, for scopes that have an opinion about it."""
    differ = _DIFFERS.get(scope)
    if differ is None or previous is None:
        return None, ""
    try:
        return differ(previous, current)
    except Exception:  # noqa: BLE001 — a differ bug must not lose the observation
        return None, ""


def severity_for(status: str, change_class: str, *, scope: str | None = None) -> str:
    """The deterministic severity. Same inputs, same answer, every time.

    A collector that reports `warn` or `action` has seen something policy cannot soften — a
    threshold breach is a threshold breach whether or not it also changed. `unknown` dominates
    everything: a source that could not be read, or could not be recorded faithfully, cannot be
    called healthy.
    """
    if status == STATUS_UNKNOWN:
        return STATUS_UNKNOWN
    if status in (STATUS_WARN, STATUS_ACTION):
        return status
    overrides = _SCOPE_CHANGE_SEVERITY.get(scope or "", {})
    if change_class in overrides:
        return overrides[change_class]
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

        # The one boundary where a reading becomes evidence. EVERY collector-originated string
        # crosses it — value, evidence, reason, confidence and the identifiers — because a
        # field's intended purpose is not a security property, and the collectors that will
        # actually carry plugin names, log lines and service output have not been written yet
        # (issue #82; PR #85 review and re-review).
        normalized = prepare_value(result.value, limit=ctx.max_value_bytes)
        # The material state goes through the SAME boundary, because it is stored too and a
        # projection of a value is not automatically safer than the value.
        material = prepare_value(material_of(result), limit=ctx.max_value_bytes)
        scope, scope_ok = safe_identifier(result.scope, fallback="unnamed.scope")
        source, source_ok = safe_identifier(result.source, fallback="unknown.source")
        collector_id, id_ok = safe_identifier(collector.id, fallback="unknown.collector")
        version, version_ok = safe_identifier(getattr(collector, "version", ""), fallback="0")
        identifiers_ok = scope_ok and source_ok and id_ok and version_ok

        status = result.status
        reason = safe_text(result.reason, limit=MAX_REASON_BYTES) or None
        if normalized.oversized or material.oversized:
            status = STATUS_UNKNOWN
            reason = ("this source returned more than can be recorded faithfully, so its state "
                      "is unknown — not healthy")
        elif not identifiers_ok:
            # A collector that cannot name its own scope or source is not one whose reading
            # should be believed, even though the reading is still kept as evidence.
            status = STATUS_UNKNOWN
            reason = ("this collector returned a malformed identifier, so its reading is not "
                      "trusted — the observation is kept, its state is unknown")

        previous = store.latest_observation(profile=ctx.profile, environment=ctx.environment,
                                            scope=scope)
        change_class = classify(previous, status=status, digest=material.digest,
                                value_digest=normalized.digest)
        severity = severity_for(status, change_class, scope=scope)

        # What changed WITHIN the value, for scopes that can say. The note is appended to the
        # owner-facing reason so the page answers "what changed since last time" in words, and
        # a differ may escalate — a plugin that was active and is not is worth more than the
        # informational verdict `wp.inventory` gives ordinary drift.
        if change_class == CHANGE_CHANGED and status != STATUS_UNKNOWN:
            escalation, note = describe_change(
                scope, observation_value(previous) if previous else None, normalized.value)
            if escalation and _ROLLUP_ORDER.index(escalation) < _ROLLUP_ORDER.index(severity):
                severity = escalation
            if note:
                reason = f"{reason}; {note}" if reason else note
                reason = safe_text(reason, limit=MAX_REASON_BYTES)
        severities.append(severity)
        store.record_observation(
            run_id,
            collector_id=collector_id,
            collector_version=version,
            scope=scope,
            source=source,
            profile=ctx.profile,
            environment=ctx.environment,
            captured_at=ctx.now_iso(),
            status=status,
            value_json=normalized.canonical,
            value_digest=normalized.digest,
            # Stored, not merely computed: the row can then show WHAT was compared, so a
            # `changed` verdict is auditable instead of asserted.
            material_json=material.canonical,
            material_digest=material.digest,
            evidence=bound_evidence(result.evidence, limit=ctx.max_evidence_bytes),
            predecessor_id=previous["id"] if previous else None,
            change_class=change_class,
            severity=severity,
            confidence=safe_text(result.confidence, limit=MAX_CONFIDENCE_BYTES) or None,
            reason=reason,
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
