"""WP-U5.3a — what recovery this business is supposed to have, declared as data.

Issue #82 §8.1 is explicit that backup policy must be **data, not magic numbers scattered through
collectors**, and — the harder requirement — that the implementation must make clear which values
are *verified current configuration* and which are *merely proposed defaults*:

    Do not encode remembered values as truth without verification.

That sentence is the design. A policy file that states "off-site backups run daily" reads
identically whether somebody confirmed it this morning or somebody guessed it a year ago, and the
whole point of U5 is that the platform must not present the second as the first. So every value
here carries its **provenance**, and provenance decides what the owner surface is allowed to say.

## Four provenances, and why `owner_attested` is not `observed`

* `OBSERVED`      — the platform saw it itself, this run. The only provenance that earns green.
* `OWNER_ATTESTED`— the owner stated it, on a date, and it is recorded as their statement. It is
                    evidence *about a claim*, not evidence about the world. R3 is exactly this:
                    scheduled Duplicator backups to Google Drive are configured and have been
                    tested, per the owner — and the platform cannot see any of it.
* `PROPOSED`      — a default this codebase invented so the policy has a shape. Not agreed.
* `ABSENT`        — verified NOT to exist. Also a fact, and a more useful one than silence. R3's
                    other half: whole-VPS off-site recovery is not configured.

An `OWNER_ATTESTED` layer never renders healthy. That is not scepticism about the owner; it is the
difference between "somebody told me the smoke alarm works" and "the smoke alarm just beeped when
I pressed the button". §8.3 puts it plainly: *a backup file existing is not equivalent to a proven
restore*. An owner's recollection is one step further from proof than a file.

## Acknowledged gaps do not shout

§7 forbids alert fatigue, and a known, recorded, deliberately-deferred gap that screams `action`
every sweep trains the owner to ignore the page — which is how the *next* gap gets missed. So a
layer may be `acknowledged`, with the reason and the tracking reference recorded. An acknowledged
gap reports `warn` and says it is known. An unacknowledged breach reports `action`.

The acknowledgement is data here, in the repository, reviewable in a diff — not a mute button in
the UI.

## What U5.3a deliberately cannot do

No Plesk credential, no Google Drive credential, no new privilege (issue #82 §12, §13, and the
U5.3a scope decision). Every layer therefore declares what would be needed to *observe* it, and a
layer the platform cannot reach reports `unknown` naming the missing dependency — never zero
backups, never green.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- provenance ---------------------------------------------------------------------------------

#: The platform established this itself, this run.
OBSERVED = "observed"
#: The owner stated it. Recorded as their statement, with the date they said it.
OWNER_ATTESTED = "owner_attested"
#: This codebase's default. Nobody has agreed it.
PROPOSED = "proposed"
#: Verified not to exist. A fact, not a silence.
ABSENT = "absent"

PROVENANCES = (OBSERVED, OWNER_ATTESTED, PROPOSED, ABSENT)

#: The provenances that may contribute to a healthy verdict. Deliberately one item long.
VERIFIABLE = (OBSERVED,)


@dataclass(frozen=True)
class PolicyValue:
    """A policy number and where it came from — inseparable, on purpose.

    Separating them is how "we think the retention is 7 days" becomes "the retention is 7 days"
    somewhere between a config file and a dashboard.
    """

    value: Any
    provenance: str
    note: str = ""
    #: When the owner said it, for OWNER_ATTESTED. An attestation without a date cannot go stale,
    #: and a claim that cannot go stale is one that will still be reassuring in five years.
    as_of: str = ""

    def __post_init__(self) -> None:
        if self.provenance not in PROVENANCES:
            raise ValueError(f"not a policy provenance: {self.provenance}")
        if self.provenance == OWNER_ATTESTED and not self.as_of:
            raise ValueError(
                "an owner attestation must carry the date it was made; an undated claim never "
                "ages, and a claim that never ages is one nobody revisits")

    @property
    def verified(self) -> bool:
        return self.provenance in VERIFIABLE


# --- layers -------------------------------------------------------------------------------------

#: The four things §8.3 says must be distinguished rather than collapsed into one green check.
#: They fail independently and in different ways, and the most dangerous combination — a perfect
#: backup nobody has ever restored — looks identical to full health if they are averaged.
LAYER_APPLICATION = "application"
LAYER_HOST = "host"
LAYER_OFFSITE = "offsite"
LAYER_RESTORE_TEST = "restore_test"

LAYERS = (LAYER_APPLICATION, LAYER_HOST, LAYER_OFFSITE, LAYER_RESTORE_TEST)


@dataclass(frozen=True)
class BackupLayer:
    """One independently-failing component of recoverability."""

    key: str
    #: Owner-facing. "Application backup", not "duplicator_pkg_chain".
    title: str
    #: What recovery this layer actually buys — the sentence that answers "why do I care?"
    protects: str
    #: How the platform WOULD see it, and what it is missing. Empty when it can see it.
    observed_via: str = ""
    missing_dependency: str = ""
    #: Policy numbers. Each carries its own provenance.
    max_age_hours: PolicyValue | None = None
    retention_copies: PolicyValue | None = None
    min_free_gb: PolicyValue | None = None
    #: The layer's declared current state, and where that declaration came from.
    state: PolicyValue | None = None
    #: A known, recorded, deliberately-deferred gap warns rather than screams. See the module
    #: docstring: an alert the owner has already decided about is training, not information.
    acknowledged: bool = False
    acknowledged_reason: str = ""
    tracked_as: str = ""

    def __post_init__(self) -> None:
        if self.key not in LAYERS:
            raise ValueError(f"not a backup layer: {self.key}")
        if self.acknowledged and not (self.acknowledged_reason and self.tracked_as):
            raise ValueError(
                "an acknowledged gap must say why it is accepted and where it is tracked, or it "
                "is not an acknowledgement — it is a silenced alarm")
        if not self.observable and not self.missing_dependency:
            raise ValueError(
                f"layer {self.key} cannot be observed and does not say what is missing; "
                f"'unknown' without a named dependency is not an answer the owner can act on")

    @property
    def observable(self) -> bool:
        """Can the platform see this layer at all, with the access it currently has?"""
        return bool(self.observed_via)


@dataclass(frozen=True)
class TaintedArtifact:
    """A backup that EXISTS and must never be restored.

    Recoverability is not a count of archives. `docs/STANDING-CAUTIONS.md` records a ~19 GB
    server backup from the tobacco-spam compromise, labelled DO_NOT_RESTORE, whose restoration
    would reintroduce the compromise. A Backup Guardian that counted artifacts would score that
    as coverage — and the moment it matters is an incident, when somebody is frightened and
    reaching for the biggest, most recent-looking archive on the box.

    So it is carried in the policy as **negative** coverage, and the collector states it plainly
    on the owner surface rather than leaving it in a document nobody opens mid-incident.
    """

    label: str
    why: str
    recorded: str
    recorded_in: str


@dataclass(frozen=True)
class BackupPolicy:
    """The declared recovery posture for one profile."""

    profile: str
    layers: tuple[BackupLayer, ...]
    #: Archives that exist and must not be treated as recovery. See `TaintedArtifact`.
    tainted: tuple[TaintedArtifact, ...] = ()
    #: Bumped when the MEANING of a layer changes, so evidence is never compared across two
    #: incompatible readings of the same policy — the same discipline as COLLECTOR_SET_VERSION.
    version: str = "u5.3a/1"

    def layer(self, key: str) -> BackupLayer | None:
        for entry in self.layers:
            if entry.key == key:
                return entry
        return None

    @property
    def unverified(self) -> tuple[BackupLayer, ...]:
        """Layers whose declared state nobody has independently established."""
        return tuple(
            entry for entry in self.layers
            if entry.state is not None and not entry.state.verified)


def validate_policy(the_policy: BackupPolicy) -> None:
    """Refuse a policy that claims more than the codebase can back.

    Modelled on `core.actions.validate_registry`, which refuses a registry whose entries disagree
    with the enforcement layer — the same discipline, for the same reason. The rule *"only an
    observed layer may be healthy"* is enforced by `judge()`, but a rule that lives only in the
    function applying it can be undone by an edit to the data it reads. Here a layer claiming
    `OBSERVED` must also say HOW it was observed, so a future author cannot promote a layer to
    green by changing one word in a policy file.

    Raises rather than returning a verdict: a malformed recovery policy is not a degraded
    reading, it is a statement nobody should be shown.
    """
    seen: set[str] = set()
    for entry in the_policy.layers:
        if entry.key in seen:
            raise ValueError(f"backup layer declared twice: {entry.key}")
        seen.add(entry.key)
        if entry.state is None:
            continue
        if entry.state.provenance == OBSERVED and not entry.observable:
            raise ValueError(
                f"layer {entry.key} claims its state was OBSERVED but declares no `observed_via` "
                f"— a policy file cannot promote itself to verified by asserting it")
    missing = [key for key in LAYERS if key not in seen]
    if missing:
        raise ValueError(
            f"backup policy does not cover {', '.join(missing)}; §8.3 requires the components to "
            f"be distinguished, and a layer omitted from the policy is one nobody will notice is "
            f"missing")


# --- the policy as it actually stands ------------------------------------------------------------
#
# Seeded from the real operating setup as recorded on issue #82 (R3 clarification, 2026-08-08).
# Every value below is either owner-attested with that date, verified absent, or a proposed
# default this codebase invented. **None of it is observed**, because U5.3a adds no credential and
# no privilege, and on this host the platform can reach none of these sources: the Plesk dump
# store is root-owned and the Duplicator packages live inside a docroot the service account cannot
# traverse (R8).
#
# That is not a disappointing result. A Backup Guardian whose first honest act is to say "I cannot
# see any of your backups, here is exactly what each one would need" is more useful than one that
# reports green from a config file — and it makes the access question a decision rather than an
# assumption.

DEFAULT_POLICY = BackupPolicy(
    profile="tossa-cycling",
    layers=(
        BackupLayer(
            key=LAYER_APPLICATION,
            title="Application backup",
            protects="restores the WordPress site — content, database, plugins, uploads — after "
                     "a bad update, a corrupted database or a compromise",
            missing_dependency=(
                "Duplicator packages are written inside the site docroot, which the account this "
                "platform runs as cannot traverse (R8). Reading them needs either the WordPress "
                "connector or a narrow fixed read helper — neither exists yet, and both are a "
                "separate reviewed capability"),
            max_age_hours=PolicyValue(
                24 * 7, PROPOSED,
                "a week is this codebase's guess, not an agreed policy; the real schedule has "
                "not been read by the platform"),
            state=PolicyValue(
                "configured and tested", OWNER_ATTESTED,
                note="scheduled Duplicator backups to Google Drive are configured and have been "
                     "tested/confirmed — the owner's statement on issue #82, not a platform "
                     "reading",
                as_of="2026-08-08"),
        ),
        BackupLayer(
            key=LAYER_HOST,
            title="Whole-server backup",
            protects="rebuilds the operating system, Plesk configuration, orchestrator runtime, "
                     "systemd units, service configuration and cron — everything an application "
                     "backup does not contain",
            missing_dependency=(
                "there is nothing to observe: no host-level backup mechanism is configured, so "
                "no artifact, log or schedule exists for the platform to read"),
            state=PolicyValue(
                "not configured", ABSENT,
                "full VPS off-site recovery is not yet configured; recorded on issue #82 as R3. "
                "Narrower than it sounds: docs/STANDING-CAUTIONS.md records that the ORCHESTRATOR "
                "is reconstructible from git `main`, the deploy snapshots under "
                "/var/backups/tc-console/ and the release-worktree model. What has no recovery "
                "path is the rest of the box — the operating system, Plesk configuration, mail, "
                "certificates and cron. Saying 'no host backup' without that distinction would "
                "overstate the gap, and an overstated gap is dismissed as easily as a hidden one"),
            acknowledged=True,
            acknowledged_reason=(
                "the owner knows and has deferred it deliberately; designing and implementing "
                "host-level recovery is its own work, not something to be hurried by a warning "
                "on a dashboard"),
            tracked_as="issue #82 — R3",
        ),
        BackupLayer(
            key=LAYER_OFFSITE,
            title="Off-site copy",
            protects="survives the loss of the server itself — a backup that only exists on the "
                     "machine it protects is not a backup",
            missing_dependency=(
                "verifying the Google Drive copy needs a narrowly-scoped Drive credential "
                "(issue #82 §13), which U5.3a deliberately does not add. U5.3b is gated on that "
                "credential review and on R9"),
            max_age_hours=PolicyValue(
                24 * 7, PROPOSED,
                "proposed to match the application layer; not agreed and not read from Drive"),
            retention_copies=PolicyValue(
                3, PROPOSED,
                "a guess at how many packages should be retained off-site; the real retention "
                "has never been read"),
            state=PolicyValue(
                "believed current", OWNER_ATTESTED, as_of="2026-08-08",
                note="covered by the same owner statement as the application layer; the platform has "
                "never seen the Drive folder. Note the repository disagrees with itself here: "
                "docs/SITE_PROFILE.md still carries 'offsite backups (❓ owner to configure in "
                "Plesk)' from 2026-07-10. The two are not necessarily contradictory — Duplicator "
                "to Drive is not Plesk's own off-site feature — but nobody has reconciled them, "
                "and §15 says a live source outranks a remembered description. Neither of these "
                "is a live source"),
        ),
        BackupLayer(
            key=LAYER_RESTORE_TEST,
            title="Restore test",
            protects="the only thing that proves the others worked — an archive that has never "
                     "been restored is a hypothesis, not a recovery plan",
            missing_dependency=(
                "the project records no restore-test evidence anywhere the platform can read. "
                "Nothing writes it today, so there is no source to point at"),
            max_age_hours=PolicyValue(
                24 * 90, PROPOSED,
                "quarterly is this codebase's proposal for how stale a restore test may be "
                "before recoverability confidence should be treated as degraded"),
            state=PolicyValue(
                "no recorded evidence", ABSENT,
                "the owner reports having tested the Duplicator restore; that statement is "
                "recorded on the application layer. What is absent is any DATED, RECORDED test "
                "the platform can point at — which is what this layer measures"),
            acknowledged=True,
            acknowledged_reason=(
                "recording restore tests is not yet a thing this platform does; until it can, "
                "the honest state is 'no evidence', and warning about it every sweep would "
                "punish the owner for a gap in the platform rather than in their operation"),
            tracked_as="issue #82 §8.2 — restore-test evidence",
        ),
    ),
    tainted=(
        TaintedArtifact(
            label="~19 GB server backup from the tobacco-spam compromise era",
            why="it contains the COMPROMISED site state; restoring it would reintroduce the "
                "compromise. Before any restore decision on this server, the artifact's "
                "label, date and location must be checked in the hosting panel, and anything "
                "from the compromise window treated as tainted until proven otherwise",
            recorded="2026-08-03",
            recorded_in="docs/STANDING-CAUTIONS.md",
        ),
    ),
)


# Checked at import, not merely in a test. `core.actions` validates its registry the same way and
# for the same reason: a policy that claims more than the codebase can back should fail loudly
# where it is defined, not quietly wherever it is first read.
validate_policy(DEFAULT_POLICY)
