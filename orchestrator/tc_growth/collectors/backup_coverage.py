"""`backup.coverage` — how confident can this business be that it can recover?

Issue #82 §8 sets the question deliberately higher than the one a backup dashboard answers:

    Backup Guardian must answer "How confident are we that we can recover?", not merely
    "Did some backup process run?"

So this collector does not look for green ticks. It evaluates the declared policy
(`backup_policy.py`) layer by layer, and for each one asks a narrower question than "is there a
backup": **what has actually been established, and by whom?**

## The verdict comes from provenance, not from the declaration

A policy file can say "off-site backups run daily" whether that was confirmed this morning or
guessed last year, and §8.1 forbids presenting the second as the first. The rule this collector
enforces is therefore simple and blunt:

* `observed`       — the platform saw it. Only this can be healthy.
* `owner_attested` — the owner said so, on a date. Recorded, dated, credited — and `unknown`,
                     because a statement about backups is not a reading of backups.
* `proposed`       — this codebase's own guess. `unknown`.
* `absent`         — verified missing. `action`, or `warn` when the gap is acknowledged.

The `owner_attested` case is the one worth defending. It is not doubt about the owner: R3 records
that the Duplicator → Drive chain is configured *and has been tested*, which is more than most
small businesses can say. It is that §8.3's distinction — *a backup file existing is not
equivalent to a proven restore* — applies a step earlier too. A remembered success is one further
remove from proof than a file, and a monitoring system whose green light can be produced by
somebody's recollection is a monitoring system that will be green on the day it matters.

## Four layers, never averaged

§8.3 requires the components to be distinguished rather than collapsed. They fail independently
and the most dangerous combination — a perfect backup nobody has ever restored — averages out to
looking fine. So the value carries a verdict per layer and the status is the worst of them, and
the owner-facing sentence names which layer is the reason.

## U5.3a sees nothing, and says so precisely

No Plesk credential, no Drive credential, no new privilege. On this host that means every layer
is currently unobservable — the Plesk dump store is root-owned and the Duplicator packages sit
inside a docroot the service account cannot traverse (R8). Each layer therefore reports the exact
missing dependency rather than a shrug, which turns "we don't know" into a decision somebody can
take.
"""

from __future__ import annotations

from typing import Callable

from .. import backup_policy as policy_mod
from ..backup_policy import (ABSENT, DEFAULT_POLICY, OBSERVED, OWNER_ATTESTED, PROPOSED,
                             BackupLayer, BackupPolicy)
from ..inspection import (STATUS_ACTION, STATUS_OK, STATUS_UNKNOWN, STATUS_WARN,
                          CollectionContext, CollectorResult)

#: What each provenance is allowed to produce. The table is the policy — there is no branch
#: anywhere below that can promote a layer above its provenance's ceiling.
_PROVENANCE_STATUS = {
    OBSERVED: STATUS_OK,
    OWNER_ATTESTED: STATUS_UNKNOWN,
    PROPOSED: STATUS_UNKNOWN,
    ABSENT: STATUS_ACTION,
}

#: Worst-first, matching `inspection._ROLLUP_ORDER`. `unknown` outranks `warn` for the same reason
#: it does there: not knowing whether you can recover is worse than knowing one number is off.
_ORDER = (STATUS_ACTION, STATUS_UNKNOWN, STATUS_WARN, STATUS_OK)


def _worst(statuses: list[str]) -> str:
    for candidate in _ORDER:
        if candidate in statuses:
            return candidate
    return STATUS_UNKNOWN


def judge(layer: BackupLayer) -> tuple[str, str]:
    """One layer's verdict and the sentence explaining it.

    Never consults the declared value itself — only its provenance and whether the platform can
    see the layer at all. A policy file cannot talk its way to green.
    """
    if layer.state is None:
        return STATUS_UNKNOWN, (
            f"no state is declared for {layer.title.lower()}, so nothing is known about it")

    status = _PROVENANCE_STATUS[layer.state.provenance]

    if status == STATUS_ACTION and layer.acknowledged:
        # A gap the owner has already decided about is not news. Warning rather than shouting is
        # what keeps the page worth reading on the day something new appears (§7).
        return STATUS_WARN, (
            f"{layer.title.lower()} does not exist — {layer.state.value}. This is a known gap, "
            f"accepted deliberately and tracked as {layer.tracked_as}")

    if status == STATUS_ACTION:
        return status, (
            f"{layer.title.lower()} does not exist — {layer.state.value} — and this gap is not "
            f"recorded as accepted anywhere")

    if layer.state.provenance == OWNER_ATTESTED:
        return status, (
            f"{layer.title.lower()} is {layer.state.value} according to the owner, stated "
            f"{layer.state.as_of}. The platform has not seen it: {layer.missing_dependency}")

    if layer.state.provenance == PROPOSED:
        return status, (
            f"{layer.title.lower()} rests on a default this codebase proposed rather than "
            f"anything anybody confirmed")

    return status, f"{layer.title.lower()} was observed directly: {layer.state.value}"


