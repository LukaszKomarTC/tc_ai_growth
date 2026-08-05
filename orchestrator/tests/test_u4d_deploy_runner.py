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
    # The rollback text names the VERB, not `--rollback`: increment 2 replaced the release
    # script's flag interface with a fixed-verb privileged program, and a plan that still
    # described the old flag would be telling the owner about a path that no longer exists.
    assert "rollback" in plan and "`rollback` verb" in plan["rollback"]
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
    # WHICH refusal fires is the scheduler's choice, not the code's: if the loser is descheduled
    # after the barrier for long enough, the winner's claim has already committed by the time the
    # loser reads the row, so it trips the `not planned` read instead of the claim. Both are
    # correct and both mean one deployment. Asserting the claim specifically made this test fail
    # under CPU load — it was asserting an OS scheduling outcome. The claim path itself is proven
    # deterministically by the test below, which reproduces the interleave rather than hoping for
    # it. What must hold HERE, whichever path fires, is one winner and a loser that ran nothing.
    assert ("already claimed" in str(losers[0])
            or "not planned" in str(losers[0])), f"unexpected refusal: {losers[0]}"

    # The loser ran NO executor: every recorded step belongs to the same runner.
    assert len(set(ran)) == 1, f"both runners executed steps: {ran}"
    assert len(ran) == len(deploy.STEPS)


def test_when_both_runners_pass_the_planned_read_the_claim_is_what_excludes_one(store):
    """The interleave the racing test above can only hope for, reproduced deterministically.

    Both runners read `planned` — the loser's read is served from a snapshot taken before the
    winner claimed, which is exactly what a second detached runner sees when its SELECT lands in
    the window between the winner's SELECT and the winner's UPDATE. The earlier read therefore
    cannot exclude anybody here, and if the atomic claim were removed this test would run the
    executors twice.
    """
    run_id, _ = _plan(store)
    stale = store.get_deploy_run(run_id)              # the pre-claim snapshot: status == planned
    assert stale["status"] == "planned"

    assert store.start_deploy_run(run_id, pid=4242) is True   # the winner claims it
    assert store.get_deploy_run(run_id)["status"] == "running"

    class ReadsTheStaleRow:
        """The loser's connection: every write is real, only its row read is from the window."""

        def __init__(self, inner):
            self._inner = inner

        def get_deploy_run(self, rid):
            return stale if rid == run_id else self._inner.get_deploy_run(rid)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    ran: list[str] = []

    def records(name):
        def _run(sha, ctx):
            ran.append(name)
            return deploy.StepResult(True, "ok")
        return _run

    executors = {st.name: records(st.name) for st in deploy.STEPS}

    with pytest.raises(deploy.DeployRefused) as exc:
        deploy.execute(ReadsTheStaleRow(store), run_id, context={}, executors=executors)

    assert "already claimed" in str(exc.value)
    assert ran == [], f"the loser ran executors: {ran}"
    # And it neither recorded a step nor overwrote the winner's claim.
    assert store.list_deploy_steps(run_id) == []
    run = store.get_deploy_run(run_id)
    assert run["status"] == "running" and run["runner_pid"] == 4242


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


# --- WP-U4d permission predicate (PR #79, reduced scope) -------------------------------------
#
# The privileged helper and installer these were written for are WITHDRAWN from PR #79 — their
# root execution chain was unsafe. The predicate itself is finished and proven, and lives alone
# in scripts/lib/permission-guard.sh until the redesigned helper sources it.

GUARD = os.path.join(os.path.dirname(os.path.dirname(deploy.__file__)),
                     "scripts", "lib", "permission-guard.sh")


