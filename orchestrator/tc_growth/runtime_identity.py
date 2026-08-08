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

_CGROUP_UNIT = re.compile(r"/([A-Za-z0-9_.@-]+\.(?:service|scope))")


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
    docroot_readable: bool
    problems: tuple[str, ...] = field(default=())

    @property
    def unit_matches(self) -> bool:
        """False only when we KNOW we are under a different unit — an unknown unit is not a
        mismatch, it is an unknown, and this module does not convert one into the other."""
        return self.unit is None or self.unit == self.expected_unit

    @property
    def ready_to_inspect(self) -> bool:
        """Would an inspection right now produce evidence worth accepting?

        This is what makes a missing docroot obvious BEFORE a sweep rather than after it, which
        was the reviewer's requirement: an acceptance run spent discovering an unset variable is
        an acceptance run wasted.
        """
        return not self.problems


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


def describe(*, unit_reader=unit_of_this_process) -> RuntimeIdentity:
    """Resolve the running identity from configuration and from the process itself.

    Never raises. A Console that cannot describe itself must still render the page saying so —
    a self-check that takes the surface down when it fails is worse than none.
    """
    profile, environment = resolve_identity()

    docroot = (os.environ.get(DOCROOT_ENV, "") or "").strip()
    docroot_readable = bool(docroot) and os.path.isdir(docroot)
    unit = unit_reader()

    problems: list[str] = []
    if not docroot:
        problems.append(
            f"{DOCROOT_ENV} is not set in this service's environment, so WordPress cannot be "
            f"inspected and `wp.inventory` will report `unknown`")
    elif not docroot_readable:
        problems.append(
            f"{DOCROOT_ENV} is set but is not a readable directory, so WordPress cannot be "
            f"inspected")
    if profile == UNRESOLVED or environment == UNRESOLVED:
        problems.append(
            "this Console cannot state whose environment it is, and evidence that cannot name "
            "its subject must not be recorded")
    if unit is not None and unit != CONSOLE_UNIT:
        problems.append(
            f"this process is running under {unit}, not {CONSOLE_UNIT}; the collectors watch "
            f"{CONSOLE_UNIT}, so they would report the Console missing while it is in fact "
            f"serving this page")

    return RuntimeIdentity(
        profile=profile, environment=environment, unit=unit, expected_unit=CONSOLE_UNIT,
        build_commit=(os.environ.get("TC_BUILD_COMMIT", "") or "unknown"),
        docroot=docroot, docroot_readable=docroot_readable, problems=tuple(problems))
