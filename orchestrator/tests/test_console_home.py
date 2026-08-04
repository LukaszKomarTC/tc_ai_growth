"""U3b — the operator homepage answers the five Monday questions (WP-CONSOLE-USABILITY).

Views are pure functions taking the store + helpers, so these tests inject fakes: content rules
(five sections, honest empty states, the green nothing-waiting), the environment TRUTH PANEL
(separate source lines, never one label), display-time redaction, and escaping of every
store-sourced string (case titles and report bodies are attacker-influenceable)."""

from __future__ import annotations

import datetime as dt
import types

from tc_growth import console_views


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _fake_store(*, runs=(), cases_by_status=None, decisions=(), artifact=None):
    cbs = cases_by_status or {}
    return types.SimpleNamespace(
        list_runs=lambda kind=None, limit=20: [
            r for r in runs if kind is None or r.kind == kind][:limit],
        list_cases=lambda status=None, limit=50: list(cbs.get(status, []))[:limit],
        list_decisions=lambda limit=50: list(decisions)[:limit],
        latest_report_artifact=lambda kind=None: artifact,
    )


def _home(store) -> str:
    return console_views.home_body(store, profile="Tossa Cycling", env_kind="staging",
                                   wp_host="staging.tossacycling.com", allow_writes=False,
                                   redact=lambda t: t)


def test_empty_store_renders_all_five_sections_with_honest_empty_states():
    out = _home(_fake_store())
    for heading in ("Weekly report", "Attention (0)", "Decisions waiting (0)",
                    "Problems (0)", "Recent operations"):
        assert heading in out
    assert "No scheduled report run recorded yet." in out
    assert "No stored report artifact yet" in out
    assert "Nothing requires attention." in out
    assert "🟢 Nothing blocking you" in out                  # the all-clear status card (U3b.1)
    assert "🟢 Nothing waiting" in out                       # the empty-queue invariant, visible
    assert "None detected" in out
    # Hierarchy: status card is the FIRST element; the truth panel moved to the END (reference,
    # not action — reviewer, 2026-08-03).
    assert out.index("statuscard") < out.index("Weekly report")
    assert out.index("envtruth") > out.index("Recent operations")


def test_environment_truth_is_a_panel_of_separate_lines():
    out = _home(_fake_store())
    for line in ("Profile", "Operating environment", "Analytics", "WordPress",
                 "WooCommerce orders", "Production writes"):
        assert line in out
    assert "Production GSC/GA4 (read-only)" in out
    assert "staging.tossacycling.com" in out
    assert "not production truth (D#7)" in out
    assert "Disabled" in out                                  # allow_writes=False rendered


def test_populated_home_links_report_and_lists_queue():
    run = types.SimpleNamespace(id=28, kind="weekly-report", status="ok",
                                started_at=_now(), detail=None)
    art = types.SimpleNamespace(id=1, validator_ok=1, validator_reason=None,
                                delivery_status="delivered", delivery_attempts=1)
    case = types.SimpleNamespace(id=3, ref="INC-2026-02-01", title="Tobacco spam decay",
                                 status="monitoring", priority="medium",
                                 created_at=_now(), updated_at=_now())
    dec = types.SimpleNamespace(id=12, title="Approve tours hub", status="proposed",
                                made_at=_now(), rationale=None, impact=None, confidence=None)
    out = _home(_fake_store(runs=[run], cases_by_status={"monitoring": [case]},
                            decisions=[dec], artifact=art))
    assert "href='/report/1'" in out and "delivery delivered" in out
    assert "run#28" in out
    assert "INC-2026-02-01" in out and "Attention (1)" in out
    assert "D#12" in out and "Decisions waiting (1)" in out
    assert "🟢" not in out                                    # queue is not empty -> no green
    # U4c: the card is business-first — the headline leads, the queue count is context.
    assert "🔴 Action required — Approve tours hub" in out


def test_status_card_top_is_the_longest_waiting_decision():
    """Two proposed decisions: the card leads with the OLDEST (waited longest), and shows its
    rationale as the why-line — existing data only, no invented urgency."""
    old = types.SimpleNamespace(id=9, title="Apply bilingual SEO", status="proposed",
                                made_at="2026-08-01T10:00:00+00:00",
                                rationale="1,502 impressions at position 14.9",
                                impact='{"value": "+200 visits/mo", "label": "estimate"}',
                                confidence=None)
    new = types.SimpleNamespace(id=12, title="Newer thing", status="proposed",
                                made_at="2026-08-03T10:00:00+00:00", rationale=None,
                                impact=None, confidence=None)
    out = _home(_fake_store(decisions=[new, old]))
    assert "🔴 Action required — Apply bilingual SEO" in out    # oldest-waiting leads
    assert "2 decisions in the queue" in out
    assert "1,502 impressions at position 14.9" in out


