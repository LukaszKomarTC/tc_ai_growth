"""WP-U4d — the governed deployment runner (issue #77, Decision 2).

Every test here maps to an acceptance criterion on #77. The two that matter most are the ones
that are easy to fake and hard to prove: that the runner genuinely survives the Console restart
it performs (exercised with a real detached process, not a mock), and that a backup is VERIFIED
before anything irreversible happens.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import textwrap
import time

import pytest

from tc_growth import deploy
from tc_growth.store import open_store
from tc_growth.store.db import SCHEMA_VERSION

SHA = "684681cb72a1e6790c13718eeb786ded2b16c8aa"
OTHER_SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("TC_DB_PATH", str(tmp_path / "store.db"))
    s = open_store()
    yield s
    s.close()


def _plan(store, sha=SHA, by="owner"):
    plan = deploy.build_plan(sha, current_sha="3edb0de" + "0" * 33)
    return store.plan_deploy(sha=sha, plan=plan, plan_digest=deploy.plan_digest(plan),
                             requested_by=by), plan


def _executors(**overrides):
    """A full set of passing executors, with named steps swapped out per test."""
    def ok(name):
        def _run(sha, ctx):
            ctx.setdefault("order", []).append(name)
            return deploy.StepResult(True, f"{name} ok")
        return _run
    table = {s.name: ok(s.name) for s in deploy.STEPS}
    table.update(overrides)
    return table


# --- the authorization is a row, and only an exact SHA -------------------------------------

@pytest.mark.parametrize("bad", [
    "HEAD", "main", "origin/main", "684681c", SHA.upper(), SHA[:-1], SHA + "a", "", "  ",
    "684681cb72a1e6790c13718eeb786ded2b16c8a;", "../../etc/passwd",
])
def test_only_an_exact_lowercase_40_hex_sha_is_accepted(bad):
    with pytest.raises(deploy.DeployRefused):
        deploy.validate_sha(bad)


def test_a_sha_nobody_planned_cannot_be_executed(store):
    """There is no code path from 'a commit someone names' to 'a deployment'."""
    with pytest.raises(deploy.DeployRefused):
        deploy.execute(store, 999, executors=_executors())


def test_a_run_executes_once_and_never_again(store):
    run_id, _ = _plan(store)
    assert deploy.execute(store, run_id, context={}, executors=_executors()) == "succeeded"
    with pytest.raises(deploy.DeployRefused):
        deploy.execute(store, run_id, context={}, executors=_executors())


def test_the_authorized_target_cannot_be_edited_after_review(store):
    """Trigger-enforced: editing sha/plan/plan_digest would let a reviewed plan run a different
    commit. Proven against raw SQL, not through the helper that would never try it."""
    run_id, _ = _plan(store)
    conn = sqlite3.connect(os.environ["TC_DB_PATH"])
    for column, value in (("sha", OTHER_SHA), ("plan_digest", "x" * 64), ("plan", "{}")):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"UPDATE deploy_runs SET {column} = ? WHERE id = ?", (value, run_id))
    conn.close()


def test_a_finished_run_is_terminal_even_against_raw_sql(store):
    run_id, _ = _plan(store)
    deploy.execute(store, run_id, context={}, executors=_executors())
    conn = sqlite3.connect(os.environ["TC_DB_PATH"])
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE deploy_runs SET status='planned' WHERE id=?", (run_id,))
    conn.close()


def test_two_runners_racing_the_same_row_produce_one_deployment(store):
    run_id, _ = _plan(store)
    assert store.start_deploy_run(run_id, pid=111) is True
    assert store.start_deploy_run(run_id, pid=222) is False


# --- closed allowlists ---------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/etc", "/etc/sudoers.d", "/opt/tc_ai_growth", "/opt/tc_ai_growth/app/../../etc",
    "/var/www", "/opt/tc_ai_growth_evil", "/",
])
def test_paths_outside_the_allowlist_are_refused(path):
    with pytest.raises(deploy.DeployRefused):
        deploy._assert_allowed_path(path)


def test_allowlisted_paths_are_accepted():
    assert deploy._assert_allowed_path(deploy.APP_DIR + "/orchestrator") == \
        deploy.APP_DIR + "/orchestrator"
    assert deploy._assert_allowed_path(deploy.release_dir(SHA)).startswith(deploy.RELEASES_DIR)


@pytest.mark.parametrize("svc", ["apache2", "ssh", "tc-console.socket", "cron", ""])
def test_services_outside_the_allowlist_are_refused(svc):
    with pytest.raises(deploy.DeployRefused):
        deploy._assert_allowed_service(svc)


def test_the_dispatch_table_is_closed(store):
    """A step name with no executor cannot fall back to 'run whatever was asked'."""
    assert set(deploy.EXECUTORS) == {s.name for s in deploy.STEPS}
    assert all(callable(fn) for fn in deploy.EXECUTORS.values())


def test_no_executor_uses_a_shell():
    """Checked on the PARSED code, not on the text — prose that merely mentions `shell=True`
    must not make this pass or fail. Nothing here may hand a string to a shell."""
    import ast

    tree = ast.parse(open(deploy.__file__).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                assert kw.arg != "shell" or getattr(kw.value, "value", None) is not True, \
                    "a shell would turn every allowlist into a suggestion"
            name = ast.unparse(node.func)
            assert name not in ("os.system", "os.popen", "subprocess.getoutput",
                                "subprocess.getstatusoutput", "eval", "exec"), name


# --- ordering: backup is VERIFIED before anything irreversible -----------------------------

def test_backup_precedes_every_irreversible_step():
    names = [s.name for s in deploy.STEPS]
    assert names.index("backup") < min(names.index(n) for n in deploy.IRREVERSIBLE)
    assert set(deploy.IRREVERSIBLE) == {"converge", "migrate", "release"}


def test_an_unverifiable_backup_stops_the_deployment_before_migrating(store, tmp_path):
    """If the copy does not match the original it is treated as NO backup — the deployment
    stops, and nothing that cannot be undone has run."""
    def bad_backup(sha, ctx):
        return deploy.StepResult(False, "backup copy does NOT match the original")
    run_id, _ = _plan(store)
    ctx = {}
    assert deploy.execute(store, run_id, context=ctx,
                          executors=_executors(backup=bad_backup)) == "failed"
    ran = ctx.get("order", [])
    for irreversible in deploy.IRREVERSIBLE:
        assert irreversible not in ran
    run = store.get_deploy_run(run_id)
    assert run["status"] == "failed"
    assert "backup" in run["outcome"]


def test_the_real_backup_executor_verifies_its_copy(store, tmp_path):
    """Not a mock: takes a genuine sqlite backup of a populated store and compares table counts."""
    db = os.environ["TC_DB_PATH"]
    store.log_run(kind="weekly-report", status="ok", summary="x")
    ctx = {"db_path": db}
    result = deploy.ex_backup(SHA, ctx)
    assert result.ok, result.summary
    assert os.path.exists(ctx["backup_path"])
    original = sqlite3.connect(db).execute("SELECT count(*) FROM runs").fetchone()[0]
    copy = sqlite3.connect(ctx["backup_path"]).execute("SELECT count(*) FROM runs").fetchone()[0]
    assert original == copy == 1


# --- stop on failure, explicit terminal state ----------------------------------------------

@pytest.mark.parametrize("failing", ["preflight", "suite", "migrate", "release", "health"])
def test_any_failed_step_stops_the_deployment_with_an_explicit_terminal_state(store, failing):
    def fail(sha, ctx):
        ctx.setdefault("order", []).append(failing)
        return deploy.StepResult(False, f"{failing} failed on purpose")
    run_id, _ = _plan(store)
    ctx = {}
    assert deploy.execute(store, run_id, context=ctx,
                          executors=_executors(**{failing: fail})) == "failed"
    run = store.get_deploy_run(run_id)
    assert run["status"] == "failed"
    assert run["finished_at"]
    assert failing in run["outcome"]
    order = [s.name for s in deploy.STEPS]
    after = order[order.index(failing) + 1:]
    assert not set(after) & set(ctx.get("order", [])), "steps ran after the failure"


def test_a_runner_defect_is_recorded_as_a_defect_not_as_policy(store):
    """The U4c lesson, applied from the start: an unexpected exception must never be presented
    as a refusal. It says 'bug', it carries a traceback, and the run fails rather than refuses."""
    def boom(sha, ctx):
        raise RuntimeError("injected defect")
    run_id, _ = _plan(store)
    assert deploy.execute(store, run_id, context={},
                          executors=_executors(migrate=boom)) == "failed"
    steps = store.list_deploy_steps(run_id)
    bad = [s for s in steps if s["status"] == "failed"][-1]
    assert "defect" in bad["summary"] and "not a policy refusal" in bad["summary"]
    assert "RuntimeError" in bad["summary"]
    assert "Traceback" in (bad["detail"] or "")
    assert store.get_deploy_run(run_id)["status"] == "failed"


def test_a_policy_refusal_is_recorded_as_a_refusal(store):
    def refuse(sha, ctx):
        raise deploy.DeployRefused("target is not on origin/main")
    run_id, _ = _plan(store)
    assert deploy.execute(store, run_id, context={},
                          executors=_executors(preflight=refuse)) == "refused"
    run = store.get_deploy_run(run_id)
    assert run["status"] == "refused"
    assert "origin/main" in run["outcome"]


# --- evidence is append-only and complete --------------------------------------------------

def test_steps_are_append_only_evidence(store):
    run_id, _ = _plan(store)
    deploy.execute(store, run_id, context={}, executors=_executors())
    conn = sqlite3.connect(os.environ["TC_DB_PATH"])
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE deploy_steps SET summary='tidied' WHERE run_id=?", (run_id,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM deploy_steps WHERE run_id=?", (run_id,))
    conn.close()


def test_every_step_is_timestamped_and_attributable(store):
    run_id, _ = _plan(store, by="owner")
    deploy.execute(store, run_id, context={}, executors=_executors())
    steps = store.list_deploy_steps(run_id)
    assert [s["name"] for s in steps if s["status"] == "running"] == [s.name for s in deploy.STEPS]
    assert all(s["at"] for s in steps)
    assert store.get_deploy_run(run_id)["requested_by"] == "owner"
    assert store.get_deploy_run(run_id)["sha"] == SHA


# --- secrets never reach evidence ----------------------------------------------------------

@pytest.mark.parametrize("secret_line", [
    "TC_CONSOLE_TOKEN=abc123def456abc123def456",
    "tc_smtp_password: hunter2hunter2",
    "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",
    "MY_API_KEY = sk-live-0123456789abcdef",
])
def test_secret_shaped_values_are_redacted_before_storage(store, secret_line):
    def leaky(sha, ctx):
        return deploy.StepResult(False, f"failed: {secret_line}", f"detail: {secret_line}")
    run_id, _ = _plan(store)
    deploy.execute(store, run_id, context={}, executors=_executors(release=leaky))
    blob = json.dumps(store.list_deploy_steps(run_id)) + json.dumps(store.get_deploy_run(run_id))
    assert "redacted" in blob
    for token in ("abc123def456abc123def456", "hunter2hunter2", "sk-live-0123456789abcdef",
                  "eyJhbGciOiJIUzI1NiJ9.payload.signature"):
        assert token not in blob


# --- the plan the owner reviews ------------------------------------------------------------

def test_the_plan_names_irreversible_steps_before_authorization():
    plan = deploy.build_plan(SHA)
    assert plan["irreversible_steps"] == list(deploy.IRREVERSIBLE)
    assert plan["touches_production_wordpress"] is False
    assert plan["stop_on_failure"] is True
    assert "rollback" in plan and "--rollback" in plan["rollback"]
    text = deploy.plan_text(plan)
    assert "NOT REVERSIBLE" in text
    for name in deploy.IRREVERSIBLE:
        assert name in text
    assert SHA in text


def test_authorization_is_bound_to_the_plan_that_was_displayed():
    """Same consent binding as U4c's adopt-live: a plan that changed is a plan that was not
    reviewed."""
    a = deploy.build_plan(SHA)
    b = deploy.build_plan(SHA)
    assert deploy.plan_digest(a) == deploy.plan_digest(b)
    c = deploy.build_plan(OTHER_SHA)
    assert deploy.plan_digest(a) != deploy.plan_digest(c)


# --- the detached runner genuinely survives the Console restart -----------------------------

def test_a_detached_runner_outlives_the_process_that_started_it(tmp_path, monkeypatch):
    """The criterion that cannot be proven with a mock.

    A parent process starts a detached child (exactly as the Console starts the runner), then the
    parent is KILLED — standing in for the Console restart the deployment itself performs. The
    child must still finish and write its own terminal result to the store.
    """
    db = tmp_path / "store.db"
    monkeypatch.setenv("TC_DB_PATH", str(db))
    s = open_store()
    run_id, _ = _plan(s)
    s.close()

    child = tmp_path / "runner.py"
    child.write_text(textwrap.dedent(f"""
        import os, sys, time
        sys.path.insert(0, {str(os.path.dirname(os.path.dirname(deploy.__file__)))!r})
        os.environ["TC_DB_PATH"] = {str(db)!r}
        from tc_growth import deploy
        from tc_growth.store import open_store
        def slow(sha, ctx):
            time.sleep(1.5)          # still running when the parent dies
            return deploy.StepResult(True, "survived the restart")
        def ok(sha, ctx):
            return deploy.StepResult(True, "ok")
        table = {{st.name: ok for st in deploy.STEPS}}
        table["release"] = slow
        store = open_store()
        deploy.execute(store, {run_id}, context={{}}, executors=table)
    """))

    parent = tmp_path / "parent.py"
    parent.write_text(textwrap.dedent(f"""
        import subprocess, sys, time
        subprocess.Popen([sys.executable, {str(child)!r}], start_new_session=True)
        time.sleep(0.3)
    """))

    proc = subprocess.Popen([sys.executable, str(parent)])
    time.sleep(0.6)
    proc.kill()                      # the Console dies mid-deployment
    proc.wait(timeout=10)

    deadline = time.time() + 30
    status = None
    while time.time() < deadline:
        s2 = open_store()
        status = s2.get_deploy_run(run_id)["status"]
        steps = s2.list_deploy_steps(run_id)
        s2.close()
        if status in ("succeeded", "failed", "refused"):
            break
        time.sleep(0.25)

    assert status == "succeeded", f"the detached runner did not finish (status={status})"
    assert any(st["summary"] == "survived the restart" for st in steps)
    assert [st["name"] for st in steps if st["status"] == "ok"] == [s.name for s in deploy.STEPS]


def test_the_console_can_reconnect_to_a_run_by_id_after_a_restart(store):
    """Reconnection is by durable id, not by an in-memory handle — so a restarted Console shows
    the same run and its terminal result rather than orphaning it."""
    run_id, _ = _plan(store)
    deploy.execute(store, run_id, context={}, executors=_executors())
    reopened = open_store()
    try:
        run = reopened.get_deploy_run(run_id)
        assert run["status"] == "succeeded"
        assert len(reopened.list_deploy_steps(run_id)) == 2 * len(deploy.STEPS)
    finally:
        reopened.close()


# --- the increment does not claim to deploy its own bootstrap -------------------------------

def test_the_deploy_operation_is_registered_but_not_yet_offered():
    from tc_growth.core.actions import get_operation, validate_registry

    validate_registry()
    op = get_operation("deploy_release")
    assert op.enabled is False, ("#77: the runner must prove itself on a disposable target "
                                 "before it can be clicked")
    assert op.allowed_args == ("run_id",), "the commit must never be a request argument"
    assert op.target_surface == "platform"
    assert "never invokes the WordPress connector: no site write path exists here" in op.enforced_by


def test_no_remote_trigger_path_is_introduced():
    """#77 Decision 2 rejected a remote identity. Nothing here may open one."""
    src = open(deploy.__file__).read()
    for forbidden in ("paramiko", "ssh ", "authorized_keys", "ProxyCommand", "socket.bind"):
        assert forbidden not in src


