"""WP-U4b — live-change verification: rules, two-step flow, evidence, and closure.

What is proven, at its precise layer:
- URL equality follows the spec's pinned rules (case/port/fragment/percent-encoding safe;
  trailing slash exact; ANY query disqualifies; wrong slug/language never equal);
- content comparison is NFC + whitespace-collapse + exact, per language, fail-closed
  (one language mismatching fails the read; missing payload fields and fetch errors never pass);
- the TWO-STEP flow is store-backed: read #1 arms a pending state that survives a fresh
  connection (restart), the confirm refuses before the minimum interval, a revision change
  orphans the pending read, and only two consistent full matches mark the decision EXECUTED
  (terminal, evidenced by a POINTER to the terminal attempt);
- attempt rows are append-only at the database layer;
- the v4 -> v5 migration is purely additive.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3

import pytest

from tc_growth import verify
from tc_growth.store.sqlite import SqliteStore

ES_URL = "https://tossacycling.com/"
EN_URL = "https://tossacycling.com/en/"


def _envelope() -> dict:
    return {
        "schema_version": "u4/1",
        "profile": "default",
        "environment": "production",
        "kind": "seo_meta_update",
        "target": {"object_type": "wp_post", "post_id": 11038,
                   "expected_urls": {"es": ES_URL, "en": EN_URL}},
        "payload": {
            "title_es": "Tossa Cycling — Alquiler de bicicletas en Tossa de Mar",
            "meta_es": "Centro de ciclismo en Tossa de Mar. Reserva online.",
            "title_en": "Tossa Cycling — Bike Rental in Tossa de Mar",
            "meta_en": "Cycling centre in Tossa de Mar. Book online.",
        },
    }


def _page(url: str, *, title: str, meta: str, canonical: str | None = None,
          status: int = 200, final_url: str | None = None,
          error: str | None = None) -> verify.PageRead:
    return verify.PageRead(
        requested_url=url, final_url=final_url or url, status=status,
        redirect_chain=[], body_sha256="ab" * 32, title=title, meta_description=meta,
        canonical=canonical if canonical is not None else url, error=error)


def _good_fetch(env: dict):
    """A fetcher serving pages that match the envelope's payload exactly."""
    p = env["payload"]

    def fetch(url: str) -> verify.PageRead:
        lang = "es" if url == ES_URL else "en"
        return _page(url, title=p[f"title_{lang}"], meta=p[f"meta_{lang}"])
    return fetch


def _seed_approved(s: SqliteStore) -> object:
    did = s.propose_decision(
        title="Homepage SEO", envelope=_envelope(), expected_profile="default",
        allowed_environments=("production",), allowed_hosts=("tossacycling.com",))
    s.approve_decision(did, expected_revision=0)
    return s.get_decision(did)


# --- URL equality (pinned rules) -----------------------------------------------------------------


@pytest.mark.parametrize("a,b,equal", [
    (ES_URL, "HTTPS://TOSSACYCLING.COM/", True),               # case-insensitive scheme+host
    (ES_URL, "https://tossacycling.com:443/", True),           # default port normalized
    (ES_URL, "https://tossacycling.com/#top", True),           # fragment stripped
    ("https://x.com/a%7Eb/", "https://x.com/a~b/", True),      # percent-encoding canonical
    (ES_URL, "https://tossacycling.com", False),               # trailing slash EXACT
    (ES_URL, "https://tossacycling.com/?utm=1", False),        # ANY query = not equal
    (ES_URL, "https://www.tossacycling.com/", False),          # different host
    (EN_URL, "https://tossacycling.com/en", False),            # slash form again
    ("https://x.com/a/", "https://x.com/A/", False),           # path case NOT normalized
])
def test_url_equality_pinned_rules(a, b, equal):
    assert verify.urls_equal(a, b) is equal


def test_text_normalization_nfc_and_whitespace_only():
    composed, decomposed = "Reparación", "Reparación"
    assert verify.normalize_text(composed) == verify.normalize_text(decomposed)
    assert verify.normalize_text("  a \n b\t c ") == "a b c"
    assert verify.normalize_text("CASE") != verify.normalize_text("case")  # no case folding


def test_page_signal_extraction():
    body = ('<html><head><title>T &amp; Co</title>'
            '<meta name="description" content="Meta &quot;x&quot;">'
            '<link rel="canonical" href="https://x.com/p/"></head></html>')
    sig = verify.extract_page_signals(body)
    assert sig == {"title": "T & Co", "meta_description": 'Meta "x"',
                   "canonical": "https://x.com/p/"}
    assert verify.extract_page_signals("<html></html>") == {
        "title": None, "meta_description": None, "canonical": None}


