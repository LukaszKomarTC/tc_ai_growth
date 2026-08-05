"""Action Registry — named operations as declarative data (Evidence Platform spec §5a).

The catalogue of operations that GENUINELY exist in this platform: what they are, what
phase and environment they require, what approval class governs them, and which code
layers actually enforce those constraints. Definitions are code (versioned by git);
executions become evidence rows only when the 1.1 execution ledger is built (spec §5b).

Two disciplines, both test-enforced:
- Entries describe reality, not roadmap intent: every tool-bound entry must agree with
  the enforcement layer (TOOL_MIN_PHASE / ALWAYS_ASK) and name a registered tool.
- Documentation is not enforcement: `rollback_description` / `verification_description`
  are prose for humans; only `enforced_by` names the code that actually refuses a call.
  A field graduates to `*_handler` ONLY when a machine-executed handler exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .approval import ALWAYS_ASK, TOOL_MIN_PHASE, Phase

# Outcome vocabulary an operation's result_policy may map exit codes to, with the operator
# attention each implies. Pure data — the Execution Service reads this to interpret an exit code
# without hard-coding Unix success/failure. Keeping it beside the registry keeps "how an op's
# outputs are interpreted" in one governed place. severity: ok < warnings < attention < error.
OUTCOME_SEVERITY: dict[str, str] = {
    "success": "ok",       # exit ran, nothing to report (default for exit 0)
    "clean": "ok",         # a diagnostic ran and found nothing
    "findings": "attention",  # a diagnostic COMPLETED and found something — NOT a failure
    "warnings": "warn",    # completed with non-fatal warnings
    "failure": "error",    # the operation could not complete
}


class Category(str, Enum):
    ANALYSIS = "analysis"          # read + reason + report
    INTELLIGENCE = "intelligence"  # snapshot/query the platform's own evidence stores
    DIAGNOSTICS = "diagnostics"    # operator-facing health/inspection checks
    DRAFTING = "drafting"          # produce reviewable artifacts, never live changes
    EXECUTION = "execution"        # change external state (always human-confirmed)
    PLATFORM = "platform"          # change THIS platform's own installation (never the site)


class Approval(str, Enum):
    NONE = "none"                            # read-only; no human step required
    HUMAN_REVIEW_OF_OUTPUT = "review_output" # artifact reviewed/approved by a human after creation
    ALWAYS_ASK = "always_ask"                # explicit per-call human confirmation (approval.ALWAYS_ASK)


@dataclass(frozen=True)
class Operation:
    id: str
    name: str
    category: Category
    min_phase: Phase
    environments: tuple[str, ...]      # environments this operation may TARGET
    approval: Approval
    tool: str | None = None            # registered tool this operation is bound to
    command: str | None = None         # CLI entrypoint (python -m tc_growth.cli <command>)
    allowed_args: tuple[str, ...] = () # arg keys the Execution Service will accept (allowlist;
                                       # anything else is refused server-side — no free-form input)
    result_policy: tuple[tuple[int, str], ...] = ()  # exit_code -> outcome label. Lets the
                                       # executor stay generic while the registry describes THIS
                                       # op's result semantics (e.g. integrity scan: 2 = findings,
                                       # a COMPLETED outcome, not a failure). Empty => default
                                       # policy (0 = success, anything else = execution error).
    timeout_s: float | None = None     # per-operation execution timeout. VPS acceptance F1: the
                                       # integrity scan runs ~100s against the executor's generic
                                       # 120s cap — too thin a margin. An op that legitimately
                                       # runs long declares its own budget; None => executor default.
    # What an operation can reach. The staging-only cap on write-capable operations exists
    # because production WORDPRESS writes are capped — it is a statement about the customer's
    # site, not about this platform's own host. A deployment writes the platform and provably
    # never the site, so it declares target_surface="platform" and is held to the U4d boundary
    # (fixed allowlists, exact SHA, no shell) instead of to a rule that does not apply to it.
    target_surface: str = "site"
    preconditions: tuple[str, ...] = ()
    enforced_by: tuple[str, ...] = ()  # code layers that actually refuse a bad call
    rollback_description: str = ""     # prose — NOT machine-enforced (see module docstring)
    verification_description: str = "" # prose — NOT machine-enforced
    enabled: bool = True


_READ_ROLLBACK = "not required — read-only; no external state is changed"
_GATE = "phase gate (core.approval.is_tool_allowed)"

OPERATIONS: tuple[Operation, ...] = (
    Operation(
        id="smtp_test",
        name="SMTP delivery test",
        category=Category.DIAGNOSTICS,
        min_phase=Phase.READ_ONLY,
        environments=("staging", "production"),
        approval=Approval.NONE,
        command="smtp-test",
        allowed_args=(),  # takes no arguments — the mail config is the input
        preconditions=("TC_SMTP_* and TC_REPORT_RECIPIENT configured",),
        # Sends one test message via the configured relay; changes nothing on the site. The
        # Execution Service runs it with per-step instrumentation (connect/starttls/auth/send).
        enforced_by=(_GATE, "reads mail config only — no site or external state is written"),
        rollback_description=_READ_ROLLBACK,
        verification_description="each protocol step (connect/starttls/auth/send) is reported as a "
                                 "streamed step event; a test message lands in the recipient inbox",
    ),
    Operation(
        id="redeliver_latest_report",
        name="Re-send latest weekly report",
        category=Category.DIAGNOSTICS,
        min_phase=Phase.READ_ONLY,
        environments=("staging", "production"),
        approval=Approval.NONE,
        command="report-redeliver-latest",
        allowed_args=(),  # 'latest' IS the operation — no argument surface (U3b)
        # Re-sends the STORED immutable artifact byte-identically (U3a chain): no agent run, no
        # tokens, no new artifact row; delivery attempt counted on the one row, marked by id.
        result_policy=((0, "success"), (1, "failure")),
        timeout_s=60.0,
        preconditions=("at least one weekly-report artifact stored (schema v3)",
                       "TC_SMTP_* and TC_REPORT_RECIPIENT configured"),
        enforced_by=(_GATE, "reads the artifact store + mail config; site state untouched"),
        rollback_description="not required — re-sends an existing immutable artifact; "
                             "worst case is a duplicate email",
        verification_description="delivery attempt recorded on the artifact row "
                                 "(report-artifact <id> shows status + attempt count)",
    ),
    Operation(
        id="run_integrity_scan",
        name="Run integrity scan (Technical Inspector)",
        category=Category.DIAGNOSTICS,
        min_phase=Phase.READ_ONLY,
        environments=("staging", "production"),
        approval=Approval.NONE,
        command="integrity-scan",
        allowed_args=(),
        # The inspector exits 0 when clean and 2 when it finds anomalies. Exit 2 is a COMPLETED
        # scan with findings (attention) — NOT a failure. Any other code is a real execution error.
        result_policy=((0, "clean"), (2, "findings")),
        # VPS acceptance measured ~98-100s per scan (core + 24 plugin checksums); 300s gives the
        # slow-day headroom the generic 120s default lacks (F1).
        timeout_s=300.0,
        preconditions=("inspector script deployed (scripts/wp-integrity-scan.sh)",
                       "wp-cli available on the host"),
        # Runs through the Execution Service's GENERIC command path — no operation-specific
        # executor code. Read-only: it inspects and reports, never modifies the site.
        enforced_by=(_GATE, "read-only scan — inspects and reports, never writes"),
        rollback_description=_READ_ROLLBACK,
        verification_description="each check (core/plugin checksums, shell-name patterns, "
                                 "PHP-in-uploads/mu-plugins, kit fingerprints, admin-set drift, "
                                 "wp-config markers) streams as output; exit 2 = anomalies found "
                                 "and logged; the run is recorded to the ledger as evidence",
    ),
    Operation(
        id="deploy_release",
        name="Deploy a reviewed release (WP-U4d)",
        category=Category.PLATFORM,
        min_phase=Phase.CONTROLLED_EXECUTION,
        environments=("staging", "production"),
        approval=Approval.ALWAYS_ASK,
        command="deploy-run",
        # The ONLY accepted input is the id of a deploy run the owner already planned and
        # reviewed. The commit itself is not an argument to this operation — it lives on the
        # authorized row, where the store's triggers make it immutable. There is therefore no
        # request shape that can deploy an unreviewed commit.
        allowed_args=("run_id",),
        result_policy=((0, "success"), (1, "failure")),
        timeout_s=3600.0,
        target_surface="platform",
        preconditions=("a deploy run in status 'planned' whose plan the owner has reviewed",
                       "the target is an exact 40-hex commit that is an ancestor of origin/main",
                       "a VERIFIED backup of the evidence store (step 2 refuses to continue "
                       "without one)"),
        enforced_by=(_GATE,
                     "tc_growth.deploy.validate_sha — exact 40-hex only; refs and short SHAs "
                     "refused",
                     "tc_growth.deploy.EXECUTORS — closed dispatch table of fixed argv builders; "
                     "no shell, no interpolation, no caller-supplied words",
                     "tc_growth.deploy._assert_allowed_path / _assert_allowed_service — closed "
                     "path and service allowlists, normalized before comparison",
                     "store triggers trg_deploy_runs_target_immutable / _terminal — the reviewed "
                     "target cannot be edited and a finished run cannot be resurrected",
                     "never invokes the WordPress connector: no site write path exists here"),
        rollback_description="scripts/deploy-console.sh --rollback restores the previous unit, "
                             "inspector and sudoers state; the evidence store is recovered from "
                             "the verified backup taken before migration; a converged checkout "
                             "is returned by deploying the previous SHA. Irreversible steps "
                             "(converge, migrate, release) are listed in the plan BEFORE "
                             "authorization, never discovered during execution.",
        verification_description="each step is written to deploy_steps as append-only evidence "
                                 "by the DETACHED runner, so the record survives the Console "
                                 "restart the deployment itself performs; the run ends in an "
                                 "explicit terminal status (succeeded/failed/refused) and the "
                                 "health step confirms HTTP 200 plus the running service pinning "
                                 "the target SHA",
        # DISABLED until its host prerequisites exist (the fixed deployment sudoers surface and
        # KillMode=process on tc-console.service) and the staging/disposable proof has run. The
        # registry describes CURRENT AUTHORITY: a capability that has not been proven is present
        # here to be reviewed, not offered to be clicked. #77 requires the proof before first use.
        enabled=False,
    ),
)


class RegistryError(ValueError):
    """The action registry contradicts itself or the enforcement layer."""


def validate_registry(ops: tuple[Operation, ...] = OPERATIONS) -> None:
    """Fail loudly if the catalogue drifts from reality. Called by tests and list-operations.

    Checks BOTH internal coherence (unique ids, sane fields) and agreement with the
    enforcement layer — a registry entry whose phase/approval contradicts core.approval
    is a lie about the platform and must not survive CI.
    """
    seen: set[str] = set()
    for op in ops:
        if op.id in seen:
            raise RegistryError(f"duplicate operation id: {op.id}")
        seen.add(op.id)
        if not op.id.replace("_", "").isalnum() or op.id != op.id.lower():
            raise RegistryError(f"operation id must be lower_snake_case: {op.id}")
        if op.tool is None and op.command is None:
            raise RegistryError(f"{op.id}: not callable — needs a tool or command binding")
        # result_policy must describe outcomes the platform understands, with no duplicate codes.
        seen_codes: set[int] = set()
        for code, outcome in op.result_policy:
            if not isinstance(code, int):
                raise RegistryError(f"{op.id}: result_policy exit code must be int, got {code!r}")
            if code in seen_codes:
                raise RegistryError(f"{op.id}: result_policy has duplicate exit code {code}")
            seen_codes.add(code)
            if outcome not in OUTCOME_SEVERITY:
                raise RegistryError(f"{op.id}: result_policy outcome {outcome!r} is not one of "
                                    f"{sorted(OUTCOME_SEVERITY)}")
        if op.timeout_s is not None and not (isinstance(op.timeout_s, (int, float)) and op.timeout_s > 0):
            raise RegistryError(f"{op.id}: timeout_s must be a positive number, got {op.timeout_s!r}")
        if not op.verification_description:
            raise RegistryError(f"{op.id}: verification_description is required")
        if op.target_surface not in ("site", "platform"):
            raise RegistryError(f"{op.id}: target_surface must be 'site' or 'platform', "
                                f"got {op.target_surface!r}")
        if op.target_surface == "platform" and op.category is not Category.PLATFORM:
            raise RegistryError(f"{op.id}: only PLATFORM-category operations may declare "
                                "target_surface='platform'")
        if op.min_phase > Phase.READ_ONLY:
            if not op.rollback_description:
                raise RegistryError(f"{op.id}: write-capable operations require a "
                                    "rollback_description")
            if op.target_surface == "site" and op.environments != ("staging",):
                raise RegistryError(f"{op.id}: write-capable operations may only target "
                                    "staging (profile write cap is the production reality)")
        if op.tool is not None:
            gate_phase = TOOL_MIN_PHASE.get(op.tool)
            if gate_phase is None:
                raise RegistryError(f"{op.id}: tool '{op.tool}' is not in TOOL_MIN_PHASE — "
                                    "entry describes a tool the gate does not know")
            if gate_phase != op.min_phase:
                raise RegistryError(f"{op.id}: min_phase {op.min_phase!r} disagrees with "
                                    f"TOOL_MIN_PHASE[{op.tool!r}] = {gate_phase!r}")
            if (op.approval is Approval.ALWAYS_ASK) != (op.tool in ALWAYS_ASK):
                raise RegistryError(f"{op.id}: approval class disagrees with ALWAYS_ASK "
                                    f"membership of tool '{op.tool}'")


def get_operation(op_id: str) -> Operation:
    for op in OPERATIONS:
        if op.id == op_id:
            return op
    raise KeyError(op_id)
