"""Execution Service — the origin-agnostic core of the Operations Console (WP-CONSOLE-MVP).

Defining property: this service **never knows whether a request came from a human click or an
AI recommendation.** It receives an *approved operation* (a registry op id + validated args)
and executes it under the platform's existing guardrails. That single boundary is what lets the
human-button Console and the future AI-trigger path share ONE governed, logged execution engine
instead of two.

It reuses the two authorities that already exist — it invents no new ones:
  * the **Action Registry** (`core.actions`) says what operations exist and how they're bound;
  * the **phase gate** (`core.approval`) says whether a call is permitted right now.

Every execution: resolves the op, enforces phase + approval + environment + arg allowlist
server-side, runs it while emitting **step events**, persists a run record as evidence, and
returns a structured result. No free-form command is ever accepted — the op id must be in the
registry and every arg key must be in that op's allowlist.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .actions import OUTCOME_SEVERITY, Approval, Operation, get_operation
from .approval import ALWAYS_ASK, Phase

# A step-event sink. The Console pushes these onto its SSE stream; tests collect them in a list.
Emit = Callable[["StepEvent"], None]
# ALWAYS_ASK confirmation hook: given the operation + args, return True to permit the call.
Confirm = Callable[[Operation, dict], bool]

_STATUS_START = "start"
_STATUS_OK = "ok"
_STATUS_ERROR = "error"
_STATUS_INFO = "info"


@dataclass(frozen=True)
class StepEvent:
    """One boundary in an operation's execution, streamed as it happens."""

    step: str
    status: str  # start | ok | error | info
    detail: str = ""

    def as_dict(self) -> dict:
        return {"step": self.step, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class OperationPreview:
    """What the operator (or an agent) is shown BEFORE Execute — generated from the registry
    entry, the same source of truth the executor enforces, so preview and execution cannot drift."""

    op_id: str
    name: str
    category: str
    min_phase: int
    environments: tuple[str, ...]
    approval: str
    binding: str          # "cli:<command>" or "tool:<name>"
    writes: bool          # does this operation change external state?
    allowed_args: tuple[str, ...]
    expected_actions: str
    runnable_now: bool    # would the CURRENT phase/env permit it?
    outcomes: tuple[tuple[str, str], ...] = ()  # (outcome, severity) this op can COMPLETE with
    block_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "op_id": self.op_id, "name": self.name, "category": self.category,
            "outcomes": [{"outcome": o, "severity": s} for o, s in self.outcomes],
            "min_phase": self.min_phase, "environments": list(self.environments),
            "approval": self.approval, "binding": self.binding, "writes": self.writes,
            "allowed_args": list(self.allowed_args), "expected_actions": self.expected_actions,
            "runnable_now": self.runnable_now, "block_reason": self.block_reason,
        }


# Result vocabulary — an evidence-centric platform must NOT collapse everything into Unix
# success/failure. A diagnostic that completes and reports findings is a SUCCESSFUL execution
# with a non-clean outcome, not a broken tool. So the model separates three axes:
#   execution_status : did the operation RUN to a defined result?  completed | error | blocked
#   outcome          : the DOMAIN result the op reports            clean | findings | warnings | success | failure
#   severity         : how much operator attention it warrants     ok | attention | warn | error
# The exit-code -> outcome mapping is DATA on the registry operation (Operation.result_policy),
# and the outcome -> severity vocabulary lives with the registry (actions.OUTCOME_SEVERITY), so
# the executor stays generic while the registry describes each op's own semantics.
def interpret_exit(op: Operation, exit_code: int) -> tuple[str, str, str]:
    """Map an exit code to (execution_status, outcome, severity) using the op's result_policy.

    Default policy when the op declares none: exit 0 -> success (clean), anything else -> a real
    execution error. An op with domain-specific codes (e.g. integrity scan: 2 = findings) declares
    them, and those codes become COMPLETED outcomes — not failures. A code outside the policy is a
    genuine execution error (a crash, a timeout, an unexpected state), which IS 'error'.
    """
    policy = dict(op.result_policy) if op.result_policy else {0: "success"}
    if exit_code in policy:
        outcome = policy[exit_code]
        return "completed", outcome, OUTCOME_SEVERITY.get(outcome, "attention")
    return "error", "failure", "error"


