"""WP-U4d.2 — the Console-driven acceptance surface (Acceptance B, increment 1).

What these tests prove, and equally what they do not: this file drives the OWNER SURFACE — the
registered operation, its dual-layer refusal while disabled, CSRF, the two-step approval, the
no-values property, the durable phase stream, reconnection across a server restart, and the
closed verdict set. The ENGINE behind the launch is proven by `test_u4d2_privileged_boundary.py`
(root) and, for the six systemd phases, by the on-host run. Phases written here by hand stand in
for the root side of the launch — the wiring from the real engine to these rows is increment 2,
and nothing in this file claims otherwise.
"""

from __future__ import annotations

import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import tc_growth.store
from tc_growth import acceptance_run, console, deploy_acceptance
from tc_growth.core import actions
from tc_growth.core.actions import OPERATIONS, Operation
from tc_growth.store.sqlite import SqliteStore

TOKEN = "u4d2-test-token"


@pytest.fixture()
def env(monkeypatch, tmp_path):
    db = tmp_path / "console.db"
    SqliteStore(str(db)).close()
    monkeypatch.setattr(tc_growth.store, "open_store",
                        lambda path=None: SqliteStore(str(db)))
    monkeypatch.setenv(console._TOKEN_ENV, TOKEN)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), console._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    opener.open(f"{base}/login", data=f"token={TOKEN}".encode(), timeout=30)

    class Env:
        pass

    e = Env()
    e.base, e.opener, e.db, e.monkeypatch, e.httpd = base, opener, db, monkeypatch, httpd
    try:
        yield e
    finally:
        httpd.shutdown()


def _get(env, path: str) -> str:
    return env.opener.open(env.base + path, timeout=30).read().decode()


def _post(env, path: str, /, **fields) -> str:
    data = urllib.parse.urlencode(fields).encode()
    try:
        return env.opener.open(env.base + path, data=data, timeout=30).read().decode()
    except urllib.error.HTTPError as exc:
        return exc.read().decode()


def _csrf(env) -> str:
    """The session's CSRF token: from the acceptance form when offered, else from the
    /operations page's window.__CSRF__ global — the same two delivery paths the deploy tests
    scrape, needed because a disabled surface renders no form to scrape."""
    page = _get(env, "/acceptance")
    m = re.search(r"name='csrf' value='([^']+)'", page)
    if m is None:
        m = re.search(r'window\.__CSRF__="([^"]+)"', _get(env, "/operations"))
    assert m, "no csrf token found on /acceptance or /operations"
    return m.group(1)


def _enable(env):
    """Flip deploy_acceptance to enabled for this test only — the same rebuilt-tuple pattern
    the deploy tests use, because Operation is frozen and there is no setter."""
    rebuilt = tuple(
        Operation(**{**op.__dict__, "enabled": True}) if op.id == "deploy_acceptance" else op
        for op in OPERATIONS)
    env.monkeypatch.setattr(actions, "OPERATIONS", rebuilt)


def _store(env) -> SqliteStore:
    return SqliteStore(str(env.db))


# --- the operation is registered, and refused at BOTH layers while disabled -----------------

def test_the_page_renders_but_offers_no_control_while_disabled(env):
    page = _get(env, "/acceptance")
    assert "Acceptance history" in page
    assert "not enabled yet" in page
    assert "Run deployment acceptance</button>" not in page


def test_launching_is_refused_at_the_server_while_disabled(env):
    """Absent from the HTML is not the property — the POST itself must be refused. And it is
    refused BEFORE anything is written: no run row, no spawned process."""
    spawned = []
    env.monkeypatch.setattr(acceptance_run, "spawn_detached",
                            lambda run_id, **kw: spawned.append(run_id))
    page = _post(env, "/acceptance/run", csrf=_csrf(env), confirmed="1")
    assert "not enabled yet" in page
    store = _store(env)
    try:
        assert store.list_acceptance_runs() == []
    finally:
        store.close()
    assert spawned == []


def test_the_post_requires_csrf_even_when_enabled(env):
    _enable(env)
    try:
        env.opener.open(env.base + "/acceptance/run",
                        data=b"csrf=forged&confirmed=1", timeout=30)
        raise AssertionError("a forged csrf token was accepted")
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
    store = _store(env)
    try:
        assert store.list_acceptance_runs() == []
    finally:
        store.close()


