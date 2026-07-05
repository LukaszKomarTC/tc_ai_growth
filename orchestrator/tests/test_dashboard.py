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
