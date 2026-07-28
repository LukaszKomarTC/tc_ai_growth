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
    assert res.execution_status == "blocked"
    assert res.block_reason == "unknown_operation"


def test_disallowed_argument_is_refused():
    res = _exec().execute("smtp_test", {"to": "attacker@evil.test"})
    assert res.execution_status == "blocked"
    assert res.block_reason == "disallowed_arg"


def test_operation_below_current_phase_is_blocked():
    # publish_seo_draft needs CONTROLLED_EXECUTION; a READ_ONLY executor must refuse it.
    res = _exec().execute("publish_seo_draft")
    assert res.execution_status == "blocked"
    assert res.block_reason == "phase"


def test_wrong_environment_is_blocked():
    # publish_seo_draft may target staging only.
    res = _exec(phase=Phase.CONTROLLED_EXECUTION, environment="production").execute("publish_seo_draft")
    assert res.execution_status == "blocked"
    assert res.block_reason in ("environment", "phase")  # both are legitimate refusals here


def test_always_ask_op_without_confirmation_is_blocked(monkeypatch):
    # Give it enough phase/env to reach the approval gate, then deny by having no confirm hook.
    monkeypatch.setenv("TC_ALLOW_WRITES", "true")
    res = Executor(phase=Phase.CONTROLLED_EXECUTION, environment="staging",
                   confirm=None, store_factory=lambda: None).execute("publish_seo_draft")
    assert res.execution_status == "blocked"
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
    assert res.completed and res.clean            # exit 0, default policy -> success/ok
    assert res.execution_status == "completed" and res.outcome == "success"
    assert res.exit_code == 0
    # Step events streamed to the sink AND captured on the result.
    streamed = [s.step for s in seen]
    assert "start" in streamed and "send" in streamed
    assert [s.step for s in res.steps] == streamed
    assert "passed" in res.output


def test_smtp_test_failure_is_an_execution_error_not_an_exception(monkeypatch):
    # SMTP has no result_policy, so a non-zero exit is a genuine execution error (the tool could
    # not do its job) — distinct from a diagnostic that COMPLETES with findings.
    monkeypatch.setattr("tc_growth.report.smtp_test_steps", _fake_smtp_steps_fail)
    res = _exec().execute("smtp_test")
    assert res.execution_status == "error" and res.outcome == "failure"
    assert res.severity == "error"
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
    assert rec["status"] == "completed"       # ledger status = execution_status, never a domain outcome
    # The full step transcript + interpreted result is the evidence — recorded, not just a summary.
    assert "steps" in rec["detail"] and "auth" in rec["detail"]
    assert '"outcome": "success"' in rec["detail"] and '"severity": "ok"' in rec["detail"]
    assert "human" in rec["detail"]


def test_smtp_password_never_appears_in_evidence(monkeypatch):
    """Acceptance requirement: the SMTP password must not appear in output, steps, or evidence.
    Exercises the REAL smtp_test_steps against a fake SMTP server."""
    import smtplib

    from tc_growth import report

    SENTINEL = "S3cr3t-PW-do-not-leak"
    for k, v in {"TC_SMTP_HOST": "smtp.example.test", "TC_SMTP_PORT": "587",
                 "TC_SMTP_USER": "info@example.test", "TC_SMTP_PASSWORD": SENTINEL,
                 "TC_REPORT_RECIPIENT": "owner@example.test"}.items():
        monkeypatch.setenv(k, v)
    report.get_settings.cache_clear() if hasattr(report.get_settings, "cache_clear") else None

    class _FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): pass
        def login(self, u, p): pass
        def send_message(self, m): pass

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    seen: list[tuple] = []
    _ok, summary = report.smtp_test_steps(emit=lambda s, st, d="": seen.append((s, st, d)))
    blob = summary + " " + " ".join(f"{s} {st} {d}" for s, st, d in seen)
    assert SENTINEL not in blob, "SMTP password leaked into evidence/output"


def test_integrity_scan_target_cannot_be_overridden(monkeypatch):
    """Acceptance requirement: the scan target is server-pinned; a client cannot redirect it.
    The op takes no args, so any arg is refused before anything runs."""
    res = _exec().execute("run_integrity_scan", {"docroot": "/etc"})
    assert res.execution_status == "blocked" and res.block_reason == "disallowed_arg"


def test_evidence_records_provenance(monkeypatch):
    """Every evidence record must be traceable to a reviewed revision + a target — 'the scan
    passed' is useless without knowing which code ran, on which profile, in which environment."""
    import json

    monkeypatch.setattr("tc_growth.report.smtp_test_steps", _fake_smtp_steps_ok)
    monkeypatch.setenv("TC_BUILD_COMMIT", "abc1234")
    monkeypatch.setenv("TC_SITE", "production")
    store = _FakeStore()
    _exec(environment="production", store_factory=lambda: store).execute("smtp_test")
    prov = json.loads(store.calls[0]["detail"])["provenance"]
    assert prov["repo_commit"] == "abc1234"
    assert prov["profile"] == "production"
    assert prov["environment"] == "production"
    assert prov["binding"] == "cli:smtp-test"
    assert prov["release"]  # the platform release is stamped too


