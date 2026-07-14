"""Slice 8: read-only dashboard — rendering, escaping, and the GET-only invariant."""

from __future__ import annotations

import threading
import urllib.request
from http.server import ThreadingHTTPServer

from tc_growth import store
from tc_growth.dashboard import _Handler, render_case, render_overview


def _seeded(tmp_path):
    s = store.open_store(tmp_path / "d.db")
    s.seed_incident_case()
    s.log_run(kind="weekly-report", model="claude-sonnet-4-6",
              prompt_tokens=10_000, completion_tokens=2_000, summary="all quiet")
    s.record_decision(title="Keep 410", made_by="agent", status="proposed",
                      case_id=s.get_case_by_ref(store.INCIDENT_REF).id)
    return s


def test_overview_shows_cases_runs_costs_decisions(tmp_path):
    s = _seeded(tmp_path)
    page = render_overview(s)
    assert store.INCIDENT_REF in page
    assert "weekly-report" in page and "claude-sonnet-4-6" in page
    assert "$0.0" in page                       # cost rendered
    assert "Keep 410" in page and "proposed" in page
    s.close()


def test_case_page_renders_narrative_and_escapes_html(tmp_path):
    s = _seeded(tmp_path)
    case = s.get_case_by_ref(store.INCIDENT_REF)
    s.append_observation(case.id, "<script>alert(1)</script>", author="agent")
    page = render_case(s, store.INCIDENT_REF)
    assert "Merchant Center" in page
    assert "<script>" not in page               # injected content is escaped...
    assert "&lt;script&gt;" in page             # ...not dropped
    assert render_case(s, "NOPE-9") is None     # unknown -> 404 path
    s.close()


def test_server_serves_overview_and_is_get_only(tmp_path, monkeypatch):
    monkeypatch.setenv("TC_DB_PATH", str(tmp_path / "d.db"))
    _seeded(tmp_path).close()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            body = resp.read().decode()
        assert resp.status == 200 and store.INCIDENT_REF in body

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/case/{store.INCIDENT_REF}") as resp:
            assert "Merchant Center" in resp.read().decode()

        # READ-ONLY invariant: no mutating HTTP method exists on the handler at all.
        for method in ("do_POST", "do_PUT", "do_DELETE", "do_PATCH"):
            assert not hasattr(_Handler, method)

        # And a POST is rejected by the server (501 unsupported method).
        req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=b"x=1", method="POST")
        try:
            urllib.request.urlopen(req)
            raise AssertionError("POST should not succeed")
        except urllib.error.HTTPError as exc:
            assert exc.code == 501
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_production_banner_identity_is_red_and_read_only(monkeypatch):
    """WP-05 acceptance: the production identity must read 'Tossa Cycling · PRODUCTION',
    render on the red banner (#b32d2e), and carry the READ-ONLY PROFILE marker when the
    profile write cap is off. Staging stays amber. Unit-level evidence — no email, no run."""
    from tc_growth.dashboard import _site_banner

    monkeypatch.setenv("TC_SITE", "")
    monkeypatch.setenv("TC_SITE_NAME", "Tossa Cycling")
    monkeypatch.setenv("TC_ENV_KIND", "production")
    monkeypatch.setenv("TC_ALLOW_WRITES", "false")
    banner = _site_banner()
    assert "Tossa Cycling · PRODUCTION" in banner
    assert "#b32d2e" in banner                      # production = red, never amber
    assert "READ-ONLY PROFILE" in banner

    monkeypatch.setenv("TC_ENV_KIND", "staging")
    monkeypatch.setenv("TC_ALLOW_WRITES", "true")
    staging = _site_banner()
    assert "Tossa Cycling · STAGING" in staging
    assert "#996b00" in staging                     # staging = amber
    assert "READ-ONLY PROFILE" not in staging