# --- explicit approval, and the browser supplies nothing ------------------------------------

def test_approval_is_two_step_and_the_first_post_mutates_nothing(env):
    _enable(env)
    page = _post(env, "/acceptance/run", csrf=_csrf(env))
    assert "Confirm: run deployment acceptance" in page
    assert "name='confirmed' value='1'" in page
    store = _store(env)
    try:
        assert store.list_acceptance_runs() == []
    finally:
        store.close()


def test_the_confirmed_post_creates_the_run_with_a_server_derived_root(env):
    _enable(env)
    spawned = []
    env.monkeypatch.setattr(acceptance_run, "spawn_detached",
                            lambda run_id, **kw: spawned.append(run_id))
    _post(env, "/acceptance/run", csrf=_csrf(env), confirmed="1")
    store = _store(env)
    try:
        runs = store.list_acceptance_runs()
    finally:
        store.close()
    assert len(runs) == 1 and spawned == [runs[0]["id"]]
    run = runs[0]
    assert run["status"] == "requested"
    assert run["root"] == acceptance_run.derive_run_root(run["id"])
    assert run["root"].startswith(deploy_acceptance.SAFE_ACCEPTANCE_PARENT + "/")


def test_hostile_form_fields_change_nothing_about_the_run(env):
    """The form's only meaningful fields are csrf and confirmed. Paths, services, units, ports,
    users and command fragments in the request must leave no trace on the created run."""
    _enable(env)
    env.monkeypatch.setattr(acceptance_run, "spawn_detached", lambda run_id, **kw: None)
    injections = {
        "root": "/opt/tc_ai_growth/app", "path": "/etc/sudoers.d/pwn", "service": "sshd",
        "unit": "tc-console.service", "port": "8385", "user": "root",
        "command": "rm -rf /", "target": "production", "sha": "0" * 40,
    }
    _post(env, "/acceptance/run", csrf=_csrf(env), confirmed="1",
          **injections)
    store = _store(env)
    try:
        run = store.list_acceptance_runs()[0]
    finally:
        store.close()
    assert run["root"] == acceptance_run.derive_run_root(run["id"])
    assert run["requested_by"] == "owner"
    for hostile in injections.values():
        assert hostile not in (run["root"], run["requested_by"], run["summary"] or "")


def test_a_second_acceptance_while_one_is_live_is_refused_as_busy(env):
    _enable(env)
    env.monkeypatch.setattr(acceptance_run, "spawn_detached", lambda run_id, **kw: None)
    csrf = _csrf(env)
    _post(env, "/acceptance/run", csrf=csrf, confirmed="1")
    page = _post(env, "/acceptance/run", csrf=csrf, confirmed="1")
    assert "already live" in page
    store = _store(env)
    try:
        assert len(store.list_acceptance_runs()) == 1
    finally:
        store.close()


# --- the durable stream: phases render, and the record survives a Console restart -----------

def test_the_run_page_streams_phases_from_the_durable_record(env):
    _enable(env)
    env.monkeypatch.setattr(acceptance_run, "spawn_detached", lambda run_id, **kw: None)
    _post(env, "/acceptance/run", csrf=_csrf(env), confirmed="1")
    store = _store(env)
    try:
        run_id = store.list_acceptance_runs()[0]["id"]
        page = _get(env, f"/acceptance/{run_id}")
        assert "RUNNING" in page and "refreshes itself" in page
        # A second writer — the shape the detached runner has — appends phases; the page shows
        # them on the next read with no channel other than the store.
        store.claim_acceptance_run(run_id)
        store.record_acceptance_phase(run_id, seq=1, name="preflight-refuses-production",
                                      status="ok", detail="resolved before any mutation")
        store.record_acceptance_phase(run_id, seq=2, name="transient-unit", status="deferred")
        page = _get(env, f"/acceptance/{run_id}")
        assert "preflight-refuses-production" in page and "transient-unit" in page
        assert "deferred" in page
    finally:
        store.close()