# --- migration ------------------------------------------------------------------------------

def test_v6_store_migrates_to_v7_leaving_every_existing_record_intact(tmp_path, monkeypatch):
    """The pre-deploy evidence: a populated v6 store gains the deploy tables and loses nothing."""
    db = tmp_path / "store.db"
    monkeypatch.setenv("TC_DB_PATH", str(db))
    s = open_store()
    case_id = s.seed_incident_case()
    s.log_run(kind="weekly-report", status="ok", summary="prior evidence", case_id=case_id)
    s.close()

    conn = sqlite3.connect(db)
    before = {t: conn.execute(f"SELECT * FROM {t}").fetchall() for t in
              ("runs", "cases", "decisions", "decision_events", "decision_verify_attempts",
               "decision_adoptions", "report_artifacts")}
    conn.execute("DROP TABLE deploy_steps")
    conn.execute("DROP TABLE deploy_runs")
    conn.execute("UPDATE schema_version SET version = 6")
    conn.commit()
    conn.close()

    s = open_store()
    try:
        conn = sqlite3.connect(db)
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == SCHEMA_VERSION
        after = {t: conn.execute(f"SELECT * FROM {t}").fetchall() for t in before}
        assert after == before
        assert conn.execute("SELECT count(*) FROM deploy_runs").fetchone()[0] == 0
        conn.close()
    finally:
        s.close()