# --- verify_read: fail-closed comparison ---------------------------------------------------------


def test_read_matches_when_every_language_matches():
    env = _envelope()
    assert verify.verify_read(env, fetch=_good_fetch(env))["outcome"] == "match"


def test_one_language_mismatch_fails_the_whole_read():
    env = _envelope()
    good = _good_fetch(env)

    def fetch(url):
        if url == EN_URL:
            return _page(url, title="Home | TOSSA CYCLING", meta="old meta")
        return good(url)
    result = verify.verify_read(env, fetch=fetch)
    assert result["outcome"] == "mismatch"
    assert any("title mismatch" in p for p in result["urls"]["en"]["problems"])
    assert result["urls"]["es"]["problems"] == []              # the ES evidence stays clean


@pytest.mark.parametrize("mutate,expected_problem", [
    (dict(status=301), "final HTTP status"),
    (dict(final_url="https://tossacycling.com/otra/"), "final URL"),
    (dict(canonical="https://tossacycling.com/otra/"), "page canonical"),
    (dict(title=None), "page has no title"),
])
def test_page_level_failures_are_mismatches(mutate, expected_problem):
    env = _envelope()
    good = _good_fetch(env)

    def fetch(url):
        page = good(url)
        if url == ES_URL:
            for k, v in mutate.items():
                setattr(page, k, v)
        return page
    result = verify.verify_read(env, fetch=fetch)
    assert result["outcome"] == "mismatch"
    assert any(expected_problem in p for p in result["urls"]["es"]["problems"])


def test_fetch_error_is_error_not_pass():
    env = _envelope()
    good = _good_fetch(env)

    def fetch(url):
        if url == EN_URL:
            return verify.PageRead(requested_url=url, error="URLError: timed out")
        return good(url)
    assert verify.verify_read(env, fetch=fetch)["outcome"] == "error"


def test_missing_payload_field_cannot_verify():
    fetch = _good_fetch(_envelope())                           # pages unchanged and fine
    env = _envelope()
    del env["payload"]["meta_en"]                              # ...but nothing to compare to
    result = verify.verify_read(env, fetch=fetch)
    assert result["outcome"] == "mismatch"
    assert any("no meta_en to compare" in p for p in result["urls"]["en"]["problems"])


# --- the two-step flow ---------------------------------------------------------------------------


def test_full_two_step_flow_executes_with_evidence(tmp_path):
    db = str(tmp_path / "v.db")
    s = SqliteStore(db)
    d = _seed_approved(s)
    env = _envelope()

    assert verify.verify_step(s, d, step=1, fetch=_good_fetch(env)) == "pending"
    # Pending is STORE-backed: a fresh connection (restart) still sees it.
    s2 = SqliteStore(db)
    pending = s2.pending_verify_attempt(d.id, revision=d.revision)
    assert pending is not None and pending.read_number == 1 and pending.outcome == "match"

    # Confirm refuses before the minimum interval...
    assert verify.verify_step(s2, d, step=2, fetch=_good_fetch(env)) == "too-soon"
    assert s2.get_decision(d.id).status == "approved"
    # ...and executes after it (interval overridden for the test, never in production).
    assert verify.verify_step(s2, d, step=2, fetch=_good_fetch(env),
                              min_interval_s=0) == "executed"
    done = s2.get_decision(d.id)
    assert (done.status, done.revision) == ("executed", d.revision + 1)
    attempts = s2.list_verify_attempts(d.id)
    assert [a.read_number for a in attempts] == [1, 2]
    assert attempts[1].pair_id == attempts[0].id
    assert done.execution_evidence == f"verify_attempt:{attempts[1].id}"
    assert done.executed_at
    # The lifecycle event trail records the platform's act.
    assert [e.action for e in s2.list_decision_events(d.id)][-1] == "execute"
    # Executed decisions have LEFT the queue (proposed-only)...
    assert all(x.status != "proposed" or x.id != d.id for x in s2.list_decisions())
    # ...and are terminal even against raw SQL.
    with pytest.raises(sqlite3.IntegrityError):
        s2._conn.execute("UPDATE decisions SET title = 'x' WHERE id = ?;", (d.id,))


def test_failed_confirm_keeps_decision_approved_and_both_attempts(tmp_path):
    s = SqliteStore(str(tmp_path / "v.db"))
    d = _seed_approved(s)
    env = _envelope()
    assert verify.verify_step(s, d, step=1, fetch=_good_fetch(env)) == "pending"

    def changed_fetch(url):                                    # page changed between reads
        return _page(url, title="Something else now", meta="different")
    assert verify.verify_step(s, d, step=2, fetch=changed_fetch,
                              min_interval_s=0) == "read-mismatch"
    assert s.get_decision(d.id).status == "approved"           # does NOT close
    attempts = s.list_verify_attempts(d.id)
    assert [a.outcome for a in attempts] == ["match", "mismatch"]
    # The failed pair is consumed — confirming again requires a fresh read #1.
    assert verify.verify_step(s, d, step=2, fetch=_good_fetch(env),
                              min_interval_s=0) == "no-pending"