def test_reconnection_after_a_console_restart_shows_the_same_run(env):
    """Kill the server, start a NEW one on the same store: the run page must show the identical
    durable state. This is the property that lets the operation survive the Console restart —
    there is no in-memory run state to lose."""
    _enable(env)
    env.monkeypatch.setattr(acceptance_run, "spawn_detached", lambda run_id, **kw: None)
    _post(env, "/acceptance/run", csrf=_csrf(env), confirmed="1")
    store = _store(env)
    try:
        run_id = store.list_acceptance_runs()[0]["id"]
        store.claim_acceptance_run(run_id)
        store.record_acceptance_phase(run_id, seq=1, name="launch", status="ok")
    finally:
        store.close()

    env.httpd.shutdown()
    httpd2 = ThreadingHTTPServer(("127.0.0.1", 0), console._Handler)
    threading.Thread(target=httpd2.serve_forever, daemon=True).start()
    try:
        base2 = f"http://127.0.0.1:{httpd2.server_address[1]}"
        opener2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        opener2.open(f"{base2}/login", data=f"token={TOKEN}".encode(), timeout=30)
        page = opener2.open(f"{base2}/acceptance/{run_id}", timeout=30).read().decode()
        assert "launch" in page and "RUNNING" in page
    finally:
        httpd2.shutdown()


# --- the verdict: a closed set that degrades toward BLOCKED, never toward PASS --------------

def _phases(**by_name):
    return [{"name": n, "status": s} for n, s in by_name.items()]


def test_no_phases_is_blocked_not_pass():
    assert acceptance_run.verdict([]) == "BLOCKED"


def test_a_deferred_phase_is_never_success():
    phases = [{"name": n, "status": "ok"} for n in acceptance_run.ALL_PHASES]
    for i, name in enumerate(acceptance_run.ALL_PHASES):
        poisoned = [dict(p) for p in phases]
        poisoned[i] = {"name": name, "status": "deferred"}
        assert acceptance_run.verdict(poisoned) == "BLOCKED", (
            f"a deferred {name} was represented as something other than BLOCKED")


def test_a_failed_self_check_is_blocked_not_pass():
    """A failed self-check is a trust/integration failure — BLOCKED, never FAILED SAFELY."""
    for check in acceptance_run.CHECK_ORDER:
        phases = [{"name": n, "status": "ok"} for n in acceptance_run.ALL_PHASES]
        phases[list(acceptance_run.ALL_PHASES).index(check)]["status"] = "failed"
        assert acceptance_run.verdict(phases) == "BLOCKED", (
            f"a failed {check} was not BLOCKED")


def test_every_phase_ok_is_pass():
    phases = [{"name": n, "status": "ok"} for n in acceptance_run.ALL_PHASES]
    assert acceptance_run.verdict(phases) == "PASS"


def test_engine_all_ok_but_a_check_missing_is_blocked():
    """PASS requires the self-checks too: engine-only green is not enough."""
    phases = [{"name": n, "status": "ok"} for n in deploy_acceptance.PHASE_ORDER]
    assert acceptance_run.verdict(phases) == "BLOCKED"


def test_an_incomplete_phase_record_is_blocked_not_pass():
    phases = [{"name": n, "status": "ok"} for n in list(acceptance_run.ALL_PHASES)[:-1]]
    assert acceptance_run.verdict(phases) == "BLOCKED"


def test_a_failure_with_green_safety_evidence_is_failed_safely():
    phases = _all_ok_phases()      # engine + self-checks all ok...
    phases[list(acceptance_run.ALL_PHASES).index("apply-file-phases")]["status"] = "failed"
    assert acceptance_run.verdict(phases) == "FAILED SAFELY"


def test_a_failure_without_safety_evidence_is_blocked_not_failed_safely():
    """A failure whose rollback or production-state phase did not land ok is UNRESOLVED — it
    must never be labelled 'safely'."""
    for safety in acceptance_run.SAFETY_PHASES:
        phases = [{"name": n, "status": "ok"} for n in deploy_acceptance.PHASE_ORDER]
        phases[deploy_acceptance.PHASE_ORDER.index("apply-file-phases")]["status"] = "failed"
        phases[deploy_acceptance.PHASE_ORDER.index(safety)]["status"] = "failed"
        assert acceptance_run.verdict(phases) == "BLOCKED", (
            f"a failure with {safety} itself failed was called FAILED SAFELY")


