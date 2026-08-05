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
    phases = [{"name": n, "status": "ok"} for n in deploy_acceptance.PHASE_ORDER]
    for i, name in enumerate(deploy_acceptance.PHASE_ORDER):
        poisoned = [dict(p) for p in phases]
        poisoned[i] = {"name": name, "status": "deferred"}
        assert acceptance_run.verdict(poisoned) == "BLOCKED", (
            f"a deferred {name} was represented as something other than BLOCKED")


def test_every_phase_ok_is_pass():
    phases = [{"name": n, "status": "ok"} for n in deploy_acceptance.PHASE_ORDER]
    assert acceptance_run.verdict(phases) == "PASS"


def test_an_incomplete_phase_record_is_blocked_not_pass():
    phases = [{"name": n, "status": "ok"} for n in deploy_acceptance.PHASE_ORDER[:-1]]
    assert acceptance_run.verdict(phases) == "BLOCKED"


def test_a_failure_with_green_safety_evidence_is_failed_safely():
    phases = [{"name": n, "status": "ok"} for n in deploy_acceptance.PHASE_ORDER]
    phases[deploy_acceptance.PHASE_ORDER.index("apply-file-phases")]["status"] = "failed"
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
              + [{"name": n, "status": "ok"} for n in deploy_acceptance.PHASE_ORDER])
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
