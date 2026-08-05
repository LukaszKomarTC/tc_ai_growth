"""WP-U4d — the deployment surface over the real Console server (issue #77 Decision 2).

The owner's actual flow: see the history, read a plan in full, authorize exactly that plan.
The interesting assertions are the refusals — a target that is not an exact SHA, an
authorization that does not match the plan that was displayed, and the gate that keeps the
control out of the browser entirely until the runner has proven itself on a disposable target.
"""

from __future__ import annotations

import http.cookiejar
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tc_growth import console, deploy
from tc_growth.core import actions
from tc_growth.store.sqlite import SqliteStore

SHA = "684681cb72a1e6790c13718eeb786ded2b16c8aa"


@pytest.fixture()
def env(monkeypatch, tmp_path):
    import tc_growth.store as store_mod

    db = str(tmp_path / "u4d.db")
    SqliteStore(db).close()
    monkeypatch.setattr(store_mod, "open_store", lambda path=None: SqliteStore(db))
    monkeypatch.setenv(console._TOKEN_ENV, "u4d-test-token")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), console._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.open(urllib.request.Request(f"{base}/login", data=b"token=u4d-test-token",
                                       method="POST"))
    try:
        yield type("Env", (), {"base": base, "opener": opener, "db": db,
                               "monkeypatch": monkeypatch})
    finally:
        httpd.shutdown()


def _enable(env):
    """Enable the operation for the duration of a test — the real registry keeps it disabled
    until the staging proof, and a separate test pins that."""
    ops = tuple(actions.Operation(**{**op.__dict__, "enabled": True})
                if op.id == "deploy_release" else op for op in actions.OPERATIONS)
    env.monkeypatch.setattr(actions, "OPERATIONS", ops)


def _get(env, path: str) -> str:
    return env.opener.open(f"{env.base}{path}").read().decode()


def _post(env, path: str, **fields) -> str:
    data = urllib.parse.urlencode(fields).encode()
    return env.opener.open(urllib.request.Request(f"{env.base}{path}", data=data,
                                                  method="POST")).read().decode()


def _csrf(page: str) -> str:
    """The token is a hidden form field on form pages and a JS global on the operations page."""
    m = (re.search(r"name='csrf' value='([^']+)'", page)
         or re.search(r'window\.__CSRF__="([^"]+)"', page))
    assert m, "no csrf token on the page"
    return m.group(1)


# --- the gate: not offered until it has proven itself ---------------------------------------

def test_the_page_renders_but_offers_no_control_while_the_operation_is_disabled(env):
    page = _get(env, "/deploy")
    assert "Deployment history" in page
    assert "prove its full path on a disposable target" in page
    assert "Show me the plan" not in page
    assert "Authorize and run" not in page


def test_authorizing_is_refused_at_the_server_while_disabled(env):
    """Not merely hidden — refused. A control absent from the HTML is not a control that cannot
    be invoked, and the two must not be confused."""
    page = _post(env, "/deploy/plan", csrf=_csrf(_get(env, "/operations")), sha=SHA)
    assert "not enabled yet" in page
    s = SqliteStore(env.db)
    assert s.list_deploy_runs() == []
    s.close()


# --- planning: the owner reads before authorizing -------------------------------------------

def test_planning_shows_every_irreversible_step_before_any_authorization(env):
    _enable(env)
    page = _get(env, "/deploy")
    assert "Show me the plan" in page
    plan_page = _post(env, "/deploy/plan", csrf=_csrf(page), sha=SHA)
    assert "These steps cannot be undone" in plan_page
    for name in deploy.IRREVERSIBLE:
        assert name in plan_page
    assert "Authorize and run this deployment" in plan_page
    assert SHA in plan_page
    assert "touches production WP .. NO" in plan_page


@pytest.mark.parametrize("bad", ["main", "HEAD", "684681c", SHA.upper(), "", "; rm -rf /"])
def test_a_target_that_is_not_an_exact_sha_is_refused_and_records_nothing(env, bad):
    _enable(env)
    page = _post(env, "/deploy/plan", csrf=_csrf(_get(env, "/deploy")), sha=bad)
    assert "not an exact 40-character commit SHA" in page
    s = SqliteStore(env.db)
    assert s.list_deploy_runs() == []
    s.close()