def test_today_page_and_api(monkeypatch, tmp_path):
    """The owner's morning check: tiles + attention queue render; /api/today serves the same
    data as JSON. Read-only shell slice 1 (2026-07-13)."""
    import json
    import urllib.request

    from tc_growth import store as store_mod
    from tc_growth.dashboard import _Handler
    from http.server import ThreadingHTTPServer

    db = tmp_path / "today.db"
    monkeypatch.setenv("TC_DB_PATH", str(db))
    s = store_mod.open_store()
    s.create_case(ref="INC-1", title="watched", category="incident",
                  status="monitoring", opened_by="human")
    s.record_decision(title="Proposed thing", status="proposed", made_by="agent")
    s.record_decision(title="Approved thing", status="approved", made_by="human")
    s.close()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    import threading

    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/today").read().decode()
        assert "Needs your attention" in body
        assert "Proposed thing" in body               # needs-decision row
        assert "Approved thing" in body               # approved-awaiting-outcome row
        assert "profile (read-only view):" in body    # switcher present

        api = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/today").read())
        assert api["decisions_proposed"] == 1
        assert api["decisions_awaiting_outcome"] == 1
        assert api["cases_monitoring"] == 1

        profiles = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/profiles").read())
        assert "default" in profiles["profiles"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_profile_scoped_routes(monkeypatch, tmp_path):
    """/p/<name>/ serves that profile's store with its own banner; unknown profiles 404; a
    missing store renders a notice and is NEVER created by a GET (control-plane rules)."""
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    from pathlib import Path

    from tc_growth import store as store_mod
    from tc_growth.config import BASE_DIR
    from tc_growth.dashboard import _Handler

    # A production-shaped test profile with its own seeded store.
    db = tmp_path / "prodview.db"
    prof = Path(BASE_DIR) / "profiles" / "dashtest-production.env"   # *.env is gitignored
    prof.write_text(
        "TC_SITE_NAME=Tossa Cycling\nTC_ENV_KIND=production\nTC_ALLOW_WRITES=false\n"
        f"TC_DB_PATH={db}\n"
    )
    s = store_mod.SqliteStore(db)
    s.create_case(ref="PROD-1", title="prod-only case", category="incident",
                  status="monitoring", opened_by="human")
    s.close()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    import threading

    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        body = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/p/dashtest-production/").read().decode()
        assert "Tossa Cycling · PRODUCTION" in body
        assert "#b32d2e" in body                       # red banner for production context
        assert "READ-ONLY PROFILE" in body
        assert "PROD-1" in body                        # that profile's store, not the default's
        assert "/p/dashtest-production/case/PROD-1" in body   # links stay inside the context

        # Unknown profile -> 404, fail-closed.
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/p/nope/")
            raise AssertionError("unknown profile must 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404

        # Missing store: notice page, and the GET must not create the file.
        prof.write_text("TC_ENV_KIND=production\nTC_DB_PATH=" + str(tmp_path / "absent.db") + "\n")
        body2 = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/p/dashtest-production/").read().decode()
        assert "store not found" in body2
        assert not (tmp_path / "absent.db").exists()
    finally:
        httpd.shutdown()
        httpd.server_close()
        prof.unlink(missing_ok=True)


def test_decision_detail_view(monkeypatch, tmp_path):
    """Console slice 2: /decision/<id> is the 'why am I seeing this?' page — basis, status,
    outcome, linked case — and D#ids across Today/overview/case pages link to it."""
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    import threading

    from tc_growth import store as store_mod
    from tc_growth.dashboard import _Handler

    db = tmp_path / "dec.db"
    monkeypatch.setenv("TC_DB_PATH", str(db))
    s = store_mod.open_store()
    cid = s.create_case(ref="CASE-9", title="the case", category="incident",
                        status="monitoring", opened_by="human")
    did = s.record_decision(title="Serve 410 for spam", status="approved", made_by="human",
                            rationale="Spam URLs must return 410 and never redirect.",
                            case_id=cid)
    s.update_decision(did, outcome="worked")
    s.close()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/decision/{did}").read().decode()
        assert "Serve 410 for spam" in body
        assert "Basis / rationale" in body
        assert "never redirect" in body                 # the why
        assert "CASE-9" in body and "/case/CASE-9" in body
        assert "worked" in body                         # outcome shown

        # The overview's decision table links to the detail page.
        over = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert f"/decision/{did}" in over

        # Unknown decision -> 404.
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/decision/99999")
            raise AssertionError("unknown decision must 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