def test_a_failed_launch_alone_is_blocked():
    assert acceptance_run.verdict(_phases(launch="failed")) == "BLOCKED"


def test_a_retried_phase_is_judged_on_its_final_record():
    phases = ([{"name": "launch", "status": "failed"}]
              + [{"name": "launch", "status": "ok"}]
              + _all_ok_phases())
    assert acceptance_run.verdict(phases) == "PASS"


# --- the detached runner: an impossible launch ends BLOCKED, honestly -----------------------

def test_a_refused_escalation_finishes_the_run_blocked(env, tmp_path, monkeypatch):
    """Point the runner at a privileged entry that refuses (the truthful shape of a host whose
    machinery is not installed): the run must end BLOCKED with the refusal recorded, and the
    run page must show the closed verdict, not a success."""
    _enable(env)
    fake = tmp_path / "fake-privileged.sh"
    fake.write_text("#!/bin/bash\necho 'REFUSED: machinery is not installed' >&2\nexit 2\n")
    fake.chmod(0o755)

    class FakeProduction:
        privileged_entry = str(fake)

    from tc_growth import deploy_target
    monkeypatch.setattr(deploy_target, "PRODUCTION", FakeProduction())

    env.monkeypatch.setattr(acceptance_run, "spawn_detached", lambda run_id, **kw: None)
    _post(env, "/acceptance/run", csrf=_csrf(env), confirmed="1")
    store = _store(env)
    try:
        run_id = store.list_acceptance_runs()[0]["id"]
        # Run the real runner body in-process against the fake entry. `sudo -n` wraps it; if
        # sudo itself refuses (no grant on this machine) that is the same honest outcome.
        outcome = acceptance_run.execute(store, run_id)
        assert outcome == "blocked"
        run = store.get_acceptance_run(run_id)
        assert run["status"] == "done" and run["verdict"] == "BLOCKED"
        phases = store.list_acceptance_phases(run_id)
        assert [p["name"] for p in phases] == ["launch"]
        assert phases[0]["status"] == "failed"
    finally:
        store.close()
    page = _get(env, f"/acceptance/{run_id}")
    assert "BLOCKED" in page and "PASS" not in page


def test_the_runner_refuses_a_run_that_was_already_claimed(env):
    _enable(env)
    env.monkeypatch.setattr(acceptance_run, "spawn_detached", lambda run_id, **kw: None)
    _post(env, "/acceptance/run", csrf=_csrf(env), confirmed="1")
    store = _store(env)
    try:
        run_id = store.list_acceptance_runs()[0]["id"]
        assert store.claim_acceptance_run(run_id) is True
        with pytest.raises(deploy_acceptance.AcceptanceRefused):
            acceptance_run.execute(store, run_id)
        # The loser wrote nothing: no phases, no verdict, run still running.
        assert store.list_acceptance_phases(run_id) == []
        assert store.get_acceptance_run(run_id)["status"] == "running"
    finally:
        store.close()


# --- the engine's progress hook: phases flush as they happen, refusals included -------------

def test_the_progress_hook_receives_the_refusal_path_phases(tmp_path, monkeypatch):
    """Drive deploy_acceptance.run to an early refusal and prove the hook received every phase
    that landed BEFORE the refusal — the property a durable consumer needs, because the report
    dict itself dies with the exception. Off-root the refusal is the euid guard, which fires
    before any phase; the assertion is therefore exact: nothing streamed, nothing lost."""
    import os

    events = []
    if os.geteuid() != 0:
        with pytest.raises(deploy_acceptance.AcceptanceRefused):
            deploy_acceptance.run(tmp_path / "x", progress=lambda *a: events.append(a))
        assert events == []
    else:
        # As root: a poisoned resolver refuses after zero mutations and zero phase marks.
        original = tc_growth_resolve = None
        from tc_growth import deploy_harness
        original = deploy_harness.resolve_target

        def poisoned(root, **kw):
            target = original(root, **kw)
            object.__setattr__(target, "service", "tc-console")
            return target

        monkeypatch.setattr(deploy_harness, "resolve_target", poisoned)
        with pytest.raises(deploy_acceptance.AcceptanceRefused):
            deploy_acceptance.run(tmp_path / "x", progress=lambda *a: events.append(a))
        assert events == []