def test_failed_read1_never_arms_pending(tmp_path):
    s = SqliteStore(str(tmp_path / "v.db"))
    d = _seed_approved(s)

    def bad_fetch(url):
        return _page(url, title="wrong", meta="wrong")
    assert verify.verify_step(s, d, step=1, fetch=bad_fetch) == "read-mismatch"
    assert s.pending_verify_attempt(d.id, revision=d.revision) is None
    assert verify.verify_step(s, d, step=2, fetch=bad_fetch,
                              min_interval_s=0) == "no-pending"


def test_revision_change_orphans_the_pending_read(tmp_path):
    """Unapprove between the two reads: the confirm must NOT verify against an envelope the
    owner has since revisited — the pending read is orphaned by revision binding."""
    s = SqliteStore(str(tmp_path / "v.db"))
    d = _seed_approved(s)
    env = _envelope()
    assert verify.verify_step(s, d, step=1, fetch=_good_fetch(env)) == "pending"
    s.unapprove_decision(d.id, expected_revision=d.revision)
    s.approve_decision(d.id, expected_revision=d.revision + 1)
    fresh = s.get_decision(d.id)
    assert s.pending_verify_attempt(d.id, revision=fresh.revision) is None
    assert verify.verify_step(s, fresh, step=2, fetch=_good_fetch(env),
                              min_interval_s=0) == "no-pending"


def test_verify_refuses_wrong_states_and_kinds(tmp_path):
    s = SqliteStore(str(tmp_path / "v.db"))
    did = s.propose_decision(
        title="t", envelope=_envelope(), expected_profile="default",
        allowed_environments=("production",), allowed_hosts=("tossacycling.com",))
    d = s.get_decision(did)
    assert verify.verify_step(s, d, step=1) == "not-approved"  # proposed: verify n/a
    lid = s.record_decision(title="legacy", status="approved")
    assert verify.verify_step(s, s.get_decision(lid), step=1) == "not-verifiable"


def test_confirm_wait_is_measured_from_stored_read_time():
    pending = type("P", (), {"finished_at": "2026-08-04T10:00:00+00:00"})
    at = dt.datetime.fromisoformat("2026-08-04T10:00:30+00:00")
    assert verify.confirm_wait_s(pending, now=at) == 30
    at = dt.datetime.fromisoformat("2026-08-04T10:01:01+00:00")
    assert verify.confirm_wait_s(pending, now=at) == 0


def test_attempt_rows_are_append_only_and_carry_verbatim_evidence(tmp_path):
    s = SqliteStore(str(tmp_path / "v.db"))
    d = _seed_approved(s)
    env = _envelope()
    verify.verify_step(s, d, step=1, fetch=_good_fetch(env))
    a = s.list_verify_attempts(d.id)[0]
    assert (a.revision, a.envelope_sha256) == (d.revision, d.envelope_sha256)
    detail = json.loads(a.detail)
    assert detail["es"]["fetched_title"] == env["payload"]["title_es"]  # verbatim
    assert detail["es"]["body_sha256"]
    for stmt in ("UPDATE decision_verify_attempts SET outcome = 'match';",
                 "DELETE FROM decision_verify_attempts;"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            s._conn.execute(stmt)


def test_v4_database_migrates_forward_additively(tmp_path):
    """A v4 store (as deployed before U4b) opens under current code: version stamped forward,
    the attempts table and its triggers exist, and everything else is untouched."""
    from tc_growth.store.db import SCHEMA_VERSION

    path = tmp_path / "v4.db"
    s = SqliteStore(path)                                      # current code creates latest
    s._conn.execute("UPDATE schema_version SET version = 4;")  # pretend it was v4
    s._conn.execute("DROP TRIGGER trg_verify_attempts_no_update;")
    s._conn.execute("DROP TRIGGER trg_verify_attempts_no_delete;")
    s._conn.execute("DROP TABLE decision_verify_attempts;")
    s._conn.commit()
    s.close()
    s = SqliteStore(path)
    assert s._conn.execute(
        "SELECT version FROM schema_version;").fetchone()[0] == SCHEMA_VERSION
    names = {r[0] for r in s._conn.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE '%verify%';")}
    assert {"decision_verify_attempts", "trg_verify_attempts_no_update",
            "trg_verify_attempts_no_delete"} <= names
    s.close()