def headline(verdicts: dict[str, dict], the_policy: BackupPolicy, tainted=()) -> str:
    """The one sentence §8.3 asks for — naming the weakest component, not averaging them.

    The example given there is the shape to hit: *"Backups are current, but restore confidence is
    incomplete because the last staging restore test is outside policy."* Honest and useful,
    where either a bare red or a bare green would be neither.
    """
    observed = [k for k, v in verdicts.items() if v["provenance"] == OBSERVED]
    attested = [k for k, v in verdicts.items() if v["provenance"] == OWNER_ATTESTED]
    missing = [k for k, v in verdicts.items() if v["provenance"] == ABSENT]

    if not observed:
        parts = [f"the platform cannot currently see any of the {len(the_policy.layers)} backup "
                 f"layers, so recoverability is not verified"]
        if attested:
            titles = ", ".join(sorted(verdicts[k]["title"].lower() for k in attested))
            parts.append(f"{titles} rest on the owner's statement rather than on evidence")
        if missing:
            titles = ", ".join(sorted(verdicts[k]["title"].lower() for k in missing))
            parts.append(f"{titles} do not exist at all")
        return "; ".join(parts) + _tainted_clause(tainted)

    weakest = min(verdicts.values(), key=lambda v: _ORDER.index(v["status"]))
    return (f"{len(observed)} of {len(the_policy.layers)} layers verified; the weakest is "
            f"{weakest['title'].lower()} — {weakest['reason']}") + _tainted_clause(tainted)


def _tainted_clause(tainted) -> str:
    """Said in the headline, not only behind an evidence fold.

    A never-restore archive is the one fact whose cost is paid at the worst possible moment, and
    a warning nobody reads until after the restore is not a warning.
    """
    if not tainted:
        return ""
    return (f". Separately: {len(tainted)} archive(s) on this server are labelled DO NOT RESTORE "
            f"and must never be counted as recovery — see the evidence for what and why")


class BackupCoverageCollector:
    """Reads a declared policy. Reaches no network, no credential store and no privileged path."""

    id = "backup.coverage"
    version = "1"
    scope = "backup.coverage"

    def __init__(self, *, the_policy: BackupPolicy | None = None,
                 now: Callable[[], object] | None = None):
        self._policy = the_policy if the_policy is not None else DEFAULT_POLICY

    def collect(self, ctx: CollectionContext) -> CollectorResult:
        verdicts: dict[str, dict] = {}
        for layer in self._policy.layers:
            status, reason = judge(layer)
            verdicts[layer.key] = {
                "title": layer.title,
                "protects": layer.protects,
                "status": status,
                "reason": reason,
                "provenance": layer.state.provenance if layer.state else "undeclared",
                "as_of": layer.state.as_of if layer.state else "",
                "observable": layer.observable,
                "missing_dependency": layer.missing_dependency,
                "acknowledged": layer.acknowledged,
                "tracked_as": layer.tracked_as,
            }

        overall = _worst([v["status"] for v in verdicts.values()])

        value = {
            "policy_version": self._policy.version,
            "profile": self._policy.profile,
            "layers": verdicts,
            # §9: forecasting must degrade honestly. There is nothing to forecast from — no layer
            # is observable, so there is no retention or growth series, and inventing one would be
            # the "days remaining" fabrication that section exists to forbid.
            "forecast": "not attempted — no backup source is observable, so there is no size or "
                        "retention history to project from",
            # Said in the record rather than only in a docstring: nobody reading this row later
            # should think the platform checked Plesk or Drive and found them healthy.
            "sources_reached": [],
            # Named `external_access`, not `credentials_used`: the U5 boundary masks the value of
            # any key whose NAME claims to hold a credential, and it was quite right to mask this
            # one — the rule cannot afford to reason about whether a particular field is really
            # a secret. The field never held a credential; it held a sentence about not having
            # one, and the honest fix was to stop naming it as though it did.
            "external_access": "none — U5.3a adds no Plesk or Google Drive access",
            # Negative coverage, on the page rather than in a document. The moment this matters is
            # an incident, when somebody is reaching for the biggest recent-looking archive on the
            # box — which is exactly when nobody opens STANDING-CAUTIONS.md.
            "do_not_restore": [
                {"label": t.label, "why": t.why, "recorded": t.recorded,
                 "recorded_in": t.recorded_in}
                for t in self._policy.tainted
            ],
        }

        # The judged verdict per layer, plus the policy version. NOT the prose, the attestation
        # dates or the dependency text: those are stable, but the material is what a CHANGE in
        # them would mean, and what matters is that a layer's verdict moved or the reviewed policy
        # itself changed. A policy edit is a reviewed diff and should be visible on the page.
        material = {
            "policy_version": self._policy.version,
            "layers": {key: {"status": v["status"], "provenance": v["provenance"]}
                       for key, v in verdicts.items()},
            # An archive appearing on — or disappearing from — the never-restore list is a change
            # to what recovery is available, and belongs in the comparison.
            "do_not_restore": sorted(t.label for t in self._policy.tainted),
        }

        return CollectorResult(
            scope=self.scope, status=overall, value=value, source="backup-policy",
            evidence="; ".join(f"{k}={v['status']}/{v['provenance']}"
                               for k, v in sorted(verdicts.items())),
            reason=headline(verdicts, self._policy, self._policy.tainted),
            confidence="high" if overall == STATUS_OK else "none",
            material=material,
            # The policy is a local file and it was read completely — the layers' states are
            # established, even though what they DESCRIBE is not. Those are different claims, and
            # conflating them is the defect U5.2d fixed: this collector genuinely established a
            # material state, and a change to it (a reviewed policy edit, a layer's verdict
            # moving) must be visible rather than swallowed because the health reads `unknown`.
            comparable=True)
