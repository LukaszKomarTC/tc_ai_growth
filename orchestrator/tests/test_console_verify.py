"""WP-U4b — the Verify-live-change control over the real Console server.

Drives the owner's actual flow end-to-end (fetches faked at the module seam, never the store):
approved decision -> Verify live change (read #1) -> store-backed pending with a disabled,
countdown-labeled Confirm -> Confirm refused before the interval -> Confirm (read #2) ->
EXECUTED with evidence on the page. Plus the fail-closed branches the owner will actually hit:
mismatched pages, stale revisions, and the control's absence everywhere it must not appear.
"""

from __future__ import annotations

import http.cookiejar
import re
import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tc_growth import console, verify
from tc_growth.store.sqlite import SqliteStore

ES_URL = "https://tossacycling.com/"
EN_URL = "https://tossacycling.com/en/"


def _envelope() -> dict:
    return {
        "schema_version": "u4/1", "profile": "default", "environment": "production",
        "kind": "seo_meta_update",
        "target": {"object_type": "wp_post", "post_id": 11038,
                   "expected_urls": {"es": ES_URL, "en": EN_URL}},
        "payload": {"title_es": "Título ES", "meta_es": "Meta ES",
                    "title_en": "Title EN", "meta_en": "Meta EN"},
    }


def _matching_page(url: str) -> verify.PageRead:
    lang = "es" if url == ES_URL else "en"
    payload = _envelope()["payload"]
    return verify.PageRead(requested_url=url, final_url=url, status=200, redirect_chain=[],
                           body_sha256="cd" * 32, title=payload[f"title_{lang}"],
                           meta_description=payload[f"meta_{lang}"], canonical=url)


def _wrong_page(url: str) -> verify.PageRead:
    return verify.PageRead(requested_url=url, final_url=url, status=200, redirect_chain=[],
                           body_sha256="ef" * 32, title="Home | OLD",
                           meta_description="old", canonical=url)


@pytest.fixture()
def env(monkeypatch, tmp_path):
    """Running Console + one APPROVED verifiable decision + authenticated opener. Live fetches
    are faked at tc_growth.verify.fetch_page (resolved at call time for exactly this reason)."""
    import tc_growth.store as store_mod

    db = str(tmp_path / "u4b.db")
    s = SqliteStore(db)
    did = s.propose_decision(title="Homepage SEO", envelope=_envelope(),
                             expected_profile="default", allowed_environments=("production",),
                             allowed_hosts=("tossacycling.com",))
    s.approve_decision(did, expected_revision=0)
    s.close()
    monkeypatch.setattr(store_mod, "open_store", lambda path=None: SqliteStore(db))
    monkeypatch.setenv(console._TOKEN_ENV, "u4b-test-token")
    monkeypatch.setattr(verify, "fetch_page", _matching_page)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), console._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.open(urllib.request.Request(f"{base}/login", data=b"token=u4b-test-token",
                                       method="POST"))
    try:
        yield type("Env", (), {"base": base, "opener": opener, "db": db, "decision_id": did,
                               "monkeypatch": monkeypatch})
    finally:
        httpd.shutdown()


def _csrf(page: str) -> str:
    m = re.search(r"name='csrf' value='([^']+)'", page)
    assert m
    return m.group(1)


def _post(env, path: str, **fields) -> str:
    data = urllib.parse.urlencode(fields).encode()
    return env.opener.open(urllib.request.Request(f"{env.base}{path}", data=data,
                                                  method="POST")).read().decode()


