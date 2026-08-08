"""What this process actually is — one canonical answer, derived rather than remembered.

WP-U5.2b. The pre-flight for the U5.2 acceptance run turned up two apparently-current service
identities in the repository: `tc-console.service` (the U4 governed execution surface, deployed
from a pinned release worktree by `deploy-console.sh`) and `tc-dashboard.service` (the older
read-only dashboard on a different port). They are two different programs, not two spellings of
one — but the U5 collectors watch the first by name, so an owner whose browser reached the second
would have been shown `platform.services: tc-console.service missing` and an `unknown` journal
while everything was in fact fine.

The reviewer's instruction on issue #82 was not to make the owner compensate for that in Bash:

    Fix the deployment identity once; do not make the owner carry this inconsistency in Bash.

So this module is the single place the platform states its own runtime contract, and everything
that needs a unit name imports it rather than spelling one:

* the collectors' closed command boundary (`_exec.ALLOWED_UNITS`),
* the units `platform.services` judges,
* the journal `logs.signatures` reads,
* the unit `deploy-console.sh` installs,
* the runbooks.

**Identity is read from the running process, never configured.** A constant saying "we are
`tc-console.service`" would be exactly the sort of self-report U5 exists to distrust — it would
keep saying so from a unit called something else. The unit name comes out of the process's own
cgroup, so a mismatch between what we are and what we watch is *visible* rather than assumed
away.

Nothing here needs privilege: `/proc/self/cgroup` is world-readable, and every other field comes
from this process's own configuration.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field

#: The canonical Console unit. One name, used by deployment, monitoring and documentation alike.
#: Chosen as `tc-console.service` because U4/U5 already treat it as the governed runtime identity;
#: the property that matters is that there is exactly one (issue #82, U5.2b review).
CONSOLE_UNIT = "tc-console.service"

#: The project's scheduled units, named once here for the same reason.
WEEKLY_REPORT_TIMER = "tc-weekly-report.timer"
AUTODEPLOY_TIMER = "tc-autodeploy.timer"

#: The units U5 may inspect. This is the closed set the command boundary enforces — it exists to
#: be small, and it is derived from the project's own runtime contract rather than from a pattern
#: that would also match every unit on the box.
PROJECT_UNITS: tuple[str, ...] = (CONSOLE_UNIT, WEEKLY_REPORT_TIMER, AUTODEPLOY_TIMER)

#: TRANSITIONAL. The pre-Console read-only dashboard (`cli dashboard`, loopback 8383), superseded
#: by the Console as the owner surface. It is named here so that "is it still installed?" has an
#: answer in code, and deliberately NOT added to `PROJECT_UNITS`: widening the inspected set to
#: keep a retired surface green would be the capability creep the review warned against.
#:
#: Retirement criteria — all three, then this constant and the unit file are deleted:
#:   1. the Console serves every view the dashboard served (done: Health, Cases, Operations);
#:   2. no runbook, timer or script references it (`autodeploy.sh` restarts it today — see the
#:      note there; it is the dashboard's own deploy path and correct until the unit is gone);
#:   3. the owner confirms the dashboard port is no longer reachable or needed on the host.
LEGACY_DASHBOARD_UNIT = "tc-dashboard.service"

#: Where a collector learns which WordPress belongs to this profile. Named here rather than in
#: the collector because it is now part of the deployed service's governed configuration —
#: `deploy-console.sh` writes it into the unit, so the owner never pastes it before a run.
DOCROOT_ENV = "TC_SITE_DOCROOT"

#: What the docroot pre-flight actually established. Four states, because "set" and "exists" and
#: "this process can use it" are three different claims and only the last is the one `wp.inventory`
#: depends on.
DOCROOT_UNSET = "unset"
DOCROOT_MISSING = "missing"
DOCROOT_INACCESSIBLE = "inaccessible"
DOCROOT_READABLE = "readable"

_CGROUP_UNIT = re.compile(r"/([A-Za-z0-9_.@-]+\.(?:service|scope))")


def probe_docroot(path: str) -> str:
    """Can THIS process actually use this directory the way `wp.inventory` needs to?

    The first version of this asked `os.path.isdir()` and stored the answer in a field called
    `docroot_readable`. That is existence, not readability (PR #88 review): a directory can exist
    while the service user cannot traverse or list it, and the panel would have shown no problem
    while the runbook told the owner it was readable.

    So the access is *exercised* rather than predicted. `os.access` asks the kernel's opinion
    about a uid; opening the directory is the operation itself, which is what wp-cli will do when
    it runs with `cwd` set here. An empty docroot is still readable — we got in, there was
    nothing to see.
    """
    if not path:
        return DOCROOT_UNSET
    # NOT os.path.isdir(): it answers False for "does not exist" AND for "cannot be reached",
    # which are opposite diagnoses with opposite fixes. The first on-host acceptance run proved
    # the difference matters — a docroot behind a 0710 parent was reported as "there is no
    # directory at that path", which is a positive claim about the filesystem that was simply
    # untrue, and would send the reader hunting for a wrong path instead of a permission.
    try:
        st = os.stat(path)
    except PermissionError:
        # The path could not even be examined: something on the way in denies traversal.
        return DOCROOT_INACCESSIBLE
    except OSError:
        return DOCROOT_MISSING
    if not stat.S_ISDIR(st.st_mode):
        return DOCROOT_MISSING
    try:
        with os.scandir(path) as entries:
            next(entries, None)
    except OSError:
        return DOCROOT_INACCESSIBLE
    return DOCROOT_READABLE


def unit_of_this_process(*, cgroup_path: str = "/proc/self/cgroup") -> str | None:
    """The systemd unit this process is running under, or None if that cannot be established.

    None is a real answer — a CLI run, a test, a container without systemd — and is never
    upgraded to a guess. The whole value of this field is that it disagrees out loud when the
    deployed reality differs from the contract.
    """
    try:
        with open(cgroup_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    # Last match wins: the cgroup path nests, and the leaf is the unit we are actually in.
    found = _CGROUP_UNIT.findall(text)
    return found[-1] if found else None


@dataclass(frozen=True)
class RuntimeIdentity:
    """What this Console is, and whether it is configured to inspect anything truthfully.

    Deliberately carries no secret and no token: it is rendered in a browser and its whole job is
    to be shown, so nothing may be in it that could not be.
    """

    profile: str
    environment: str
    unit: str | None
    expected_unit: str
    build_commit: str
    docroot: str
    docroot_state: str
    problems: tuple[str, ...] = field(default=())

    @property
    def unit_matches(self) -> bool:
        """False only when we KNOW we are under a different unit.

        This is a RENDERING question — should the panel say "expected tc-console.service"? — and
        an unknown unit is genuinely not a mismatch, so it does not. Readiness is a different
        question with a different answer; see `unit_proven`.
        """
        return self.unit is None or self.unit == self.expected_unit

    @property
    def unit_proven(self) -> bool:
        """Positively established as the canonical unit — not merely *not disproven*.

        The distinction is the whole point. `unit_matches` was doing double duty as both "not
        contradicted" and "confirmed", so a Console that could not read its own cgroup was
        acceptance-ready while the panel said `not running under systemd` (PR #88 review). The
        module docstring already said an unknown must not be converted into something else, and
        `ready_to_inspect` was converting it into `ready`.
        """
        return self.unit == self.expected_unit

    @property
    def docroot_readable(self) -> bool:
        """Proven, not assumed: this process opened the directory."""
        return self.docroot_state == DOCROOT_READABLE

    @property
    def ready_to_inspect(self) -> bool:
        """Would an inspection right now produce evidence worth ACCEPTING?

        Deliberately stricter than "would it produce honest evidence" — a sweep is always honest,
        and reports `unknown` when it cannot see. This answers the acceptance pre-flight's
        question instead, which needs positive proof rather than absence of contradiction.
        """
        return not self.problems and self.unit_proven


#: What an unresolvable profile or environment is called. Never a silent default: a reading filed
#: under a guessed identity is the cross-identity failure U5 exists to prevent.
UNRESOLVED = "unknown"

#: Single-site mode. `config.active_site()` returns "" when no TC_SITE profile is selected, which
#: is a supported configuration rather than a fault, and the Console has always filed its evidence
#: under this name in that case.
SINGLE_SITE_PROFILE = "default"

#: The environment fallback, kept EXACTLY as the Console has always computed it.
#:
#: `env_kind` already defaults to `staging` in the settings model, so this only applies when it is
#: explicitly blank — and the honest-looking change (fall back to `unknown` instead) would be a
#: silent one: observations are keyed on (profile, environment), so relabelling the environment
#: makes every scope's predecessor invisible and re-baselines the entire history. A normalization
#: increment must not move the identity evidence is filed under. `staging` is also the safe
#: direction to be wrong in — it never overstates an environment as production.
DEFAULT_ENVIRONMENT = "staging"


def resolve_identity() -> tuple[str, str]:
    """The (profile, environment) this process files evidence under.

    One author, for the same reason the unit name has one: the Console page, the inspection sweep
    and this self-check must agree about whose evidence they are handling. Two places computing
    it independently is how a panel ends up reassuring an owner about an identity the collectors
    are not using.

    Never raises — `config.load_env()` raises SystemExit for an unknown site profile, and a
    misconfigured profile is precisely a case this must be able to REPORT rather than die on.
    """
    try:
        from .config import active_site, get_settings

        profile = (active_site() or "").strip() or SINGLE_SITE_PROFILE
        environment = (get_settings().env_kind or "").strip().lower() or DEFAULT_ENVIRONMENT
    except (Exception, SystemExit):
        return UNRESOLVED, UNRESOLVED
    return profile, environment


def describe(*, unit_reader=unit_of_this_process, docroot_probe=probe_docroot) -> RuntimeIdentity:
    """Resolve the running identity from configuration and from the process itself.

    Never raises. A Console that cannot describe itself must still render the page saying so —
    a self-check that takes the surface down when it fails is worse than none.

    `docroot_probe` is injectable because the negative case cannot otherwise be exercised as
    root, which bypasses the permission bits the probe exists to detect.
    """
    profile, environment = resolve_identity()

    docroot = (os.environ.get(DOCROOT_ENV, "") or "").strip()
    try:
        docroot_state = docroot_probe(docroot)
    except OSError:
        docroot_state = DOCROOT_INACCESSIBLE
    unit = unit_reader()

    problems: list[str] = []
    if docroot_state == DOCROOT_UNSET:
        problems.append(
            f"{DOCROOT_ENV} is not set in this service's environment, so WordPress cannot be "
            f"inspected and `wp.inventory` will report `unknown`")
    elif docroot_state == DOCROOT_MISSING:
        problems.append(
            f"{DOCROOT_ENV} is set but there is no directory at that path, so WordPress cannot "
            f"be inspected")
    elif docroot_state == DOCROOT_INACCESSIBLE:
        problems.append(
            f"{DOCROOT_ENV} points at a directory this service cannot open — it exists, but the "
            f"account this Console runs as may not traverse or list it, which is what wp-cli "
            f"needs in order to inspect the site")
    if profile == UNRESOLVED or environment == UNRESOLVED:
        problems.append(
            "this Console cannot state whose environment it is, and evidence that cannot name "
            "its subject must not be recorded")
    if unit is None:
        # NOT the same statement as a mismatch, and not a reason to call the sweep dishonest —
        # but the acceptance pre-flight asks for positive proof that the process serving this
        # page is the unit the collectors watch, and an unestablished unit is not that proof.
        problems.append(
            f"this process cannot establish which systemd unit it is running under, so it cannot "
            f"prove it is the {CONSOLE_UNIT} the collectors watch — the reading is still honest, "
            f"but the identity behind it is unverified")
    elif unit != CONSOLE_UNIT:
        problems.append(
            f"this process is running under {unit}, not {CONSOLE_UNIT}; the collectors watch "
            f"{CONSOLE_UNIT}, so they would report the Console missing while it is in fact "
            f"serving this page")

    return RuntimeIdentity(
        profile=profile, environment=environment, unit=unit, expected_unit=CONSOLE_UNIT,
        build_commit=(os.environ.get("TC_BUILD_COMMIT", "") or "unknown"),
        docroot=docroot, docroot_state=docroot_state, problems=tuple(problems))