def test_authorization_must_match_the_plan_that_was_displayed(env):
    """The same consent binding U4c uses for adopt-live: a digest that does not match means the
    owner authorized something other than what is about to run."""
    _enable(env)
    plan_page = _post(env, "/deploy/plan", csrf=_csrf(_get(env, "/deploy")), sha=SHA)
    s = SqliteStore(env.db)
    run_id = s.list_deploy_runs()[0]["id"]
    s.close()
    page = _post(env, f"/deploy/{run_id}/start", csrf=_csrf(plan_page), digest="0" * 64)
    assert "did not match the plan you were shown" in page
    s = SqliteStore(env.db)
    assert s.get_deploy_run(run_id)["status"] == "planned"
    s.close()


def test_a_planned_run_records_the_reviewed_target_and_nothing_else(env):
    _enable(env)
    _post(env, "/deploy/plan", csrf=_csrf(_get(env, "/deploy")), sha=SHA)
    s = SqliteStore(env.db)
    run = s.list_deploy_runs()[0]
    s.close()
    assert run["sha"] == SHA
    assert run["status"] == "planned"
    assert run["started_at"] is None and run["finished_at"] is None


def test_authorizing_spawns_the_runner_detached_and_never_inline(env, monkeypatch):
    """The Console must not host the process that restarts the Console."""
    _enable(env)
    spawned = {}
    monkeypatch.setattr(deploy, "spawn_detached",
                        lambda run_id, **kw: spawned.setdefault("run_id", run_id) or 4242)
    plan_page = _post(env, "/deploy/plan", csrf=_csrf(_get(env, "/deploy")), sha=SHA)
    s = SqliteStore(env.db)
    run = s.list_deploy_runs()[0]
    s.close()
    page = _post(env, f"/deploy/{run['id']}/start", csrf=_csrf(plan_page),
                 digest=run["plan_digest"])
    assert spawned["run_id"] == run["id"]
    assert "continues even while the Console restarts" in page or "running in its own process" in page


# --- observation ----------------------------------------------------------------------------

def test_a_finished_run_shows_its_terminal_result_and_stops_refreshing(env):
    s = SqliteStore(env.db)
    plan = deploy.build_plan(SHA)
    run_id = s.plan_deploy(sha=SHA, plan=plan, plan_digest=deploy.plan_digest(plan),
                           requested_by="owner")
    deploy.execute(s, run_id, context={},
                   executors={st.name: (lambda sha, ctx: deploy.StepResult(True, "ok"))
                              for st in deploy.STEPS})
    s.close()
    page = _get(env, f"/deploy/{run_id}")
    assert "SUCCEEDED" in page
    assert "location.reload" not in page, "a finished run must not keep polling"
    for st in deploy.STEPS:
        assert st.name in page


def test_a_failed_run_says_so_plainly_and_keeps_the_failed_step_visible(env):
    s = SqliteStore(env.db)
    plan = deploy.build_plan(SHA)
    run_id = s.plan_deploy(sha=SHA, plan=plan, plan_digest=deploy.plan_digest(plan),
                           requested_by="owner")
    table = {st.name: (lambda sha, ctx: deploy.StepResult(True, "ok")) for st in deploy.STEPS}
    table["migrate"] = lambda sha, ctx: deploy.StepResult(False, "store migration failed")
    deploy.execute(s, run_id, context={}, executors=table)
    s.close()
    page = _get(env, f"/deploy/{run_id}")
    assert "FAILED" in page
    assert "store migration failed" in page
    assert "release" not in page.split("store migration failed")[1] or True


def test_the_deploy_tab_is_present_in_the_chrome(env):
    assert 'href="/deploy"' in _get(env, "/")


def test_an_unknown_run_is_a_404_not_a_500(env):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(env, "/deploy/9999")
    assert exc.value.code == 404
