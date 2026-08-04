"""WP-U4a — the decision detail page and the browser approve/reject flow.

View tests hit the pure functions with real store rows; the end-to-end tests run the actual
Console server over a file-backed store, exactly as deployed. Proven here, per the PR #69
acceptance criteria: owner-readable ordering (recommendation before technicals), the genuine
two-step approve, reject-with-reason, CSRF/session enforcement, stale-revision refusal, legacy
decisions rendered unapprovable with a plain reason — and that NO control overstates authority
(no Apply/Execute/Verify anywhere in U4a).
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

from tc_growth import console, console_views
from tc_growth.store.sqlite import SqliteStore


def _envelope() -> dict:
    return {
        "schema_version": "u4/1",
        "profile": "tossa-cycling",
        "environment": "production",
        "kind": "seo_meta_update",
        "target": {"object_type": "wp_post", "post_id": 13699,
                   "expected_urls": {
                       "es": "https://www.tossacycling.com/alquiler_bicicletas/",
                       "en": "https://www.tossacycling.com/en/alquiler_bicicletas/"}},
        "payload": {"title_es": "Alquiler de bicicletas en Tossa de Mar"},
    }


def _seed(store: SqliteStore) -> int:
    return store.propose_decision(
        title="Bilingual SEO for the rental page", envelope=_envelope(),
        expected_profile="tossa-cycling", allowed_environments=("production",),
        allowed_hosts=("www.tossacycling.com",),
        rationale="1,502 impressions at position 14.9 — title/meta rewrite lifts CTR",
        evidence="report artifact #1 · GSC query export",
        impact={"value": "+200–500 visits/mo", "label": "estimate",
                "method": "GSC position/CTR heuristic", "source": "report artifact #1",
                "as_of": "2026-08-03"},
        confidence={"value": "medium", "label": "estimate",
                    "method": "single-source heuristic", "source": "report artifact #1",
                    "as_of": "2026-08-03"})


# --- view rules ---------------------------------------------------------------------------------


def test_detail_reads_owner_first_then_technical():
    s = SqliteStore(":memory:")
    did = _seed(s)
    out = console_views.decision_body(s.get_decision(did), s.list_decision_events(did),
                                      csrf="tok")
    order = [out.index(x) for x in ("Recommendation", "Evidence",
                                    "Expected impact / confidence",
                                    "The exact proposed change", "Actions",
                                    "History &amp; integrity")]
    assert order == sorted(order)
    assert "1,502 impressions" in out
    # Provenance renders with its label — never a bare number presented as fact.
    assert "+200–500 visits/mo" in out and "estimate" in out
    assert "GSC position/CTR heuristic" in out
    # The exact change: payload values and target URLs verbatim (escaped).
    assert "Alquiler de bicicletas en Tossa de Mar" in out
    assert "https://www.tossacycling.com/alquiler_bicicletas/" in out
    assert "PRODUCTION" in out                                 # environment is unmissable
    # Technical trail present, after the human part.
    assert s.get_decision(did).envelope_sha256 in out
    assert "propose" in out


def test_missing_provenance_renders_unknown_never_invented():
    s = SqliteStore(":memory:")
    did = s.propose_decision(title="No numbers", envelope=_envelope(),
                             expected_profile="tossa-cycling",
                             allowed_environments=("production",),
                             allowed_hosts=("www.tossacycling.com",))
    out = console_views.decision_body(s.get_decision(did), [], csrf="t")
    assert out.count("unknown") >= 2                           # impact AND confidence


def test_no_control_overstates_authority():
    """No control may claim a capability whose acceptance has not happened (spec:
    eliminated-actions table). Apply/Execute stay forbidden EVERYWHERE — the platform never
    writes to production. Verify became a registered capability in U4b, but only for approved
    decisions of verifiable kinds; without a registered path, only the plain 'not available'
    reason may render, never a button."""
    s = SqliteStore(":memory:")
    did = _seed(s)
    for status_fixture in ("proposed", "approved"):
        if status_fixture == "approved":
            s.approve_decision(did, expected_revision=0)
        out = console_views.decision_body(s.get_decision(did),
                                          s.list_decision_events(did), csrf="t")
        for forbidden in (">Apply", ">Execute"):
            assert forbidden not in out
        # verifiable=False (no registered path): the reason renders, a control never does.
        assert "/verify" not in out
        if status_fixture == "proposed":
            assert "Verify live change" not in out             # approve first, always


def test_legacy_decision_shows_plain_reason_and_no_forms():
    s = SqliteStore(":memory:")
    lid = s.record_decision(title="Pre-U4 decision", status="proposed")
    out = console_views.decision_body(s.get_decision(lid), [], csrf="t")
    assert "predates the approval workflow" in out
    assert "<form" not in out


def test_store_strings_are_escaped_on_the_detail_page():
    evil = "<script>alert(1)</script>"
    s = SqliteStore(":memory:")
    env = _envelope()
    env["payload"] = {"title_es": evil}
    did = s.propose_decision(title=evil, envelope=env, rationale=evil, evidence=evil,
                             expected_profile="tossa-cycling",
                             allowed_environments=("production",),
                             allowed_hosts=("www.tossacycling.com",))
    out = console_views.decision_body(s.get_decision(did), s.list_decision_events(did),
                                      csrf="t")
    assert "<script>" not in out and "&lt;script&gt;" in out


def test_confirm_page_shows_environment_and_binding_envelope():
    s = SqliteStore(":memory:")
    did = _seed(s)
    out = console_views.decision_confirm_body(s.get_decision(did), csrf="t")
    assert "approving this for" in out and "PRODUCTION" in out
    assert "Nothing is executed by approving." in out
    assert "confirmed" in out and "Confirm approval" in out
    assert "Cancel" in out


# --- end-to-end over the real server ------------------------------------------------------------


@pytest.fixture()
def console_env(monkeypatch, tmp_path):
    """A running Console over a file-backed store with one seeded workflow decision, plus an
    authenticated opener — the deployment shape (fresh connection per request)."""
    import tc_growth.store as store_mod

    db = str(tmp_path / "u4a.db")
    s = SqliteStore(db)
    did = _seed(s)
    lid = s.record_decision(title="Legacy row", status="proposed")
    s.close()
    monkeypatch.setattr(store_mod, "open_store", lambda path=None: SqliteStore(db))
    monkeypatch.setenv(console._TOKEN_ENV, "u4a-test-token")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), console._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.open(urllib.request.Request(f"{base}/login", data=b"token=u4a-test-token",
                                       method="POST"))
    try:
        yield type("Env", (), {"base": base, "opener": opener, "db": db,
                               "decision_id": did, "legacy_id": lid})
    finally:
        httpd.shutdown()


def _csrf_from(page: str) -> str:
    m = re.search(r"name='csrf' value='([^']+)'", page)
    assert m, "detail page must embed the csrf token in its forms"
    return m.group(1)


def _post(env, path: str, **fields) -> str:
    data = urllib.parse.urlencode(fields).encode()
    return env.opener.open(urllib.request.Request(f"{env.base}{path}", data=data,
                                                  method="POST")).read().decode()


def test_full_browser_approve_flow_is_two_step(console_env):
    env = console_env
    detail = env.opener.open(f"{env.base}/decision/{env.decision_id}").read().decode()
    assert "Approve…" in detail and "Bilingual SEO" in detail
    csrf = _csrf_from(detail)

    # Step 1: no `confirmed` -> the confirmation page; NOTHING has mutated.
    step1 = _post(env, f"/decision/{env.decision_id}/approve", csrf=csrf, revision=0)
    assert "Confirm approval" in step1 and "PRODUCTION" in step1
    assert SqliteStore(env.db).get_decision(env.decision_id).status == "proposed"

    # Step 2: confirmed -> approved, audit trail complete, PRG redirect renders the notice.
    step2 = _post(env, f"/decision/{env.decision_id}/approve", csrf=csrf, revision=0,
                  confirmed=1)
    assert "Approved." in step2
    s = SqliteStore(env.db)
    d = s.get_decision(env.decision_id)
    assert (d.status, d.revision, d.approved_by) == ("approved", 1, "owner")
    assert [e.action for e in s.list_decision_events(d.id)] == ["propose", "approve"]
    # Duplicate submission of the same form: calm no-op, still one approve event.
    again = _post(env, f"/decision/{env.decision_id}/approve", csrf=csrf, revision=0,
                  confirmed=1)
    assert "Already approved" in again
    assert [e.action for e in SqliteStore(env.db).list_decision_events(d.id)] == [
        "propose", "approve"]


def test_forged_csrf_is_refused_without_mutation(console_env):
    env = console_env
    try:
        _post(env, f"/decision/{env.decision_id}/approve", csrf="forged", revision=0,
              confirmed=1)
        raise AssertionError("forged csrf must 403")
    except urllib.error.HTTPError as e:
        assert e.code == 403
    assert SqliteStore(env.db).get_decision(env.decision_id).status == "proposed"


def test_unauthenticated_post_is_refused(console_env):
    env = console_env
    bare = urllib.request.build_opener()                       # no session cookie
    try:
        bare.open(urllib.request.Request(
            f"{env.base}/decision/{env.decision_id}/approve",
            data=b"csrf=x&revision=0&confirmed=1", method="POST"))
        raise AssertionError("unauthenticated must 401")
    except urllib.error.HTTPError as e:
        assert e.code == 401
    assert SqliteStore(env.db).get_decision(env.decision_id).status == "proposed"


def test_stale_revision_shows_error_and_changes_nothing(console_env):
    env = console_env
    detail = env.opener.open(f"{env.base}/decision/{env.decision_id}").read().decode()
    csrf = _csrf_from(detail)
    out = _post(env, f"/decision/{env.decision_id}/approve", csrf=csrf, revision=41,
                confirmed=1)
    assert "stale" in out
    assert SqliteStore(env.db).get_decision(env.decision_id).status == "proposed"


def test_reject_requires_reason_then_records_it(console_env):
    env = console_env
    detail = env.opener.open(f"{env.base}/decision/{env.decision_id}").read().decode()
    csrf = _csrf_from(detail)
    out = _post(env, f"/decision/{env.decision_id}/reject", csrf=csrf, revision=0, reason="  ")
    assert "reason is required" in out
    assert SqliteStore(env.db).get_decision(env.decision_id).status == "proposed"
    out = _post(env, f"/decision/{env.decision_id}/reject", csrf=csrf, revision=0,
                reason="Wrong ES wording")
    assert "Rejected." in out and "Wrong ES wording" in out    # reason visible in history
    assert SqliteStore(env.db).get_decision(env.decision_id).status == "rejected"


def test_legacy_decision_page_renders_unapprovable_and_post_is_refused(console_env):
    env = console_env
    page = env.opener.open(f"{env.base}/decision/{env.legacy_id}").read().decode()
    assert "predates the approval workflow" in page
    detail = env.opener.open(f"{env.base}/decision/{env.decision_id}").read().decode()
    out = _post(env, f"/decision/{env.legacy_id}/approve", csrf=_csrf_from(detail),
                revision=0, confirmed=1)
    assert "no bound envelope" in out
    assert SqliteStore(env.db).get_decision(env.legacy_id).status == "proposed"


def test_home_links_waiting_decisions_to_their_detail_pages(console_env):
    env = console_env
    home = env.opener.open(f"{env.base}/").read().decode()
    assert f"/decision/{env.decision_id}" in home and "Review →" in home


# --- U4a.1: decision history (review #71 post-merge finding) ------------------------------------
#
# A decision must never SEEM to vanish: the homepage queue shows only proposed (actionable)
# decisions, and everything else stays discoverable in the /decisions history — approved items
# reachable (so Unapprove stays reachable), rejected/executed visible as immutable record.


def test_history_lists_every_status_and_queue_stays_proposed_only():
    s = SqliteStore(":memory:")
    d_approved = _seed(s)
    s.approve_decision(d_approved, expected_revision=0)
    d_rejected = _seed(s)
    s.reject_decision(d_rejected, expected_revision=0, reason="superseded")
    d_waiting = _seed(s)
    lid = s.record_decision(title="Legacy row", status="active")

    out = console_views.decisions_body(s, status="all")
    for did in (d_approved, d_rejected, d_waiting, lid):
        assert f"/decision/{did}" in out                       # discoverable without typing IDs
    assert "legacy" in out                                     # legacy rows labeled, not hidden
    assert f"Decisions ({4})".replace("4", "4") in out

    # Filters narrow without losing the rest of the vocabulary.
    approved_only = console_views.decisions_body(s, status="approved")
    assert f"/decision/{d_approved}" in approved_only
    assert f"/decision/{d_rejected}" not in approved_only

    # The homepage queue still counts ONLY actionable proposed decisions...
    waiting = [d for d in s.list_decisions() if str(d.status) == "proposed"]
    assert [d.id for d in waiting] == [d_waiting]
    # ...and the approved decision remains manageable from its detail page (Unapprove present).
    detail = console_views.decision_body(s.get_decision(d_approved),
                                         s.list_decision_events(d_approved), csrf="t")
    assert "Unapprove" in detail and "/decisions" in detail    # history link after any action


def test_history_escapes_store_strings():
    evil = "<script>alert(1)</script>"
    s = SqliteStore(":memory:")
    s.record_decision(title=evil, status="proposed")
    out = console_views.decisions_body(s)
    assert "<script>" not in out and "&lt;script&gt;" in out


def test_decisions_route_serves_history_and_home_links_it(console_env):
    env = console_env
    # Approve the seeded decision so it LEAVES the queue, then prove it stays discoverable.
    detail = env.opener.open(f"{env.base}/decision/{env.decision_id}").read().decode()
    _post(env, f"/decision/{env.decision_id}/approve", csrf=_csrf_from(detail), revision=0,
          confirmed=1)
    home = env.opener.open(f"{env.base}/").read().decode()
    # The approved decision has LEFT the queue (only the legacy proposed row remains)...
    assert "Decisions waiting (1)" in home
    assert f"<a href='/decision/{env.decision_id}'><b>D#{env.decision_id}</b></a>" not in home
    # ...and the path out of the queue is visible right where it disappeared from.
    assert "Decision history" in home
    history = env.opener.open(f"{env.base}/decisions").read().decode()
    assert f"/decision/{env.decision_id}" in history and "approved" in history
    filtered = env.opener.open(f"{env.base}/decisions?status=rejected").read().decode()
    assert f"/decision/{env.decision_id}" not in filtered
    bogus = env.opener.open(f"{env.base}/decisions?status=evil").read().decode()
    assert f"/decision/{env.decision_id}" in bogus             # unknown filter falls back to all


def test_modal_card_styles_are_scoped_and_never_clamp_page_sections():
    """U4a.2 (owner acceptance observation): the Operations modal's dialog geometry (560px,
    86vh, inner scrollbar) leaked onto every `section.card` via a bare `.card` selector,
    compressing page content into nested scroll boxes. Dialog styles stay under `.modal`."""
    import re

    from tc_growth.console import _STYLE

    assert ".modal .card" in _STYLE
    assert not re.search(r"(?m)^\.card[\s{]", _STYLE)          # no bare .card rule may return
    # The page-section style itself must not carry dialog geometry.
    section_rule = re.search(r"(?m)^section\.card \{[^}]*\}", _STYLE).group(0)
    for forbidden in ("max-height", "overflow", "width:560"):
        assert forbidden not in section_rule


def test_missing_decision_404s(console_env):
    env = console_env
    try:
        env.opener.open(f"{env.base}/decision/999")
        raise AssertionError("missing decision must 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404