def test_the_phase_vocabulary_is_single_sourced():
    """The Console consumes deploy_acceptance.PHASE_ORDER — assert the engine's mark calls
    stay inside that vocabulary by construction: every SYSTEMD phase is in PHASE_ORDER, and
    the two safety phases the verdict requires exist in it."""
    assert set(deploy_acceptance.SYSTEMD_PHASES) <= set(deploy_acceptance.PHASE_ORDER)
    assert set(acceptance_run.SAFETY_PHASES) <= set(deploy_acceptance.PHASE_ORDER)
    assert len(deploy_acceptance.PHASE_ORDER) == len(set(deploy_acceptance.PHASE_ORDER))
    # ALL_PHASES is engine phases then self-checks, with no name collision between the two.
    assert acceptance_run.ALL_PHASES == tuple(deploy_acceptance.PHASE_ORDER) + acceptance_run.CHECK_ORDER
    assert len(acceptance_run.ALL_PHASES) == len(set(acceptance_run.ALL_PHASES))


# --- increment 2: the trust boundary — a positive verdict is unforgeable by tcgrowth --------

import os  # noqa: E402 - kept beside the trust tests that use it


def _all_ok_phases(offset: int = 2):
    """Every digested phase — engine phases AND self-checks — all ok, seq starting after the
    reserved launch slot. A positive verdict now requires the self-checks too, so the happy-path
    fixture must include them."""
    return [{"seq": i + offset, "name": n, "status": "ok"}
            for i, n in enumerate(acceptance_run.ALL_PHASES)]


def _write_receipt(tmp_path, run_id, phases, *, verdict="PASS", run_id_field=None,
                   target="disposable/vpsprobe", head="a" * 40):
    d = tmp_path / "receipts"
    d.mkdir(exist_ok=True)
    text = acceptance_run.render_receipt(
        run_id=run_id_field if run_id_field is not None else run_id, target=target,
        engine_head=head, phases=phases, verdict_value=verdict, completed_at="t")
    (d / f"{run_id}.receipt").write_text(text)
    return str(d)


def test_forged_rows_and_a_pass_column_without_a_receipt_report_blocked(env):
    """CRITERION 4, executed. Forge every phase ok AND stamp the store's verdict column PASS —
    without any privileged run — and the owner surface still reports BLOCKED, because no
    root-owned receipt attests it. This is the whole point of increment 2."""
    _enable(env)
    store = _store(env)
    try:
        run_id = store.begin_acceptance_run(requested_by="attacker", root="/x")
        store.claim_acceptance_run(run_id)
        for i, name in enumerate(acceptance_run.ALL_PHASES):
            store.record_acceptance_phase(run_id, seq=i + 2, name=name, status="ok")
        store.finish_acceptance_run(run_id, verdict="PASS", summary="forged")
    finally:
        store.close()
    page = _get(env, f"/acceptance/{run_id}")
    assert "BLOCKED" in page
    assert ">PASS<" not in page and "<b>PASS</b>" not in page


def test_the_pure_verdict_says_pass_but_the_trusted_verdict_needs_the_receipt():
    """The rows imply PASS, but with no receipt the trusted verdict is BLOCKED — the store's
    own opinion is not trusted."""
    phases = _all_ok_phases()
    run = {"id": 5, "status": "done"}
    assert acceptance_run.verdict(phases) == "PASS"
    assert acceptance_run.trusted_verdict(
        run, phases, receipts_dir="/nonexistent-receipts") == "BLOCKED"


def test_a_matching_root_receipt_yields_the_attested_verdict(tmp_path):
    phases = _all_ok_phases()
    run = {"id": 5, "status": "done"}
    d = _write_receipt(tmp_path, 5, phases, verdict="PASS")
    assert acceptance_run.trusted_verdict(
        run, phases, receipts_dir=d, require_root_owned=False) == "PASS"


def test_a_receipt_whose_verdict_the_rows_do_not_support_is_blocked(tmp_path):
    """A receipt claiming PASS while the rows show a failed phase is a contradiction; the
    Console trusts neither side over the other and reports BLOCKED."""
    phases = _all_ok_phases()
    phases[3]["status"] = "failed"          # rows now imply not-PASS
    run = {"id": 5, "status": "done"}
    d = _write_receipt(tmp_path, 5, phases, verdict="PASS")   # digest still matches these rows
    assert acceptance_run.trusted_verdict(
        run, phases, receipts_dir=d, require_root_owned=False) == "BLOCKED"


