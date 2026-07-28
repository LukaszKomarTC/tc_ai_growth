"""Execution Service tests (WP-CONSOLE-MVP slice 1).

The executor is the platform's new privileged surface, so its guardrails are the thing under
test: it must refuse an op above the current phase, refuse a disallowed argument, refuse an
ALWAYS_ASK op without confirmation, and — when everything clears — run the op, stream step
events, and hand back a structured, persisted result. SMTP Test is the first vertical slice.
"""

from __future__ import annotations

from tc_growth.core.approval import Phase
from tc_growth.core.executor import (
    ExecutionResult,
    Executor,
    OperationPreview,
    StepEvent,
)


class _FakeStore:
    """Captures log_run calls so persistence is asserted without touching a real DB."""

    def __init__(self):
        self.calls: list[dict] = []

    def log_run(self, **kw) -> int:
        self.calls.append(kw)
        return 4242


def _exec(**kw) -> Executor:
    # Default to a store that persists nowhere unless a test wants to inspect evidence.
    kw.setdefault("store_factory", lambda: None)
    kw.setdefault("environment", "staging")
    kw.setdefault("phase", Phase.READ_ONLY)
    return Executor(**kw)


# -- preview -------------------------------------------------------------------


def test_preview_is_built_from_the_registry_entry():
    prev = _exec().preview("smtp_test")
    assert isinstance(prev, OperationPreview)
    assert prev.op_id == "smtp_test"
    assert prev.binding == "cli:smtp-test"
    assert prev.writes is False          # READ_ONLY op changes nothing
    assert prev.runnable_now is True     # READ_ONLY, staging in its environments
    assert "staging" in prev.environments


def test_preview_reports_a_write_op_as_not_runnable_in_read_only_phase():
    prev = _exec().preview("publish_seo_draft")
    assert prev.writes is True
    assert prev.runnable_now is False
    assert prev.block_reason  # explains WHY before the operator clicks


def test_preview_does_not_prompt_for_confirmation():
    # dry_run must never invoke the confirm hook — a preview that popped a dialog would be wrong.
    called = {"n": 0}

    def confirm(op, args):
        called["n"] += 1
        return True

    _exec(phase=Phase.CONTROLLED_EXECUTION, confirm=confirm).preview("publish_seo_draft")
    assert called["n"] == 0


# -- guardrails ----------------------------------------------------------------


def test_unknown_operation_is_blocked_not_crashed():
    res = _exec().execute("no_such_op")
    assert res.status == "blocked"
    assert res.block_reason == "unknown_operation"


def test_disallowed_argument_is_refused():
    res = _exec().execute("smtp_test", {"to": "attacker@evil.test"})
    assert res.status == "blocked"
    assert res.block_reason == "disallowed_arg"


def test_operation_below_current_phase_is_blocked():
    # publish_seo_draft needs CONTROLLED_EXECUTION; a READ_ONLY executor must refuse it.
    res = _exec().execute("publish_seo_draft")
    assert res.status == "blocked"
    assert res.block_reason == "phase"


def test_wrong_environment_is_blocked():
    # publish_seo_draft may target staging only.
    res = _exec(phase=Phase.CONTROLLED_EXECUTION, environment="production").execute("publish_seo_draft")
    assert res.status == "blocked"
    assert res.block_reason in ("environment", "phase")  # both are legitimate refusals here


def test_always_ask_op_without_confirmation_is_blocked(monkeypatch):
    # Give it enough phase/env to reach the approval gate, then deny by having no confirm hook.
    monkeypatch.setenv("TC_ALLOW_WRITES", "true")
    res = Executor(phase=Phase.CONTROLLED_EXECUTION, environment="staging",
                   confirm=None, store_factory=lambda: None).execute("publish_seo_draft")
    assert res.status == "blocked"
    assert res.block_reason == "confirmation"


# -- execution (SMTP Test vertical slice) --------------------------------------