def test_actor_is_recorded_but_does_not_change_permissions(monkeypatch):
    """Origin-agnostic: an 'ai' actor is permitted exactly where a 'human' actor is — the actor
    is audit metadata only. (The AI-trigger PATH is governed separately; the executor itself
    does not gate on origin.)"""
    monkeypatch.setattr("tc_growth.report.smtp_test_steps", _fake_smtp_steps_ok)
    human = _exec().execute("smtp_test", actor="human")
    ai = _exec().execute("smtp_test", actor="ai")
    assert human.execution_status == ai.execution_status == "completed"
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


def test_integrity_scan_op_needs_no_executor_code():
    """Op #2 is proof of the claim: a new operation is a registry entry, NOT executor code.
    run_integrity_scan must run through the generic command path — no native runner."""
    from tc_growth.core import executor as ex
    from tc_growth.core.actions import get_operation

    assert "run_integrity_scan" not in ex.NATIVE_RUNNERS
    op = get_operation("run_integrity_scan")
    assert op.command == "integrity-scan" and op.tool is None


def test_interpret_exit_uses_the_ops_result_policy():
    from tc_growth.core.actions import get_operation
    from tc_growth.core.executor import interpret_exit

    scan = get_operation("run_integrity_scan")
    assert interpret_exit(scan, 0) == ("completed", "clean", "ok")
    assert interpret_exit(scan, 2) == ("completed", "findings", "attention")
    assert interpret_exit(scan, 127) == ("error", "failure", "error")  # outside the policy
    # An op with NO policy: 0 = success, anything else = error (the sane default).
    smtp = get_operation("smtp_test")
    assert interpret_exit(smtp, 0) == ("completed", "success", "ok")
    assert interpret_exit(smtp, 1) == ("error", "failure", "error")


def test_preview_surfaces_possible_outcomes():
    prev = _exec().preview("run_integrity_scan")
    labels = {o for o, _sev in prev.outcomes}
    assert labels == {"clean", "findings"}
    assert dict(prev.outcomes)["findings"] == "attention"


def test_integrity_scan_previews_as_a_read_only_runnable_op():
    prev = _exec().preview("run_integrity_scan")
    assert prev.binding == "cli:integrity-scan"
    assert prev.writes is False
    assert prev.runnable_now is True


def test_integrity_scan_findings_are_completed_with_findings_not_failed(monkeypatch):
    """The inspector exits 2 when it finds anomalies. That is a COMPLETED diagnostic with a
    'findings' outcome (severity attention) — NOT a failed execution. Recording it as failed
    would poison reliability metrics and make the tool look broken when it worked."""
    from tc_growth.core import executor as ex

    lines = ["Technical Inspector — integrity anomalies:", "  - ADMIN set changed"]
    monkeypatch.setattr(ex.subprocess, "Popen",
                        lambda *a, **k: _FakeProc([line + "\n" for line in lines], code=2))
    seen: list[StepEvent] = []
    res = _exec().execute("run_integrity_scan", emit=seen.append)
    assert res.execution_status == "completed"    # the tool ran successfully...
    assert res.outcome == "findings"              # ...and its outcome is findings...
    assert res.severity == "attention"            # ...which warrants attention, not an error.
    assert res.completed and not res.clean
    assert res.exit_code == 2
    assert "ADMIN set changed" in res.output
    assert any(s.step == "output" for s in seen)   # streamed line-by-line


def test_integrity_scan_clean_is_completed_clean(monkeypatch):
    from tc_growth.core import executor as ex

    monkeypatch.setattr(ex.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(["inspector: clean exit=0\n"], code=0))
    res = _exec().execute("run_integrity_scan")
    assert res.execution_status == "completed" and res.outcome == "clean"
    assert res.clean and res.exit_code == 0


def test_integrity_scan_unexpected_exit_is_a_real_error(monkeypatch):
    """A code OUTSIDE the result policy (e.g. the script crashed) IS an execution error — the
    policy is not a licence to swallow genuine failures."""
    from tc_growth.core import executor as ex

    monkeypatch.setattr(ex.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(["bash: wp: command not found\n"], code=127))
    res = _exec().execute("run_integrity_scan")
    assert res.execution_status == "error" and res.outcome == "failure"
    assert res.severity == "error" and res.exit_code == 127


def test_cli_integrity_scan_reports_cleanly_when_script_missing(monkeypatch, capsys):
    from tc_growth.cli import cmd_integrity_scan

    monkeypatch.setenv("TC_INSPECTOR_SCRIPT", "/no/such/inspector.sh")
    rc = cmd_integrity_scan()
    assert rc == 1
    assert "not found" in capsys.readouterr().out


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