def test_a_receipt_bound_to_another_run_id_is_blocked(tmp_path):
    """CRITERION 5. A receipt whose content names a different run does not validate for this one,
    even placed at this run's path."""
    phases = _all_ok_phases()
    run = {"id": 5, "status": "done"}
    d = _write_receipt(tmp_path, 5, phases, verdict="PASS", run_id_field=7)
    assert acceptance_run.trusted_verdict(
        run, phases, receipts_dir=d, require_root_owned=False) == "BLOCKED"


def test_a_receipt_whose_digest_does_not_match_the_rows_is_blocked(tmp_path):
    """A receipt sealed over one set of phases cannot validate a substituted set — the digest is
    the binding."""
    sealed = _all_ok_phases()
    run = {"id": 5, "status": "done"}
    d = _write_receipt(tmp_path, 5, sealed, verdict="PASS")
    substituted = _all_ok_phases()
    substituted[2]["status"] = "deferred"    # different rows -> different digest
    assert acceptance_run.trusted_verdict(
        run, substituted, receipts_dir=d, require_root_owned=False) == "BLOCKED"


def test_a_failed_safely_receipt_is_shown_only_when_attested(tmp_path):
    phases = _all_ok_phases()
    phases[deploy_acceptance.PHASE_ORDER.index("apply-file-phases")]["status"] = "failed"
    run = {"id": 5, "status": "done"}
    assert acceptance_run.verdict(phases) == "FAILED SAFELY"
    assert acceptance_run.trusted_verdict(
        run, phases, receipts_dir="/nonexistent") == "BLOCKED"       # unattested
    d = _write_receipt(tmp_path, 5, phases, verdict="FAILED SAFELY")
    assert acceptance_run.trusted_verdict(
        run, phases, receipts_dir=d, require_root_owned=False) == "FAILED SAFELY"


def test_a_blocked_receipt_never_becomes_positive(tmp_path):
    """A receipt that itself records BLOCKED cannot yield a positive display, whatever the
    rows say."""
    phases = _all_ok_phases()
    run = {"id": 5, "status": "done"}
    d = _write_receipt(tmp_path, 5, phases, verdict="BLOCKED")
    assert acceptance_run.trusted_verdict(
        run, phases, receipts_dir=d, require_root_owned=False) == "BLOCKED"


def test_a_running_run_shows_no_verdict_yet(tmp_path):
    phases = _all_ok_phases()
    run = {"id": 5, "status": "running"}
    _write_receipt(tmp_path, 5, phases, verdict="PASS")     # even if a receipt somehow existed
    assert acceptance_run.trusted_verdict(run, phases) is None


@pytest.mark.skipif(os.geteuid() != 0, reason="root-ownership anchor can only be built as root")
def test_the_ownership_anchor_rejects_a_non_root_receipt(root_base):
    """On a real host the receipt must be OWNED BY ROOT — a file the service account could have
    written is no attestation. Build a root-owned receipt (accepted), then chown it away from
    root (rejected)."""
    import pwd
    phases = _all_ok_phases()
    run = {"id": 5, "status": "done"}
    d = str(root_base / "r")
    acceptance_run.write_receipt_as_root(
        5, target="t", engine_head="a" * 40, phases=phases, verdict_value="PASS",
        completed_at="t", receipts_dir=d)
    assert acceptance_run.trusted_verdict(run, phases, receipts_dir=d) == "PASS"
    non_root = next((pwd.getpwnam(n).pw_uid for n in ("nobody", "daemon", "bin")
                     if _uid_exists(n)), None)
    assert non_root is not None
    os.chown(acceptance_run.receipt_path(5, receipts_dir=d), non_root, non_root)
    assert acceptance_run.trusted_verdict(run, phases, receipts_dir=d) == "BLOCKED"


def _uid_exists(name):
    import pwd
    try:
        pwd.getpwnam(name)
        return True
    except KeyError:
        return False