def test_store_strings_are_escaped_everywhere():
    evil = "<script>alert(1)</script>"
    case = types.SimpleNamespace(id=9, ref=evil, title=evil, status="open", priority="high",
                                 created_at=_now(), updated_at=_now())
    out = _home(_fake_store(cases_by_status={"open": [case]}))
    assert "<script>" not in out and "&lt;script&gt;" in out


def test_report_view_shows_chain_metadata_and_redacts_at_display_time():
    art = types.SimpleNamespace(
        id=1, kind="weekly-report", run_id=28, window="2026-07-07 → 2026-08-03",
        generated_at=_now(), format_version="md/1", validator_version="1", validator_ok=1,
        validator_reason=None, content_sha256="ab" * 32, delivery_status="delivered",
        delivery_attempts=2, delivered_at=_now(),
        body="Report line with /var/www/vhosts/site/httpdocs/wp-content/uploads/x.php inside\n"
             "and <b>markup</b> that must not go live.")
    out = console_views.report_body(
        art, redact=lambda t: t.replace("/var/www/vhosts/site/httpdocs", "…"))
    assert ("ab" * 32) in out and "validated" in out
    assert "attempt\n" not in out and "attempt" in out and "delivered" in out
    assert "/var/www/" not in out                             # display-time redaction applied
    assert "…/wp-content/uploads/x.php" in out                # diagnostic tail preserved
    assert "<b>markup</b>" not in out and "&lt;b&gt;markup&lt;/b&gt;" in out


def test_rejected_artifact_is_labelled_rejected():
    art = types.SimpleNamespace(
        id=2, kind="weekly-report", run_id=29, window=None, generated_at=_now(),
        format_version="md/1", validator_version="1", validator_ok=0,
        validator_reason="incomplete_report_artifact:too_short", content_sha256="cd" * 32,
        delivery_status="send_failed", delivery_attempts=1, delivered_at=None,
        body="Good — narration only.")
    out = console_views.report_body(art, redact=lambda t: t)
    assert "REJECTED" in out and "too_short" in out


def test_cases_view_lists_and_escapes():
    case = types.SimpleNamespace(id=1, ref="TRK-1", title="<i>x</i>", status="resolved",
                                 priority="medium", created_at=_now(), updated_at=_now())
    store = types.SimpleNamespace(list_cases=lambda limit=50: [case])
    out = console_views.cases_body(store)
    assert "Cases (1)" in out and "TRK-1" in out
    assert "<i>x</i>" not in out and "&lt;i&gt;x&lt;/i&gt;" in out


def test_home_route_is_live_and_operations_moved(monkeypatch, tmp_path):
    """Route smoke over a real server: '/' renders the five-question home, '/operations' hosts
    the execute surface, '/report/<missing>' 404s cleanly — all behind the session."""
    import threading
    import urllib.request
    import urllib.error
    import http.cookiejar
    from http.server import ThreadingHTTPServer

    import tc_growth.store as store_mod
    from tc_growth import console
    from tc_growth.store.sqlite import SqliteStore

    # File-backed store: handler threads each open their own connection (sqlite connections are
    # thread-bound), exactly like production where every request calls open_store() fresh.
    db = str(tmp_path / "home.db")
    SqliteStore(db).close()  # create schema once
    monkeypatch.setattr(store_mod, "open_store", lambda: SqliteStore(db))
    monkeypatch.setenv(console._TOKEN_ENV, "home-test-token")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), console._Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        opener.open(urllib.request.Request(f"{base}/login", data=b"token=home-test-token",
                                           method="POST"))
        home = opener.open(f"{base}/").read().decode()
        assert "Decisions waiting" in home and "Weekly report" in home
        ops = opener.open(f"{base}/operations").read().decode()
        assert "SMTP delivery test" in ops and "window.__CSRF__" in ops
        try:
            opener.open(f"{base}/report/999")
            raise AssertionError("missing artifact must 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        httpd.shutdown()