@dataclass
class ExecutionResult:
    op_id: str
    execution_status: str             # completed | error | blocked
    outcome: str = ""                 # clean | findings | warnings | success | failure ("" if blocked)
    severity: str = "ok"              # ok | attention | warn | error
    steps: list[StepEvent] = field(default_factory=list)
    output: str = ""
    exit_code: int | None = None
    evidence_ref: str | None = None   # run-ledger reference, once persisted
    duration_s: float = 0.0
    started_at: str = ""
    actor: str = "human"
    block_reason: str = ""            # set when execution_status == "blocked"

    @property
    def completed(self) -> bool:
        """True if the operation ran to a defined result — INCLUDING 'completed with findings'.
        Reliability metrics key off this, so a findings scan counts as a successful execution."""
        return self.execution_status == "completed"

    @property
    def clean(self) -> bool:
        return self.completed and self.severity == "ok"

    def as_dict(self) -> dict:
        return {
            "op_id": self.op_id, "execution_status": self.execution_status,
            "outcome": self.outcome, "severity": self.severity, "exit_code": self.exit_code,
            "steps": [s.as_dict() for s in self.steps], "output": self.output,
            "evidence_ref": self.evidence_ref, "duration_s": self.duration_s,
            "started_at": self.started_at, "actor": self.actor,
            "block_reason": self.block_reason,
        }