@pytest.fixture()
def root_base():
    """A root-owned, non-world-writable base for receipt tests. pytest's tmp_path lives under
    /tmp (1777), which write_receipt_as_root's ancestor check correctly refuses, so the write
    tests need a base whose whole chain to / is root-owned. /root is root:root 0700."""
    import shutil
    import tempfile
    base = tempfile.mkdtemp(prefix="tc-u4d2-receipts-", dir="/root")
    try:
        yield Path(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_write_receipt_as_root_refuses_when_not_root(tmp_path, monkeypatch):
    if os.geteuid() == 0:
        monkeypatch.setattr(acceptance_run.os, "geteuid", lambda: 1000)
    with pytest.raises(deploy_acceptance.AcceptanceRefused):
        acceptance_run.write_receipt_as_root(
            5, target="t", engine_head="a" * 40, phases=_all_ok_phases(),
            verdict_value="PASS", completed_at="t", receipts_dir=str(tmp_path / "r"))


@pytest.mark.skipif(os.geteuid() != 0, reason="building root-owned trees requires root")
def test_receipt_creation_refuses_a_symlinked_path(root_base):
    """CRITERION 5: root must not be tricked into writing the receipt through a planted symlink.
    Pre-create the receipt path as a symlink to an outside file; the O_NOFOLLOW write refuses,
    and the outside target is left untouched."""
    d = root_base / "receipts"
    d.mkdir()
    outside = root_base / "outside.txt"
    outside.write_text("original")
    os.symlink(outside, acceptance_run.receipt_path(5, receipts_dir=str(d)))
    with pytest.raises(OSError):
        acceptance_run.write_receipt_as_root(
            5, target="t", engine_head="a" * 40, phases=_all_ok_phases(),
            verdict_value="PASS", completed_at="t", receipts_dir=str(d))
    assert outside.read_text() == "original", "root wrote through the symlink"


@pytest.mark.skipif(os.geteuid() != 0, reason="building root-owned trees requires root")
def test_receipt_creation_refuses_a_non_root_ancestor(root_base):
    """CRITERION 5: an ancestor the service account could control is refused, not written under."""
    import pwd
    non_root = next((pwd.getpwnam(n).pw_uid for n in ("nobody", "daemon", "bin")
                     if _uid_exists(n)), None)
    assert non_root is not None
    parent = root_base / "attacker"
    parent.mkdir()
    os.chown(parent, non_root, non_root)         # an ancestor the attacker owns
    with pytest.raises(deploy_acceptance.AcceptanceRefused, match="not root-owned"):
        acceptance_run.write_receipt_as_root(
            5, target="t", engine_head="a" * 40, phases=_all_ok_phases(),
            verdict_value="PASS", completed_at="t", receipts_dir=str(parent / "receipts"))


@pytest.mark.skipif(os.geteuid() != 0, reason="building root-owned trees requires root")
def test_receipt_creation_refuses_a_symlinked_receipts_dir(root_base):
    """CRITERION 5: the receipts directory itself being a symlink is refused."""
    real = root_base / "real"
    real.mkdir()
    link = root_base / "receipts"
    os.symlink(real, link)
    with pytest.raises(deploy_acceptance.AcceptanceRefused, match="symlink"):
        acceptance_run.write_receipt_as_root(
            5, target="t", engine_head="a" * 40, phases=_all_ok_phases(),
            verdict_value="PASS", completed_at="t", receipts_dir=str(link))


def test_a_successful_launch_leaves_no_positive_verdict_for_the_launcher_to_forge(env, monkeypatch):
    """CRITERION 6. If the escalation returns 0 but (as here) the root side did not actually
    finish the run, the unprivileged launcher records only the launch phase and finalises
    nothing — the run stays unfinished and the surface shows RUNNING, never a forged PASS."""
    _enable(env)
    monkeypatch.setattr(acceptance_run.subprocess, "run",
                        lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "ok",
                                                       "stderr": ""})())
    monkeypatch.setattr(acceptance_run, "spawn_detached", lambda run_id, **kw: None)
    _post(env, "/acceptance/run", csrf=_csrf(env), confirmed="1")
    store = _store(env)
    try:
        run_id = store.list_acceptance_runs()[0]["id"]
        outcome = acceptance_run.execute(store, run_id)
        assert outcome == "launched"
        run = store.get_acceptance_run(run_id)
        assert run["status"] == "running" and run["verdict"] is None
        # Only the launch phase; no engine phases, so the trusted verdict is not positive.
        phases = store.list_acceptance_phases(run_id)
        assert [p["name"] for p in phases] == ["launch"]
        assert acceptance_run.trusted_verdict(run, phases) is None
    finally:
        store.close()