def _fake_smtp_steps_ok(emit=None):
    for step, status in [("config", "ok"), ("connect", "ok"), ("starttls", "ok"),
                         ("auth", "ok"), ("send", "ok")]:
        if emit:
            emit(step, status, "")
    return True, "SMTP test passed — test message sent."


def _fake_smtp_steps_fail(emit=None):
    if emit:
        emit("connect", "start", "")
        emit("error", "error", "ConnectionRefusedError: refused")
    return False, "SMTP test FAILED: ConnectionRefusedError: refused"


def test_smtp_test_runs_streams_steps_and_reports_success(monkeypatch):
    monkeypatch.setattr("tc_growth.report.smtp_test_steps", _fake_smtp_steps_ok)
    seen: list[StepEvent] = []
    res = _exec().execute("smtp_test", emit=seen.append)

    assert isinstance(res, ExecutionResult)
    assert res.ok and res.status == "ok"
    assert res.exit_code == 0
    # Step events streamed to the sink AND captured on the result.
    streamed = [s.step for s in seen]
    assert "start" in streamed and "send" in streamed
    assert [s.step for s in res.steps] == streamed
    assert "passed" in res.output


def test_smtp_test_failure_is_a_failed_result_not_an_exception(monkeypatch):
    monkeypatch.setattr("tc_growth.report.smtp_test_steps", _fake_smtp_steps_fail)
    res = _exec().execute("smtp_test")
    assert res.status == "failed"
    assert res.exit_code == 1
    assert "FAILED" in res.output


def test_successful_run_is_persisted_as_evidence(monkeypatch):
    monkeypatch.setattr("tc_growth.report.smtp_test_steps", _fake_smtp_steps_ok)
    store = _FakeStore()
    res = _exec(store_factory=lambda: store).execute("smtp_test", actor="human")

    assert res.evidence_ref == "run#4242"
    assert len(store.calls) == 1
    rec = store.calls[0]
    assert rec["kind"] == "op:smtp_test"
    assert rec["status"] == "ok"
    # The full step transcript is the evidence — it must be recorded, not just the summary.
    assert "steps" in rec["detail"] and "auth" in rec["detail"]
    assert "human" in rec["detail"]


def test_actor_is_recorded_but_does_not_change_permissions(monkeypatch):
    """Origin-agnostic: an 'ai' actor is permitted exactly where a 'human' actor is — the actor
    is audit metadata only. (The AI-trigger PATH is governed separately; the executor itself
    does not gate on origin.)"""
    monkeypatch.setattr("tc_growth.report.smtp_test_steps", _fake_smtp_steps_ok)
    human = _exec().execute("smtp_test", actor="human")
    ai = _exec().execute("smtp_test", actor="ai")
    assert human.status == ai.status == "ok"
    assert ai.actor == "ai"


# -- generic command path (proves new ops need no executor code) ---------------


class _FakeProc:
    def __init__(self, lines, code=0):
        self.stdout = iter(lines)
        self._code = code
        self.killed = False

    def wait(self, timeout=None):
        return self._code

    def kill(self):
        self.killed = True


def test_generic_command_path_streams_stdout_lines(monkeypatch):
    """A command-bound op with no native runner streams subprocess stdout as step events and
    returns the process exit code — so adding such an op is a registry entry, not new code."""
    from tc_growth.core import executor as ex
    from tc_growth.core.actions import Approval, Category, Operation

    op = Operation(
        id="fake_cmd", name="Fake", category=Category.DIAGNOSTICS,
        min_phase=Phase.READ_ONLY, environments=("staging",), approval=Approval.NONE,
        command="list-operations", verification_description="x",
    )
    monkeypatch.setattr(ex.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(["line one\n", "line two\n"], code=0))
    seen: list[StepEvent] = []
    code, output = _exec()._run_command(op, {}, seen.append)
    assert code == 0
    assert "line one" in output and "line two" in output
    assert [s.step for s in seen if s.step == "output"]  # each stdout line became a step event
    # argv is a LIST (no shell) — the command name came from the registry, not the caller.
