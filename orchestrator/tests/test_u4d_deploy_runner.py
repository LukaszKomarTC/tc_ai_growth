"""WP-U4d — the governed deployment runner (issue #77, Decision 2).

Every test here maps to an acceptance criterion on #77. The two that matter most are the ones
that are easy to fake and hard to prove: that the runner genuinely survives the Console restart
it performs (exercised with a real detached process, not a mock), and that a backup is VERIFIED
before anything irreversible happens.
"""

from __future__ import annotations

import json
import os
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


# --- review #78 blocker 1: the CLAIM is the mutual exclusion, not the earlier read ------------

def test_two_genuinely_concurrent_executes_produce_exactly_one_deployment(tmp_path, monkeypatch):
    """Real threads, released together by a barrier, each with its OWN store connection — the
    shape two detached runners actually have. Exactly one may run the executors."""
    import threading

    monkeypatch.setenv("TC_DB_PATH", str(tmp_path / "store.db"))
    setup = open_store()
    run_id, _ = _plan(setup)
    setup.close()

    barrier = threading.Barrier(2)
    lock = threading.Lock()
    ran: list[str] = []
    outcomes: list[object] = []

    def executor(sha, ctx):
        with lock:
            ran.append(ctx["who"])
        time.sleep(0.05)
        return deploy.StepResult(True, "ok")

    def runner(who):
        store = open_store()
        table = {st.name: executor for st in deploy.STEPS}
        barrier.wait()
        try:
            outcomes.append(deploy.execute(store, run_id, context={"who": who}, executors=table))
        except deploy.DeployRefused as exc:
            outcomes.append(exc)
        finally:
            store.close()

    threads = [threading.Thread(target=runner, args=(w,)) for w in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    winners = [o for o in outcomes if o == "succeeded"]
    losers = [o for o in outcomes if isinstance(o, deploy.DeployRefused)]
    assert len(winners) == 1, f"expected exactly one winner, got {outcomes}"
    assert len(losers) == 1, f"the loser must be refused, got {outcomes}"
    assert "already claimed" in str(losers[0])

    # The loser ran NO executor: every recorded step belongs to the same runner.
    assert len(set(ran)) == 1, f"both runners executed steps: {ran}"
    assert len(ran) == len(deploy.STEPS)


def test_the_loser_records_no_step_and_cannot_touch_the_winners_evidence(store):
    """It must stop before the first step is written — not merely before the first executor."""
    run_id, _ = _plan(store)
    assert store.start_deploy_run(run_id, pid=4242) is True   # the "winner" claims it first
    before = store.list_deploy_steps(run_id)
    with pytest.raises(deploy.DeployRefused) as exc:
        deploy.execute(store, run_id, context={}, executors=_executors())
    # Either refusal is correct here: the sequential case trips the `not planned` read, the
    # genuinely concurrent case (above) trips the atomic claim. What must hold in BOTH is that
    # the loser wrote nothing and changed nothing.
    assert "not planned" in str(exc.value) or "already claimed" in str(exc.value)
    assert store.list_deploy_steps(run_id) == before == []
    run = store.get_deploy_run(run_id)
    assert run["status"] == "running" and run["runner_pid"] == 4242
    assert run["finished_at"] is None


def test_double_authorization_cannot_duplicate_migration_release_or_restart(store):
    """Authorize twice, run twice: the second attempt performs no irreversible step at all."""
    run_id, _ = _plan(store)
    first, second = {}, {}
    assert deploy.execute(store, run_id, context=first, executors=_executors()) == "succeeded"
    with pytest.raises(deploy.DeployRefused):
        deploy.execute(store, run_id, context=second, executors=_executors())
    for irreversible in deploy.IRREVERSIBLE:
        assert first["order"].count(irreversible) == 1
        assert irreversible not in second.get("order", [])


# --- review #78 blocker 2: the backup proof must match the promise ---------------------------

def test_a_healthy_copy_passes_integrity_and_content_verification(store, tmp_path):
    db = os.environ["TC_DB_PATH"]
    store.log_run(kind="weekly-report", status="ok", summary="evidence that must survive")
    ctx = {"db_path": db}
    result = deploy.ex_backup(SHA, ctx)
    assert result.ok, result.summary
    assert "integrity_check ok" in result.summary and "content digest" in result.summary
    ok, why = deploy.verify_backup(db, ctx["backup_path"])
    assert ok, why


def test_a_backup_with_identical_counts_but_changed_content_is_REJECTED(store, tmp_path):
    """The exact case row counts cannot see: same tables, same number of rows, different values."""
    db = os.environ["TC_DB_PATH"]
    store.log_run(kind="weekly-report", status="ok", summary="the original text")
    ctx = {"db_path": db}
    assert deploy.ex_backup(SHA, ctx).ok
    dst = ctx["backup_path"]

    conn = sqlite3.connect(dst)
    conn.execute("UPDATE runs SET summary = 'tampered — same row, different content'")
    conn.commit()
    counts_src = sqlite3.connect(db).execute("SELECT count(*) FROM runs").fetchone()[0]
    counts_dst = conn.execute("SELECT count(*) FROM runs").fetchone()[0]
    conn.close()
    assert counts_src == counts_dst, "the tamper must keep counts equal, or it proves nothing"

    ok, why = deploy.verify_backup(db, dst)
    assert not ok
    assert "CONTENT differs" in why


def test_a_structurally_broken_backup_is_REJECTED(tmp_path, store):
    db = os.environ["TC_DB_PATH"]
    broken = tmp_path / "broken.bak"
    broken.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
    ok, why = deploy.verify_backup(db, str(broken))
    assert not ok
    assert "integrity_check" in why or "not a readable SQLite database" in why


def test_a_missing_table_in_the_copy_is_REJECTED(tmp_path, store):
    db = os.environ["TC_DB_PATH"]
    ctx = {"db_path": db}
    assert deploy.ex_backup(SHA, ctx).ok
    conn = sqlite3.connect(ctx["backup_path"])
    conn.execute("DROP TABLE deploy_steps")
    conn.commit()
    conn.close()
    ok, why = deploy.verify_backup(db, ctx["backup_path"])
    assert not ok


def test_the_content_digest_ignores_row_order_but_not_row_values(tmp_path):
    """Determinism check: the digest must not depend on insertion order, or every backup would
    look tampered; it must depend on values, or nothing is proven."""
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    for path, rows in ((a, ["x", "y"]), (b, ["y", "x"])):
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE t (v TEXT)")
        conn.executemany("INSERT INTO t VALUES (?)", [(r,) for r in rows])
        conn.commit()
        conn.close()
    assert deploy.content_digest(str(a))[0] == deploy.content_digest(str(b))[0]

    conn = sqlite3.connect(b)
    conn.execute("UPDATE t SET v = 'z' WHERE v = 'x'")
    conn.commit()
    conn.close()
    assert deploy.content_digest(str(a))[0] != deploy.content_digest(str(b))[0]


def test_an_unverifiable_backup_stops_before_anything_irreversible_end_to_end(store, monkeypatch):
    """The real executor, with verification forced to fail: no irreversible step may run."""
    monkeypatch.setattr(deploy, "verify_backup", lambda src, dst: (False, "forced failure"))
    run_id, _ = _plan(store)
    ctx = {"db_path": os.environ["TC_DB_PATH"]}
    table = _executors(backup=deploy.ex_backup)
    assert deploy.execute(store, run_id, context=ctx, executors=table) == "failed"
    for irreversible in deploy.IRREVERSIBLE:
        assert irreversible not in ctx.get("order", [])
    assert "could NOT be verified" in store.get_deploy_run(run_id)["outcome"]


def test_the_plan_states_exactly_what_the_backup_proof_guarantees():
    """Criterion 7: the owner-facing text must not call count equality a verified recovery copy."""
    plan = deploy.build_plan(SHA)
    backup_step = [s for s in plan["steps"] if s["name"] == "backup"][0]
    assert "integrity_check" in backup_step["detail"]
    assert "content digest" in backup_step["detail"]
    assert "Equal row counts are NOT accepted as proof" in backup_step["detail"]
    assert "row-content digest match" in plan["rollback"]
    assert "not\n" not in plan["rollback"]


# --- enablement gate criterion 2: the privilege surface is ONE fixed escalation ---------------

def test_the_runner_escalates_exactly_once_and_only_through_the_wrapper():
    """The runner already IS the service user (the Console unit sets User=tcgrowth), so every
    `sudo -u tcgrowth ...` was a no-op that nonetheless required a sudoers rule wide enough to
    run arbitrary git and python. All of them are gone. What remains is one fixed root-owned
    wrapper taking a validated SHA and nothing else."""
    import ast

    tree = ast.parse(open(deploy.__file__).read())
    sudo_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and node.elts:
            first = node.elts[0]
            if isinstance(first, ast.Constant) and first.value == "sudo":
                sudo_calls.append([ast.unparse(e) for e in node.elts])
    assert len(sudo_calls) == 1, f"expected exactly one escalation, found {sudo_calls}"
    argv = sudo_calls[0]
    assert argv == ["'sudo'", "'-n'", "DEPLOY_WRAPPER", "'apply'", "sha"], argv
    assert deploy.DEPLOY_WRAPPER == "/usr/local/bin/tc-deploy-release.sh"


def test_the_privileged_step_refuses_to_run_as_root(monkeypatch):
    """Guarding the escalation, not the whole run: a deployment whose steps never escalate has
    nothing to defend, and the property is a statement about THIS step."""
    monkeypatch.setattr(deploy.os, "geteuid", lambda: 0)
    with pytest.raises(deploy.DeployRefused) as exc:
        deploy.ex_release(SHA, {"db_path": "x", "venv": "y"})
    assert "must not run as root" in str(exc.value)


def test_a_root_refusal_inside_a_step_ends_the_run_as_refused_not_as_a_defect(store, monkeypatch):
    monkeypatch.setattr(deploy.os, "geteuid", lambda: 0)
    run_id, _ = _plan(store)
    ctx = {"db_path": os.environ["TC_DB_PATH"], "venv": "v"}
    assert deploy.execute(store, run_id, context=ctx,
                          executors=_executors(release=deploy.ex_release)) == "refused"
    assert "must not run as root" in store.get_deploy_run(run_id)["outcome"]


WRAPPER = os.path.join(os.path.dirname(os.path.dirname(deploy.__file__)),
                       "scripts", "tc-deploy-release.sh")


@pytest.mark.parametrize("bad", [
    "", "main", "HEAD", "684681c", SHA.upper(), SHA + "a", "; rm -rf /", "../../etc/passwd",
    "0123456789abcdef0123456789abcdef0123456g",
])
def test_the_root_wrapper_validates_the_sha_itself(bad):
    """Root-owned code must not trust its caller. Anything that reaches sudo can pass any string;
    the wrapper is what decides that only a 40-hex SHA is meaningful."""
    proc = subprocess.run(["bash", WRAPPER, "apply", bad], capture_output=True, text=True,
                          timeout=30)
    assert proc.returncode != 0, f"the wrapper accepted {bad!r}"
    assert "tc-deploy-release" in proc.stderr


@pytest.mark.parametrize("argv", [[], ["apply"], ["apply", SHA, "--force"], ["rollback", SHA]])
def test_the_root_wrapper_refuses_anything_but_a_fixed_verb_and_its_argument(argv):
    proc = subprocess.run(["bash", WRAPPER, *argv], capture_output=True, text=True, timeout=30)
    assert proc.returncode != 0, f"the wrapper accepted {argv}"


# --- PR #79 review blocker: root must never execute service-user-writable code ----------------

def _wrapper_source() -> str:
    return open(WRAPPER).read()


def test_root_never_executes_anything_from_the_release_or_app_tree():
    """The blocker in its own words: the release worktree is created by, and writable by,
    tcgrowth. `HEAD == SHA` proves which commit was checked out, not that the files still match
    it — and git cannot be the witness either, because the worktree's `.git` is writable by the
    same account. So the wrapper must not exec anything from there, at all, on any branch."""
    # Join shell line continuations first: the privileged exec spans several lines, and
    # inspecting only the first would miss what it actually runs.
    joined = _wrapper_source().replace("\\\n", " ")
    execs = [ln.strip() for ln in joined.splitlines()
             if ln.strip().startswith(("exec ", "source ", ". /", ". $"))
             and not ln.strip().startswith("#")]
    assert execs, "no privileged exec found — the test would pass vacuously"
    for line in execs:
        # The release dir may be PASSED as data (an env value the helper reads); what must never
        # happen is root EXECUTING something from it. The executed program is the last word.
        program = line.split()[-2] if line.endswith(("--apply", "--rollback")) else line.split()[-1]
        assert "DEPLOY_SCRIPT" in program, f"root would execute: {program} (in: {line})"
        assert "REL" not in program and "RELEASES_DIR" not in program \
            and "APP_DIR" not in program, f"root would execute writable code: {program}"


def test_the_rollback_branch_does_not_discover_code_through_systemd():
    """The rollback path had the same defect: it read WorkingDirectory and exec'd from there."""
    src = _wrapper_source()
    assert "WorkingDirectory" not in src.replace("# ", "").split("--rollback")[-1] or \
        "systemctl show" not in src, "rollback must not select executable code from systemd state"
    assert "systemctl show" not in src


def test_the_privileged_machinery_lives_outside_the_repository():
    src = _wrapper_source()
    assert "/usr/local/lib/tc-deploy" in src
    assert "assert_root_owned" in src, "ownership must be checked at invocation, not assumed"


def test_the_wrapper_refuses_when_its_machinery_is_missing_or_not_root_owned(tmp_path):
    """Checked at every invocation rather than trusted from install time: if the mode or owner
    was loosened since, this is where the deployment stops."""
    proc = subprocess.run(["bash", WRAPPER, "apply", SHA], capture_output=True, text=True,
                          timeout=30, env={**os.environ, "PATH": os.environ.get("PATH", "")})
    # In this environment /usr/local/lib/tc-deploy does not exist, so the refusal must name it.
    assert proc.returncode != 0
    assert ("missing root-owned" in proc.stderr or "must be root:root" in proc.stderr), \
        proc.stderr


def test_modifying_the_release_worktree_cannot_influence_the_privileged_operation(tmp_path):
    """Adversarial: stage a worktree whose deploy-console.sh has been replaced with a payload,
    then invoke the wrapper. It must never reach that file — proven by the wrapper refusing on
    its own machinery check and by the payload never running."""
    marker = tmp_path / "payload-ran"
    rel = tmp_path / "releases" / SHA / "orchestrator" / "scripts"
    rel.mkdir(parents=True)
    (rel / "deploy-console.sh").write_text(f"#!/bin/bash\ntouch {marker}\n")
    (rel / "deploy-console.sh").chmod(0o755)
    subprocess.run(["bash", WRAPPER, "apply", SHA], capture_output=True, text=True, timeout=30)
    assert not marker.exists(), "root executed a file the service user had replaced"


# --- criterion 6: escalation scanning covers non-literal and alternate mechanisms -------------

#: The single reviewed escalation. Anything else that could raise privilege must be absent.
ALLOWED_ESCALATION = ("sudo", "-n", "DEPLOY_WRAPPER", "apply", "sha")


def test_no_alternate_escalation_mechanism_exists_anywhere_in_the_runner():
    """Counting literal ["sudo", ...] lists is not a complete property (review #79). This also
    forbids su/pkexec/systemd-run/os.exec*, and any subprocess whose executable is derived from a
    variable rather than written down — with exactly one reviewed allowlist entry."""
    import ast

    src = open(deploy.__file__).read()
    tree = ast.parse(src)

    for name in ("os.execv", "os.execve", "os.execvp", "os.execl", "os.execlp", "os.spawnv",
                 "pty.spawn"):
        assert name not in src, f"alternate execution mechanism present: {name}"

    escalators = {"su", "pkexec", "systemd-run", "doas", "runuser", "machinectl"}
    found_allowed = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and node.elts:
            first = node.elts[0]
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                continue
            head = os.path.basename(first.value)
            if head in escalators:
                raise AssertionError(f"alternate escalation mechanism: {ast.unparse(node)}")
            if head == "sudo":
                argv = tuple(ast.unparse(e).strip("'") for e in node.elts)
                assert argv == ALLOWED_ESCALATION, f"unreviewed escalation: {argv}"
                found_allowed += 1
    assert found_allowed == 1, f"expected exactly one reviewed escalation, found {found_allowed}"


# --- PR #79 round 2: the trust anchor itself must be reviewable -------------------------------

INSTALLER = os.path.join(os.path.dirname(os.path.dirname(deploy.__file__)),
                         "scripts", "install-tc-deploy.sh")


def test_the_privileged_helper_and_its_installer_exist_in_the_repository():
    """Round 2's blocker: the wrapper named /usr/local/lib/tc-deploy/deploy-console.sh as its
    trust anchor, but no such file existed in the repo. The most security-sensitive code had
    moved outside the diff. The repository copy is the auditable source of truth."""
    scripts = os.path.dirname(WRAPPER)
    assert os.path.exists(os.path.join(scripts, "deploy-console.sh"))
    assert os.path.exists(INSTALLER)
    src = open(INSTALLER).read()
    assert "MANIFEST.sha256" in src, "the installer must record a verifiable digest"
    assert "sha256sum --check" in src, "the installer must verify what actually landed"


def test_the_privileged_program_verifies_its_helper_against_a_root_owned_digest():
    src = _wrapper_source()
    assert "MANIFEST" in src
    assert "sha256sum --check" in src, "a swapped helper must be detected at every invocation"
    assert 'assert_root_owned "$ROOT_LIB" "directory"' in src, \
        "a root-owned file in a writable directory can be replaced wholesale"


def test_the_privileged_program_ignores_caller_supplied_environment():
    """Criterion 3: the helper must not treat TC_* values from the caller as authority. Every
    value handed to the child is a constant of the program or derived from the validated SHA,
    and the child starts from a constructed minimal environment."""
    src = _wrapper_source()
    assert "/usr/bin/env -i" in src, "the child must not inherit the caller's environment"
    for constant in ("RELEASES_DIR=/opt/tc_ai_growth/releases", "SERVICE_USER=tcgrowth",
                     "SERVICE_NAME=tc-console", "BACKUP_DIR=/var/backups/tc-console"):
        assert constant in src, f"path/name must be an internal constant: {constant}"


@pytest.mark.parametrize("argv", [
    ["apply"], ["apply", SHA, "extra"], ["rollback", SHA], ["deploy", SHA], [""],
    ["--apply", SHA], ["apply", "; rm -rf /"], ["apply", "../../etc"],
])
def test_the_privileged_program_accepts_only_fixed_verbs_and_an_exact_sha(argv):
    proc = subprocess.run(["bash", WRAPPER, *argv], capture_output=True, text=True, timeout=30)
    assert proc.returncode != 0, f"accepted {argv}"


def test_a_forged_environment_cannot_redirect_the_privileged_program(tmp_path):
    """Adversarial: the service user exports hostile TC_* values before invoking. They must not
    reach the child — the program refuses before that on its own machinery check, and none of
    the forged values appear in its decision-making."""
    hostile = {**os.environ,
               "TC_RELEASE_DIR": str(tmp_path), "TC_VENV": "/tmp/evil",
               "TC_STORE_DB": "/tmp/evil.db", "TC_SERVICE_USER": "root",
               "TC_SERVICE_NAME": "sshd", "TC_BACKUP_DIR": str(tmp_path)}
    proc = subprocess.run(["bash", WRAPPER, "apply", SHA], capture_output=True, text=True,
                          timeout=30, env=hostile)
    assert proc.returncode != 0
    assert "/tmp/evil" not in proc.stderr and "sshd" not in proc.stderr


def test_the_installer_refuses_an_unsafe_parent_directory():
    src = open(INSTALLER).read()
    assert "assert_safe_dir" in src
    for d in ("/usr/local", "/usr/local/lib", '"$ROOT_BIN"', '"$ROOT_LIB"'):
        assert f"assert_safe_dir {d}" in src, f"parent not checked: {d}"


def test_the_installer_is_not_reachable_from_the_runner_or_the_console():
    """Updating the machinery that performs deployments is a host action, never a deployment."""
    for module in (deploy.__file__,
                   os.path.join(os.path.dirname(deploy.__file__), "console.py")):
        assert "install-tc-deploy" not in open(module).read()