def test_full_browser_verify_flow_two_steps_to_executed(env):
    detail = env.opener.open(f"{env.base}/decision/{env.decision_id}").read().decode()
    assert "Verify live change" in detail and "Nothing is written to the site" in detail
    csrf = _csrf(detail)

    # Step 1: read #1 matches -> pending; the Confirm control exists but is DISABLED (60s).
    page = _post(env, f"/decision/{env.decision_id}/verify", csrf=csrf, revision=1)
    assert "Read #1 matched" in page and "Confirm arms in" in page
    assert "<button disabled" in page
    assert SqliteStore(env.db).get_decision(env.decision_id).status == "approved"

    # Confirm before the interval: refused, nothing changes.
    refused = _post(env, f"/decision/{env.decision_id}/verify-confirm", csrf=csrf, revision=1)
    assert "not armed yet" in refused
    assert SqliteStore(env.db).get_decision(env.decision_id).status == "approved"

    # Interval elapsed (test override of the module constant; production never lowers it).
    env.monkeypatch.setattr(verify, "MIN_CONFIRM_INTERVAL_S", 0)
    armed = env.opener.open(f"{env.base}/decision/{env.decision_id}").read().decode()
    assert "Ready to confirm" in armed and "Confirm verification" in armed
    done = _post(env, f"/decision/{env.decision_id}/verify-confirm", csrf=csrf, revision=1)
    assert "EXECUTED" in done and "left the queue" in done
    s = SqliteStore(env.db)
    d = s.get_decision(env.decision_id)
    assert (d.status, d.revision) == ("executed", 2)
    assert d.execution_evidence.startswith("verify_attempt:")
    final = env.opener.open(f"{env.base}/decision/{env.decision_id}").read().decode()
    assert "Verification attempts (2)" in final
    # The permanent business record (review #74): a plain paragraph names both reads and what
    # they checked — readable months later without inspecting the database.
    assert "Execution record" in final
    assert "read #1 at" in final and "read #2 at" in final and "both full matches" in final
    assert "the owner applied the change" in final
    # Terminal: no verify control, no approve/unapprove forms remain.
    assert "Verify live change</h2>" not in final
    assert "Terminal — corrections are new decisions." in final
    # History rows carry the executed context too.
    history = env.opener.open(f"{env.base}/decisions").read().decode()
    assert "verified live" in history


def test_mismatch_is_loud_recorded_and_never_closes(env):
    env.monkeypatch.setattr(verify, "fetch_page", _wrong_page)
    detail = env.opener.open(f"{env.base}/decision/{env.decision_id}").read().decode()
    page = _post(env, f"/decision/{env.decision_id}/verify", csrf=_csrf(detail), revision=1)
    assert "do NOT match the approved envelope" in page
    # Plain language FIRST (review #74): which language, what was wrong, what to do — rendered
    # BEFORE the raw attempts evidence.
    assert "do not match the approved content yet" in page
    assert "<b>ES</b>" in page and "title mismatch" in page
    assert page.index("do not match the approved content yet") < page.index(
        "Verification attempts")
    assert "then verify again" in page
    s = SqliteStore(env.db)
    assert s.get_decision(env.decision_id).status == "approved"
    assert [a.outcome for a in s.list_verify_attempts(env.decision_id)] == ["mismatch"]


def test_stale_revision_refuses_verification(env):
    detail = env.opener.open(f"{env.base}/decision/{env.decision_id}").read().decode()
    page = _post(env, f"/decision/{env.decision_id}/verify", csrf=_csrf(detail), revision=41)
    assert "stale" in page
    assert SqliteStore(env.db).list_verify_attempts(env.decision_id) == []


def test_no_verify_control_on_proposed_or_legacy(env):
    s = SqliteStore(env.db)
    pid = s.propose_decision(title="Second", envelope=_envelope(),
                             expected_profile="default", allowed_environments=("production",),
                             allowed_hosts=("tossacycling.com",))
    lid = s.record_decision(title="Legacy", status="approved")
    s.close()
    proposed = env.opener.open(f"{env.base}/decision/{pid}").read().decode()
    assert "Verify live change" not in proposed                # approve first, always
    legacy = env.opener.open(f"{env.base}/decision/{lid}").read().decode()
    assert "no registered verification path" in legacy or "Verify live change" not in legacy