def _run_predicate(mode: str, tmp_path) -> bool:
    """Execute the ACTUAL shell function against a real path with a real mode.

    Source-string assertions could not have caught the original defect — the broken glob *looked*
    correct, and my earlier tests asserted only that a guard existed and mentioned ownership.
    Only running it against 0777 finds it.
    """
    target = tmp_path / f"probe-{mode}"
    target.mkdir()
    os.chmod(target, int(mode, 8))
    script = (open(GUARD).read() + "\n"
              'm="$(stat -c %a "$1")"\n'
              'if mode_has_write_bits "$m"; then echo UNSAFE; else echo SAFE; fi\n')
    proc = subprocess.run(["bash", "-c", script, "bash", str(target)],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip() == "SAFE"


@pytest.mark.parametrize("mode", ["777", "775", "757", "733", "722", "702", "707", "770",
                                  "666", "622", "606", "660"])
def test_every_group_or_other_writable_mode_is_REJECTED(mode, tmp_path):
    """The old glob `[0-7][0-57][0-57]` accepted 2, 3 and 7 in either position, so 0777 passed a
    check whose error message claimed it rejected exactly that."""
    assert not _run_predicate(mode, tmp_path), f"mode {mode} was accepted but is writable"


@pytest.mark.parametrize("mode", ["755", "750", "700", "644", "640", "600", "555", "500"])
def test_safe_modes_are_ACCEPTED(mode, tmp_path):
    assert _run_predicate(mode, tmp_path), f"mode {mode} was rejected but is safe"


def test_a_malformed_or_empty_mode_is_treated_as_unsafe():
    """Fail closed: if the mode cannot be read or is not octal, refuse rather than assume."""
    script = (open(GUARD).read() + "\n"
              'if mode_has_write_bits "$1"; then echo UNSAFE; else echo SAFE; fi\n')
    for bogus in ("", "abc", "9", "75x", "0o755"):
        proc = subprocess.run(["bash", "-c", script, "bash", bogus],
                              capture_output=True, text=True, timeout=30)
        assert proc.stdout.strip() == "UNSAFE", f"{bogus!r} was treated as safe"


def test_the_privileged_bootstrap_predicate_agrees_with_the_merged_guard_on_every_mode():
    """The privileged program cannot source the guard to decide whether sourcing it is safe, so it
    carries its own copy of the predicate for that one bootstrap check.

    Duplication in a security check is how the `[0-57]` defect survived: two spellings, one of
    them wrong, and nothing comparing them. This runs BOTH implementations over all 512 modes and
    requires identical verdicts, which turns the duplication into a proven equivalence.

    Runs unprivileged — it compares two shell functions and needs no root.
    """
    privileged = os.path.join(os.path.dirname(os.path.dirname(GUARD)),
                              "tc-deploy-privileged.sh")
    bootstrap = subprocess.run(
        ["sed", "-n", "/^_bootstrap_mode_is_unsafe() {/,/^}/p", privileged],
        capture_output=True, text=True, timeout=30).stdout
    assert "8#22" in bootstrap, "the bootstrap predicate was not extracted"

    script = (open(GUARD).read() + "\n" + bootstrap + "\n"
              'for m in $(seq -w 0 777); do\n'
              '  case "$m" in *[!0-7]*) continue ;; esac\n'
              '  a=no; b=no\n'
              '  mode_has_write_bits "$m" && a=yes\n'
              '  _bootstrap_mode_is_unsafe "$m" && b=yes\n'
              '  [ "$a" = "$b" ] || echo "DISAGREE $m guard=$a bootstrap=$b"\n'
              'done\n'
              'echo DONE\n')
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    disagreements = [ln for ln in proc.stdout.splitlines() if ln.startswith("DISAGREE")]
    assert not disagreements, disagreements
    assert "DONE" in proc.stdout


def test_the_predicate_does_not_encode_write_bits_with_a_character_range():
    """Checked on CODE only — the comment legitimately quotes the broken range while explaining
    why it was wrong, and forbidding the explanation would push the reasoning out of the file."""
    code = [ln for ln in open(GUARD).read().splitlines() if not ln.strip().startswith("#")]
    assert not any("[0-57]" in ln for ln in code)


def test_the_withdrawn_wrapper_design_never_returns():
    """PR #79 withdrew `tc-deploy-release.sh`: a wrapper around the existing deploy script, which
    left root executing service-user-writable code one process hop downstream.

    This test used to assert that the installer was absent too, because at that moment NOTHING
    privileged was shipping and an absent installer was the honest state. WP-U4d.1 increment 2
    ships a privileged program deliberately, so that half is now asserted the other way round in
    `test_u4d2_privileged_boundary.py`. What must never come back is the *wrapper design* — the
    one whose boundary ended a process too early.
    """
    import ast

    scripts = os.path.dirname(os.path.dirname(GUARD))
    assert not os.path.exists(os.path.join(scripts, "tc-deploy-release.sh")), \
        "the withdrawn wrapper is back; its boundary was never safe"

    # Checked on argv literals, not on the text. `ex_release`'s docstring legitimately names the
    # old script while explaining why root no longer runs it, and forbidding the explanation
    # would push the reasoning out of the file — the same trade the permission-guard test makes.
    for node in ast.walk(ast.parse(open(deploy.__file__).read())):
        if isinstance(node, ast.List):
            words = [e.value for e in node.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            assert not any("deploy-console.sh" in w for w in words), \
                f"the runner builds a command that runs the release checkout's script: {words}"


def test_the_runner_escalates_exactly_once():
    """Criterion 1, checked on the PARSED code so a comment mentioning sudo cannot change the
    answer. Every escalation in the runner must be the single verb call to the privileged entry
    point — two `sudo` sites is precisely the over-escalation defect 1 named."""
    import ast

    escalations = []
    for node in ast.walk(ast.parse(open(deploy.__file__).read())):
        if isinstance(node, ast.List) and node.elts:
            first = node.elts[0]
            if isinstance(first, ast.Constant) and first.value == "sudo":
                escalations.append(ast.unparse(node))
    assert len(escalations) == 1, f"expected exactly one escalation, found {escalations}"
    assert "privileged_entry" in escalations[0], escalations[0]
    assert "'apply'" in escalations[0] and "'-n'" in escalations[0], escalations[0]