def _stub_engine(monkeypatch):
    def fake_run(root, *, keep=False, progress=None):
        for name in deploy_acceptance.PHASE_ORDER:
            progress(name, "ok", "")
        return {"target_name": "disposable/vpsprobe", "target_sha": "b" * 40,
                "executed": list(deploy_acceptance.PHASE_ORDER), "deferred": [], "steps": {}}
    monkeypatch.setattr(deploy_acceptance, "run", fake_run)


@pytest.mark.skipif(os.geteuid() != 0, reason="execute_as_root seals a root-owned receipt")
def test_execute_as_root_off_host_records_checks_and_is_blocked(env, root_base, monkeypatch):
    """Off-host (no systemd), the runner still performs its self-checks and records them, seals a
    receipt, and finishes BLOCKED — because the restart-reconnect check defers without a booted
    service manager. The honest outcome: no on-host proof, no PASS."""
    _enable(env)
    _stub_engine(monkeypatch)
    receipts = str(root_base / "receipts")
    store = _store(env)
    try:
        run_id = store.begin_acceptance_run(requested_by="owner", root=str(root_base / "run"))
        store.claim_acceptance_run(run_id)
        outcome = acceptance_run.execute_as_root(
            store, run_id, receipts_dir=receipts, scratch_dir=root_base / "scratch")
        assert outcome == "BLOCKED"
        phases = store.list_acceptance_phases(run_id)
        names = [p["name"] for p in phases]
        # Both engine phases and self-checks are recorded as durable evidence.
        assert acceptance_run.CHECK_ATTESTATION in names
        assert acceptance_run.CHECK_RESTART_RECONNECT in names
        by_name = {p["name"]: p["status"] for p in phases}
        assert by_name[acceptance_run.CHECK_ATTESTATION] == "ok"      # forgery battery passed
        assert by_name[acceptance_run.CHECK_RESTART_RECONNECT] == "deferred"
        run = store.get_acceptance_run(run_id)
        assert acceptance_run.trusted_verdict(run, phases, receipts_dir=receipts) == "BLOCKED"
    finally:
        store.close()


@pytest.mark.skipif(os.geteuid() != 0, reason="execute_as_root seals a root-owned receipt")
def test_execute_as_root_passes_when_every_phase_and_check_is_green(env, root_base, monkeypatch):
    """The wiring for a clean run: with the systemd-bound and store-ownership checks satisfied and
    the runtime references supplied, execute_as_root aggregates engine phases + self-checks into
    an attested PASS and seals the receipt. (The systemd/ownership checks are what the on-host run
    exercises for real; here they are stubbed so the aggregation itself is proven.)"""
    _enable(env)
    _stub_engine(monkeypatch)
    monkeypatch.setattr(acceptance_run, "verify_store_ownership",
                        lambda *a, **k: ("ok", "stubbed: service account can write"))
    monkeypatch.setattr(acceptance_run, "verify_restart_reconnect",
                        lambda *a, **k: ("ok", "stubbed: run record survived restart"))
    receipts = str(root_base / "receipts")
    store = _store(env)
    try:
        run_id = store.begin_acceptance_run(requested_by="owner", root=str(root_base / "run"))
        store.claim_acceptance_run(run_id)
        outcome = acceptance_run.execute_as_root(
            store, run_id, receipts_dir=receipts, scratch_dir=root_base / "scratch",
            resolved_head="b" * 40, resolved_target="disposable/vpsprobe")
        assert outcome == "PASS"
        run = store.get_acceptance_run(run_id)
        assert run["status"] == "done"
        phases = store.list_acceptance_phases(run_id)
        assert acceptance_run.trusted_verdict(run, phases, receipts_dir=receipts) == "PASS"
        # The receipt binds the independently-resolved head/target.
        receipt = acceptance_run.read_trusted_receipt(run_id, phases, receipts_dir=receipts)
        assert receipt["engine_head"] == "b" * 40
        assert receipt["target"] == "disposable/vpsprobe"
    finally:
        store.close()
