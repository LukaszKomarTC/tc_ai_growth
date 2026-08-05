"""WP-U4d.1 — the deployment TARGET seam (PR #80, first executable increment).

The deployment runner's paths, store, service name and evidence namespace were module constants.
That made the runner unprovable: the only target it could ever address was the production host, so
every claim about its behaviour had to be an argument about code rather than a record of running
it. This module turns those constants into a **resolved target object** so a throwaway target can
be built and driven for real.

A seam like this widens the attack surface if it is reachable from the outside, so the whole point
of this file is *where the override may come from*. Two properties, both enforced at runtime here
rather than promised in prose:

**Only the production target exists unless a CLI gate is open.** `Target` refuses to construct at
all while the gate is closed. `PRODUCTION` is built once, during import of this module, under a
private bootstrap flag that is cleared before the module finishes loading. So there is no way to
end up with a second target — well-formed or malicious — without something having opened the gate
first.

**A process that serves the Console can never open the gate.** `note_http_boundary()` latches the
moment the Console binds a socket or handles a request, and the latch both closes the gate and
makes reopening impossible for the life of the process. The Console therefore cannot be talked
into resolving a different target no matter what a request contains — not because no handler
happens to pass one today, but because the machinery that would accept one is dead in that
process.

Two claims of very different strength, and they must not be run together
------------------------------------------------------------------------
`tc_growth.cli` being the only caller of `open_cli_target_gate()` is a **convention**. This is an
ordinary public function; Python has no capability binding that could make it callable from one
module and not another, so "CLI-only" names the only caller that exists today — it is not caller
identity, and a test can only assert it of the code as written.

The latch is the **enforced** half. It holds against any caller, in any module, written at any
time, because it is a property of the process rather than of who is asking.

What this does **not** claim: it is not a defence against code execution inside the Console
process. Anything that can run arbitrary Python there can already do worse than change a path, and
could in principle call the gate before the first bind. The boundary being proven is the *request*
boundary — form fields, query strings, headers, cookies — and PR #80's harness proves that by
driving a real Console, not by reading this docstring.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

__all__ = [
    "DeployRefused", "Target", "PRODUCTION", "make_disposable_target",
    "open_cli_target_gate", "note_http_boundary", "cli_gate_is_open", "http_boundary_latched",
]

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class DeployRefused(ValueError):
    """A request that policy refuses. Distinct from a defect: refusals are expected and are
    reported to the owner in their own words. Anything unexpected must raise something else, so
    a bug can never be presented as policy (the U4c lesson, carried forward).

    It lives here rather than in `deploy` because the target seam is the first thing that can
    refuse, and `deploy` imports this module rather than the other way round. `deploy.DeployRefused`
    re-exports this exact class, so every existing `except deploy.DeployRefused` still catches it.
    """


# --------------------------------------------------------------------------- the gate
#
# Three module flags, deliberately not one: "the gate is open", "this process has served HTTP",
# and "we are constructing the production singleton". Collapsing them would make the failure modes
# share a state, and the whole reason this file exists is that a shared state is what let the last
# five defects hide.

_BOOTSTRAP = False        # True only while PRODUCTION is being built, below
_CLI_GATE_OPEN = False    # opened by tc_growth.cli for the harness verb, and by nothing else
_HTTP_LATCHED = False     # latched forever once this process binds or serves the Console


def note_http_boundary() -> None:
    """Latch this process as an HTTP server, permanently.

    Called when the Console binds its socket and again on every request it handles. Once latched
    the CLI gate is closed and can never reopen, so a Console process cannot construct a target
    even if some future handler were careless enough to try.

    Idempotent and cheap on purpose — it sits on the per-request path.
    """
    global _HTTP_LATCHED, _CLI_GATE_OPEN
    _HTTP_LATCHED = True
    _CLI_GATE_OPEN = False


def open_cli_target_gate() -> None:
    """Permit non-production targets in THIS process. Called by `tc_growth.cli` and nothing else.

    That "and nothing else" is a convention about the code as written, not an enforced property —
    see the module docstring. What IS enforced is the refusal below: a process that has ever bound
    or served the Console cannot open this gate, whoever calls it. That refusal is what PR #80's
    seam test exercises against a real Console server, rather than asserting that no handler calls
    this function.
    """
    global _CLI_GATE_OPEN
    if _HTTP_LATCHED:
        raise DeployRefused(
            "this process serves the Operations Console over HTTP, so it may not select a "
            "deployment target; disposable targets are built from the command line only")
    _CLI_GATE_OPEN = True


def close_cli_target_gate() -> None:
    """Close the gate again once the harness has built what it needs. Not a security boundary on
    its own — `note_http_boundary` is — but it keeps the window as small as the work requires."""
    global _CLI_GATE_OPEN
    _CLI_GATE_OPEN = False


def cli_gate_is_open() -> bool:
    return _CLI_GATE_OPEN


def http_boundary_latched() -> bool:
    return _HTTP_LATCHED


# --------------------------------------------------------------------------- the target

@dataclass(frozen=True)
class Target:
    """Everything a deployment addresses, in one immutable value.

    Constructing one is itself the privileged act: outside the production singleton it requires an
    open CLI gate. The fields cover exactly what a disposable run needs to be genuinely separate
    from production — its own application tree, its own store, its own backup directory, its own
    service and transient-unit names, and its own evidence namespace so a harness run can never be
    mistaken for a real deployment in the record.
    """

    name: str
    app_dir: str
    releases_dir: str
    backup_dir: str
    db_path: str
    venv: str
    service: str
    unit_prefix: str
    evidence_namespace: str
    port: str
    remote_ref: str = "origin/main"
    disposable: bool = False

    def __post_init__(self) -> None:
        if not (_BOOTSTRAP or _CLI_GATE_OPEN):
            raise DeployRefused(
                "refusing to construct a deployment target: the production target is the only one "
                "that exists unless the command-line gate is open. Nothing reachable from an HTTP "
                "request may select where a deployment writes.")
        if not _BOOTSTRAP and not self.disposable:
            raise DeployRefused(
                "only a disposable target may be constructed; production is a singleton and is "
                "never rebuilt from arguments")
        if not _NAME_RE.match(self.name or ""):
            raise DeployRefused(f"unusable target name: {self.name!r}")
        for field_name in ("app_dir", "releases_dir", "backup_dir", "db_path", "venv"):
            value = getattr(self, field_name)
            if not value or not os.path.isabs(value) or value != os.path.normpath(value):
                raise DeployRefused(
                    f"target {field_name} must be an absolute, normalised path: {value!r}")
        for field_name in ("service", "unit_prefix"):
            if not _NAME_RE.match(getattr(self, field_name) or ""):
                raise DeployRefused(
                    f"target {field_name} must be a plain unit-safe name: "
                    f"{getattr(self, field_name)!r}")
        if not str(self.port).isdigit():
            raise DeployRefused(f"target port must be numeric: {self.port!r}")

    @property
    def allowed_paths(self) -> tuple[str, ...]:
        """The only paths this target may write. `backup_dir` is included because the disposable
        target keeps its backups outside the app tree, and the production target's backups sit
        beside its store."""
        return (self.app_dir, self.releases_dir, self.backup_dir)

    @property
    def venv_python(self) -> str:
        return f"{self.venv}/bin/python"

    @property
    def orchestrator_dir(self) -> str:
        return f"{self.app_dir}/orchestrator"

    def release_dir(self, sha: str) -> str:
        return f"{self.releases_dir}/{sha}"

    def unit_name(self, sha: str) -> str:
        """The transient per-deployment unit (issue #77 Decision 2). Named here so the disposable
        target cannot collide with production's, and so the name is derived from the target rather
        than composed at the call site."""
        return f"{self.unit_prefix}-{sha[:12]}"


_BOOTSTRAP = True
try:
    #: The production host, from internal constants. These are the values the runner has always
    #: used; naming them here is what lets everything else stop being a module constant.
    PRODUCTION = Target(
        name="production",
        app_dir="/opt/tc_ai_growth/app",
        releases_dir="/opt/tc_ai_growth/releases",
        backup_dir="/opt/tc_ai_growth/app/orchestrator/data",
        db_path="/opt/tc_ai_growth/app/orchestrator/data/tc_growth.db",
        venv="/opt/tc_ai_growth/app/orchestrator/.venv",
        service="tc-console",
        unit_prefix="tc-deploy",
        evidence_namespace="production",
        port="8385",
        remote_ref="origin/main",
    )
finally:
    _BOOTSTRAP = False


def make_disposable_target(**fields) -> Target:
    """The only supported way to build a non-production target. Requires the CLI gate.

    A thin wrapper rather than a second implementation: it exists so the harness has one obvious
    call site and so `disposable=True` cannot be forgotten.
    """
    if not _CLI_GATE_OPEN:
        raise DeployRefused(
            "a disposable deployment target may only be built from the command line "
            "(tc_growth.cli deploy-harness); no other caller may open that gate")
    fields.setdefault("disposable", True)
    if not fields.get("disposable"):
        raise DeployRefused("make_disposable_target builds disposable targets only")
    return Target(**fields)


def _reset_for_tests() -> None:
    """Clear the process-local gate state. Test-only, and named so nothing mistakes it for policy.

    It exists because the flags are process-global by design; the seam's real proof runs a Console
    in its own process precisely so that proof does not depend on this function.
    """
    global _CLI_GATE_OPEN, _HTTP_LATCHED
    _CLI_GATE_OPEN = False
    _HTTP_LATCHED = False