class ExecutionBlocked(Exception):
    """A guardrail refused the operation before it ran. Carries a machine-readable reason
    (phase | confirmation | environment | disallowed_arg | unknown_operation | disabled)."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _provenance(op: Operation, environment: str) -> dict:
    """Which code, on which target, produced this evidence — so 'the scan passed' is always
    traceable to a reviewed revision months later. The commit is injected at DEPLOY time via
    TC_BUILD_COMMIT (the deployment package pins it); op-specific provenance like a script's own
    sha256 is emitted by the operation into its output. See docs/TECHNICAL_INSPECTOR.md."""
    from ..config import RELEASE, active_site

    return {
        "repo_commit": os.environ.get("TC_BUILD_COMMIT", "unknown"),
        "release": RELEASE,
        "profile": active_site() or "default",
        "environment": environment,
        "binding": f"tool:{op.tool}" if op.tool else f"cli:{op.command}",
    }


# --- native runners -----------------------------------------------------------------------
# Most operations run through the GENERIC command/tool paths below — a new operation is a
# registry entry, not new executor code. A native runner is an OPT-IN richer path for an
# operation that can report protocol-level step events (e.g. SMTP: connect/starttls/auth/send).
# Signature: (args, emit_step) -> (exit_code, output_summary).

def _run_smtp_test(args: dict, emit: Emit) -> tuple[int, str]:
    from ..report import smtp_test_steps

    def _emit(step: str, status: str, detail: str = "") -> None:
        emit(StepEvent(step=step, status=status, detail=detail))

    ok, summary = smtp_test_steps(emit=_emit)
    return (0 if ok else 1), summary


NATIVE_RUNNERS: dict[str, Callable[[dict, Emit], tuple[int, str]]] = {
    "smtp_test": _run_smtp_test,
}


class Executor:
    """Runs approved operations under the phase gate + Action Registry. Origin-agnostic."""

    def __init__(
        self,
        *,
        phase: Phase,
        environment: str | None = None,
        confirm: Confirm | None = None,
        store_factory: Callable[[], object] | None = None,
        cli_timeout_s: float = 120.0,
    ):
        self.phase = phase
        self._environment = environment  # None => resolve from settings at call time
        self._confirm = confirm
        self._store_factory = store_factory
        self._cli_timeout_s = cli_timeout_s

    # -- introspection --------------------------------------------------------

    def environment(self) -> str:
        if self._environment is not None:
            return self._environment
        from ..config import get_settings  # lazy: core stays import-cycle-free

        return (get_settings().env_kind or "staging").strip().lower()

    def preview(self, op_id: str, args: dict | None = None) -> OperationPreview:
        """Build the pre-execution preview. Never runs anything."""
        op = get_operation(op_id)  # raises KeyError on unknown id
        args = args or {}
        writes = op.min_phase > Phase.READ_ONLY
        binding = f"tool:{op.tool}" if op.tool else f"cli:{op.command}"
        reason = ""
        try:
            self._check_guards(op, args, dry_run=True)
            runnable = op.enabled
            if not op.enabled:
                reason = "operation is disabled"
        except ExecutionBlocked as blk:
            runnable = False
            reason = blk.detail
        # Possible COMPLETED outcomes (from the result policy) — so the operator knows, before
        # clicking, that e.g. this scan can come back "findings" and that is a valid result.
        policy = op.result_policy or ((0, "success"),)
        outcomes = tuple((outcome, OUTCOME_SEVERITY.get(outcome, "attention"))
                         for _code, outcome in policy)
        return OperationPreview(
            op_id=op.id, name=op.name, category=op.category.value,
            min_phase=int(op.min_phase), environments=op.environments,
            approval=op.approval.value, binding=binding, writes=writes,
            allowed_args=op.allowed_args,
            expected_actions=op.verification_description,
            runnable_now=runnable, outcomes=outcomes, block_reason=reason,
        )

    # -- execution ------------------------------------------------------------

    def execute(
        self,
        op_id: str,
        args: dict | None = None,
        *,
        emit: Emit | None = None,
        actor: str = "human",
    ) -> ExecutionResult:
        """Execute an approved operation. `actor` is recorded for the audit trail ONLY — it never
        changes what is permitted (origin-agnostic). Emits StepEvents to `emit` as it runs."""
        args = args or {}
        steps: list[StepEvent] = []

        def _emit(ev: StepEvent) -> None:
            steps.append(ev)
            if emit is not None:
                emit(ev)

        started_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        t0 = time.perf_counter()

        try:
            op = get_operation(op_id)
        except KeyError:
            ev = StepEvent("resolve", _STATUS_ERROR, f"unknown operation: {op_id!r}")
            _emit(ev)
            return ExecutionResult(op_id=op_id, execution_status="blocked", severity="error",
                                   steps=steps, block_reason="unknown_operation",
                                   started_at=started_at, actor=actor, output=ev.detail)

        # Guardrails first — nothing runs until phase, approval, environment and args all clear.
        try:
            self._check_guards(op, args, dry_run=False)
        except ExecutionBlocked as blk:
            _emit(StepEvent("guard", _STATUS_ERROR, blk.detail))
            return ExecutionResult(op_id=op.id, execution_status="blocked", severity="error",
                                   steps=steps, block_reason=blk.reason, started_at=started_at,
                                   actor=actor, output=blk.detail)

        _emit(StepEvent("start", _STATUS_INFO, f"{op.name} ({actor}) on {self.environment()}"))

        try:
            exit_code, output = self._run(op, args, _emit)
        except Exception as exc:  # noqa: BLE001 - a runner blowing up must still produce a result, not a 500
            _emit(StepEvent("error", _STATUS_ERROR, f"{type(exc).__name__}: {exc}"))
            exit_code, output = 1, f"{type(exc).__name__}: {exc}"

        # Interpret the exit code through the op's own result policy — findings != failure.
        execution_status, outcome, severity = interpret_exit(op, exit_code)
        duration = round(time.perf_counter() - t0, 3)
        result = ExecutionResult(
            op_id=op.id, execution_status=execution_status, outcome=outcome, severity=severity,
            steps=steps, output=output, exit_code=exit_code,
            duration_s=duration, started_at=started_at, actor=actor,
        )
        result.evidence_ref = self._persist(op, result)
        return result

    # -- guards ---------------------------------------------------------------

    def _check_guards(self, op: Operation, args: dict, *, dry_run: bool) -> None:
        """Enforce, in order: enabled, arg allowlist, environment, phase (+ write cap), approval.
        Raises ExecutionBlocked with a machine reason. `dry_run` skips the confirmation prompt
        (preview must not pop a human dialog) but still reports that confirmation WILL be needed."""
        if not op.enabled:
            raise ExecutionBlocked("disabled", f"operation '{op.id}' is disabled")

        # Arg allowlist — no free-form input; the client is never trusted.
        for key in args:
            if key not in op.allowed_args:
                raise ExecutionBlocked(
                    "disallowed_arg",
                    f"argument '{key}' is not permitted for '{op.id}' "
                    f"(allowed: {', '.join(op.allowed_args) or 'none'})",
                )

        # Environment — the op must be allowed to target the current environment.
        env = self.environment()
        if env not in op.environments:
            raise ExecutionBlocked(
                "environment",
                f"'{op.id}' may target {list(op.environments)}, not '{env}'",
            )

        # Phase gate — mirrors core.approval, covering both tool- and command-bound ops.
        self._check_phase(op)

        # Approval — ALWAYS_ASK needs an explicit per-call human confirmation.
        is_always_ask = op.approval is Approval.ALWAYS_ASK or (op.tool in ALWAYS_ASK)
        if is_always_ask and not dry_run and (self._confirm is None or not self._confirm(op, args)):
            raise ExecutionBlocked(
                "confirmation",
                f"'{op.id}' requires explicit human confirmation, which was not given",
            )

    def _check_phase(self, op: Operation) -> None:
        """Phase + profile-write-cap check.

        For tool-bound ops we defer to the single choke point `is_tool_allowed` (which also
        applies the write cap). For command/native ops there is no tool name, so we apply the
        equivalent rule directly: current phase must reach the op's min_phase, and any
        above-READ_ONLY op additionally requires writes to be enabled on the profile.
        """
        if op.tool is not None:
            from .approval import is_tool_allowed

            if not is_tool_allowed(op.tool, self.phase):
                raise ExecutionBlocked(
                    "phase",
                    f"tool '{op.tool}' for '{op.id}' is not permitted in phase {int(self.phase)} "
                    "(phase too low or profile write cap active)",
                )
            return

        if self.phase < op.min_phase:
            raise ExecutionBlocked(
                "phase",
                f"'{op.id}' needs phase >= {int(op.min_phase)}; current phase is {int(self.phase)}",
            )
        if op.min_phase > Phase.READ_ONLY:
            from ..config import writes_allowed

            if not writes_allowed():
                raise ExecutionBlocked(
                    "phase",
                    f"'{op.id}' writes, but the active profile has writes disabled (write cap)",
                )

    # -- runners --------------------------------------------------------------

    def _run(self, op: Operation, args: dict, emit: Emit) -> tuple[int, str]:
        runner = NATIVE_RUNNERS.get(op.id)
        if runner is not None:
            return runner(args, emit)
        if op.command is not None:
            return self._run_command(op, args, emit)
        if op.tool is not None:
            return self._run_tool(op, args, emit)
        # validate_registry guarantees a binding, but be explicit rather than silently no-op.
        raise ExecutionBlocked("unbound", f"'{op.id}' has neither a native runner, command, nor tool")

    def _run_command(self, op: Operation, args: dict, emit: Emit) -> tuple[int, str]:
        """Run a registry CLI op as a governed subprocess, streaming stdout lines as step events.

        The command comes from the registry (never from the caller) and is passed as an argv
        LIST — no shell, no string interpolation, so caller input can't inject a command.
        """
        argv = [sys.executable, "-m", "tc_growth.cli", op.command]
        emit(StepEvent("spawn", _STATUS_START, " ".join(argv[2:])))
        lines: list[str] = []
        try:
            proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except OSError as exc:
            emit(StepEvent("spawn", _STATUS_ERROR, str(exc)))
            return 1, str(exc)

        # Per-operation budget (registry F1) beats the generic executor default — a legitimately
        # long-running op declares its own timeout instead of squeezing under one global cap.
        timeout_s = op.timeout_s or self._cli_timeout_s
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\n")
                if line:
                    lines.append(line)
                    emit(StepEvent("output", _STATUS_INFO, line))
            code = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            emit(StepEvent("timeout", _STATUS_ERROR, f"exceeded {timeout_s}s"))
            return 124, "\n".join(lines) + "\n[timed out]"

        # Mark the exit step by the op's INTERPRETED severity, not raw code!=0 — for a scanner,
        # exit 2 (findings) is not an error step, it's an attention result.
        _status, outcome, severity = interpret_exit(op, code)
        mark = _STATUS_OK if severity == "ok" else _STATUS_ERROR if severity == "error" else _STATUS_INFO
        emit(StepEvent("exit", mark, f"exit {code} — {outcome}"))
        return code, "\n".join(lines)

    def _run_tool(self, op: Operation, args: dict, emit: Emit) -> tuple[int, str]:
        """Dispatch a registry TOOL op through the existing tool registry (single step)."""
        from ..tools.load import load_all

        emit(StepEvent("dispatch", _STATUS_START, op.tool or ""))
        payload = load_all().dispatch(op.tool, args)
        ok = bool(payload.get("ok"))
        emit(StepEvent("dispatch", _STATUS_OK if ok else _STATUS_ERROR,
                       "ok" if ok else str(payload.get("error", "failed"))))
        return (0 if ok else 1), json.dumps(payload, default=str)[:20000]

    # -- evidence -------------------------------------------------------------

    def _persist(self, op: Operation, result: ExecutionResult) -> str | None:
        """Best-effort run-ledger record. A persistence failure must NEVER break the operation
        (mirrors report.persist_run) — evidence is important, but losing it can't fail the run."""
        try:
            store = self._store_factory() if self._store_factory else _default_store()
            if store is None:
                return None
            detail = json.dumps({
                "actor": result.actor,
                "environment": self.environment(),
                "provenance": _provenance(op, self.environment()),
                "execution_status": result.execution_status,
                "outcome": result.outcome,
                "severity": result.severity,
                "exit_code": result.exit_code,
                "steps": [s.as_dict() for s in result.steps],
                "output": result.output[:8000],
            }, default=str)
            run_id = store.log_run(
                # Ledger status is the EXECUTION status (completed | error | blocked), never a
                # domain outcome — so reliability queries treat a findings scan as a completed
                # run, not a broken tool. Outcome/severity live in detail for richer queries.
                kind=f"op:{op.id}",
                status=result.execution_status,
                duration_s=result.duration_s,
                summary=(result.output.splitlines()[0][:200] if result.output else op.name),
                detail=detail,
                started_at=result.started_at,
            )
            return f"run#{run_id}"
        except Exception as exc:  # noqa: BLE001 — evidence logging must never break execution
            print(f"[execution not logged: {exc}]")
            return None


def _default_store():
    try:
        from ..store import open_store

        return open_store()
    except Exception:  # noqa: BLE001 — no store configured is fine; evidence just isn't persisted
        return None
