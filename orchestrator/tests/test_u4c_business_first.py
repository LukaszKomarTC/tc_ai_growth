"""WP-U4c — business-first presentation, live comparison, disclosure, adopt-live.

One test per acceptance criterion on issue #75:
- business-first titles are enforced AT PROPOSAL TIME (objective constraint, not a heuristic),
  never cosmetically rewritten for display; legacy rows keep their long titles;
- the current-vs-proposed comparison uses the VERIFIER's parser and normalization, carries a
  fetch timestamp, and fails honestly — an unreadable page shows no value, never a stale one;
- technical evidence is progressively disclosed (available, not imposed);
- adopt-live creates a NEW unapproved proposal with provenance, inherits no approval, and
  leaves the source decision untouched;
- no production write capability is added.
"""

from __future__ import annotations

import http.cookiejar
import re
import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tc_growth import console, console_views, verify
from tc_growth.store.records import MAX_TITLE_CHARS
from tc_growth.store.sqlite import SqliteStore

ES_URL = "https://tossacycling.com/"
EN_URL = "https://tossacycling.com/en/"
_CTX = dict(expected_profile="default", allowed_environments=("production",),
            allowed_hosts=("tossacycling.com",))


def _envelope(**payload_overrides) -> dict:
    payload = {"title_es": "Título aprobado", "meta_es": "Meta aprobada",
               "title_en": "Approved title", "meta_en": "Approved meta"}
    payload.update(payload_overrides)
    return {"schema_version": "u4/1", "profile": "default", "environment": "production",
            "kind": "seo_meta_update",
            "target": {"object_type": "wp_post", "post_id": 11038,
                       "expected_urls": {"es": ES_URL, "en": EN_URL}},
            "payload": payload}


def _live(url: str, *, title="Título vivo", meta="Meta viva", error=None) -> verify.PageRead:
    if error:
        return verify.PageRead(requested_url=url, error=error)
    if url == EN_URL:
        title, meta = "Live title", "Live meta"
    return verify.PageRead(requested_url=url, final_url=url, status=200, title=title,
                           meta_description=meta, canonical=url, body_sha256="ab" * 32)


# --- criterion: business-first titles enforced at proposal time ----------------------------------


def test_headline_constraint_is_objective_and_enforced_at_the_boundary():
    s = SqliteStore(":memory:")
    long_title = "Homepage: bilingual SEO title & meta rewrite for the rental landing page"
    assert len(long_title) > MAX_TITLE_CHARS
    with pytest.raises(ValueError, match="OWNER-FACING HEADLINE"):
        s.propose_decision(title=long_title, envelope=_envelope(), **_CTX)
    with pytest.raises(ValueError, match="single line"):
        s.propose_decision(title="Two\nlines", envelope=_envelope(), **_CTX)
    with pytest.raises(ValueError, match="title is required"):
        s.propose_decision(title="   ", envelope=_envelope(), **_CTX)
    assert s.list_decisions() == []                            # nothing persisted on refusal

    # A business-first headline passes and is stored trimmed — the display never rewrites it.
    did = s.propose_decision(title="  Improve homepage SEO  ", envelope=_envelope(), **_CTX)
    d = s.get_decision(did)
    assert d.title == "Improve homepage SEO"
    assert d.title in console_views.decision_body(d, [], csrf="t")


def test_legacy_rows_keep_their_titles_and_are_never_rewritten():
    """The constraint binds NEW proposals only — historical records are immutable."""
    s = SqliteStore(":memory:")
    long_title = "Pre-U4c decision with a very long technical title that predates the rule " * 2
    lid = s.record_decision(title=long_title, status="approved")
    assert s.get_decision(lid).title == long_title


# --- criterion: comparison uses the verifier's own parser, timestamped, honest failure ----------


def test_comparison_uses_verifier_normalization_and_flags_only_real_differences():
    env = _envelope(title_es="Título vivo")                    # ES title matches live...
    snap = verify.live_snapshot(env, fetch=_live)
    rows = verify.compare_fields(env, snap)
    by = {(r["lang"], r["label"]): r for r in rows}
    assert by[("es", "Title")]["same"] is True                 # ...so it reports as matching
    assert by[("es", "Meta description")]["same"] is False     # ...and this one genuinely differs
    assert by[("en", "Title")]["current"] == "Live title"
    assert snap["fetched_at"]

    # Whitespace/NFC-equivalent text counts as the SAME, exactly as verification would judge it.
    env2 = _envelope(title_es="Título   vivo ")
    rows2 = verify.compare_fields(env2, verify.live_snapshot(env2, fetch=_live))
    assert next(r for r in rows2 if r["lang"] == "es" and r["label"] == "Title")["same"] is True


def test_unreadable_page_shows_no_value_and_never_a_stale_one():
    env = _envelope()
    snap = verify.live_snapshot(env, fetch=lambda u: _live(u, error="URLError: timed out"))
    rows = verify.compare_fields(env, snap)
    assert all(r["current"] is None and r["error"] for r in rows)
    out = console_views.comparison_section(
        type("D", (), {"id": 1, "envelope_sha256": "x", "revision": 0, "status": "approved"}),
        csrf="t", comparison=rows, snapshot=snap, adoptable=True)
    assert "could not read this page" in out and "no current value shown" in out
    assert "incomplete" in out
    assert "Adopt live content" not in out                     # never adopt a partial snapshot
    assert snap["fetched_at"] in out                           # the read is timestamped


def test_comparison_is_not_fetched_until_asked():
    d = type("D", (), {"id": 7, "envelope_sha256": "x", "revision": 0, "status": "approved"})
    out = console_views.comparison_section(d, csrf="t", comparison=None)
    assert "Not fetched yet" in out and "/decision/7?live=1" in out


# --- criterion: progressive disclosure ----------------------------------------------------------


def test_technical_evidence_is_disclosed_progressively():
    s = SqliteStore(":memory:")
    did = s.propose_decision(title="Improve homepage SEO", envelope=_envelope(), **_CTX)
    out = console_views.decision_body(s.get_decision(did), s.list_decision_events(did),
                                      csrf="t")
    # The technical trail is present but collapsed; the human part is not.
    assert "<details" in out and "History &amp; integrity</summary>" in out
    assert out.index("Recommendation") < out.index("History &amp; integrity")


# --- criterion: adopt-live creates a new unapproved proposal, source untouched -------------------


def test_adopt_live_envelope_keeps_target_and_refuses_partial_reads():
    env = _envelope()
    snap = verify.live_snapshot(env, fetch=_live)
    new = verify.adopt_live_envelope(env, snap)
    assert new["target"] == env["target"]                      # same page, new words
    assert new["profile"] == env["profile"] and new["environment"] == env["environment"]
    assert new["payload"]["title_es"] == "Título vivo"
    assert new["payload"]["title_en"] == "Live title"
    bad = verify.live_snapshot(env, fetch=lambda u: _live(u, error="boom") if u == EN_URL
                               else _live(u))
    with pytest.raises(ValueError, match="refusing to adopt"):
        verify.adopt_live_envelope(env, bad)


@pytest.fixture()
def env(monkeypatch, tmp_path):
    import tc_growth.store as store_mod

    db = str(tmp_path / "u4c.db")
    s = SqliteStore(db)
    did = s.propose_decision(title="Improve homepage SEO", envelope=_envelope(), **_CTX)
    s.approve_decision(did, expected_revision=0)
    s.close()
    monkeypatch.setattr(store_mod, "open_store", lambda path=None: SqliteStore(db))
    monkeypatch.setenv(console._TOKEN_ENV, "u4c-token")
    monkeypatch.setenv("TC_DECISION_TARGET_ENVIRONMENTS", "production")
    monkeypatch.setenv("TC_DECISION_URL_HOSTS", "tossacycling.com")
    monkeypatch.setattr(verify, "fetch_page", _live)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), console._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    opener.open(urllib.request.Request(f"{base}/login", data=b"token=u4c-token", method="POST"))
    try:
        yield type("E", (), {"base": base, "opener": opener, "db": db, "decision_id": did,
                             "monkeypatch": monkeypatch})
    finally:
        httpd.shutdown()


def _adopt_form(page: str) -> dict:
    """csrf + the signed snapshot token the page bound to its own comparison."""
    return {"csrf": re.search(r"name='csrf' value='([^']+)'", page).group(1),
            "snapshot": re.search(r"name='snapshot' value='([^']+)'", page).group(1),
            "revision": 1}


def _post_adopt(env, **fields) -> str:
    return env.opener.open(urllib.request.Request(
        f"{env.base}/decision/{env.decision_id}/adopt-live",
        data=urllib.parse.urlencode(fields).encode(), method="POST")).read().decode()


def test_browser_adopt_live_creates_new_proposal_and_leaves_source_untouched(env):
    page = env.opener.open(f"{env.base}/decision/{env.decision_id}?live=1").read().decode()
    assert "field(s) differ from the live pages" in page
    assert "Adopt live content as a new proposal" in page
    out = _post_adopt(env, **_adopt_form(page))
    assert "New proposal created" in out and "Nothing on this decision changed" in out

    s = SqliteStore(env.db)
    source = s.get_decision(env.decision_id)
    assert (source.status, source.revision) == ("approved", 1)  # untouched: no mutation at all
    new = [d for d in s.list_decisions() if d.id != env.decision_id]
    assert len(new) == 1
    n = new[0]
    assert n.status == "proposed" and n.revision == 0           # no approval inherited
    assert n.envelope_sha256 != source.envelope_sha256
    assert len(n.title) <= MAX_TITLE_CHARS                      # the action obeys its own rule
    # Provenance: source decision, URLs, fetch time, fetched values.
    assert f"D#{source.id}" in n.evidence and ES_URL in n.evidence
    assert "Título vivo" in n.evidence                          # the fetched values verbatim
    assert "displayed 20" in n.evidence and "confirmed 20" in n.evidence
    # The new proposal binds what is LIVE.
    assert "Título vivo" in n.envelope and "Live title" in n.envelope


def test_adopt_live_refuses_on_stale_revision(env):
    page = env.opener.open(f"{env.base}/decision/{env.decision_id}?live=1").read().decode()
    form = _adopt_form(page) | {"revision": 99}
    out = _post_adopt(env, **form)
    assert "stale" in out
    assert len(SqliteStore(env.db).list_decisions()) == 1       # nothing created


# --- criterion (review #76): consent is bound to the snapshot the owner SAW --------------------


def test_live_content_changing_between_comparison_and_click_creates_nothing(env):
    """TOCTOU: the owner reviews snapshot A; the page changes; the click must NOT adopt B."""
    page = env.opener.open(f"{env.base}/decision/{env.decision_id}?live=1").read().decode()
    form = _adopt_form(page)

    def _changed(url):                                          # the site moved underneath
        r = _live(url)
        r.title = "Something the owner never reviewed"
        return r
    env.monkeypatch.setattr(verify, "fetch_page", _changed)

    out = _post_adopt(env, **form)
    assert "live content CHANGED" in out and "Compare again" in out
    s = SqliteStore(env.db)
    assert len(s.list_decisions()) == 1                          # no decision row...
    assert len(s.list_decision_events(env.decision_id)) == 2     # ...and no lifecycle event
    assert s.get_decision(env.decision_id).revision == 1         # source untouched


def test_tampered_or_missing_snapshot_token_is_refused(env):
    page = env.opener.open(f"{env.base}/decision/{env.decision_id}?live=1").read().decode()
    form = _adopt_form(page)
    good = form["snapshot"]

    # Missing entirely.
    out = _post_adopt(env, csrf=form["csrf"], revision=1)
    assert "did not carry a valid reference" in out
    # Digest edited (owner-visible values swapped for others).
    stamp, digest, sig = good.split("|")
    out = _post_adopt(env, **(form | {"snapshot": f"{stamp}|{'0' * len(digest)}|{sig}"}))
    assert "did not carry a valid reference" in out
    # Signature edited.
    out = _post_adopt(env, **(form | {"snapshot": f"{stamp}|{digest}|{'0' * len(sig)}"}))
    assert "did not carry a valid reference" in out
    assert len(SqliteStore(env.db).list_decisions()) == 1        # nothing created by any of them


def test_duplicate_submit_is_idempotent_not_a_twin_proposal(env):
    page = env.opener.open(f"{env.base}/decision/{env.decision_id}?live=1").read().decode()
    form = _adopt_form(page)
    first = _post_adopt(env, **form)
    assert "New proposal created" in first
    again = _post_adopt(env, **form)                             # same displayed snapshot
    assert "already adopted" in again
    created = [d for d in SqliteStore(env.db).list_decisions() if d.id != env.decision_id]
    assert len(created) == 1                                     # one proposal, not two


def test_adopt_refuses_when_a_page_cannot_be_read_at_confirm_time(env):
    page = env.opener.open(f"{env.base}/decision/{env.decision_id}?live=1").read().decode()
    form = _adopt_form(page)
    env.monkeypatch.setattr(verify, "fetch_page",
                            lambda u: _live(u, error="URLError: timed out"))
    out = _post_adopt(env, **form)
    assert "CHANGED" in out or "could not be read" in out
    assert len(SqliteStore(env.db).list_decisions()) == 1


def test_successful_adopt_records_both_reads_in_provenance(env):
    page = env.opener.open(f"{env.base}/decision/{env.decision_id}?live=1").read().decode()
    form = _adopt_form(page)
    shown_at, digest, _ = form["snapshot"].split("|")
    _post_adopt(env, **form)
    new = [d for d in SqliteStore(env.db).list_decisions() if d.id != env.decision_id][0]
    assert f"displayed {shown_at}" in new.evidence               # what the owner saw...
    assert "confirmed 20" in new.evidence                        # ...and the confirming read
    assert digest in new.evidence                                # bound by one digest
    assert f"revision {1}" in new.evidence and "envelope " in new.evidence


def test_u4c_adds_no_production_write_capability(env):
    """The whole increment is view layer + one PROPOSAL-creating action."""
    page = env.opener.open(f"{env.base}/decision/{env.decision_id}?live=1").read().decode()
    # Assert on CONTROLS, not prose: the page legitimately instructs the owner to "apply the
    # approved change in WordPress" — that sentence is the authority boundary being stated,
    # not a button. What must not exist is a control offering to do it.
    labels = [re.sub(r"<[^>]+>", "", m).strip().lower()
              for m in re.findall(r"<button[^>]*>(.*?)</button>", page, re.S)]
    assert labels, "the page should have controls at all"
    for label in labels:
        assert not any(word in label for word in ("apply", "execute", "publish", "write"))
    from tc_growth.core.actions import OPERATIONS

    assert {op.id for op in OPERATIONS if op.enabled} == {
        "smtp_test", "run_integrity_scan", "redeliver_latest_report"}


# --- criteria (review #76 round 2): durable idempotence + defects never wear policy's clothes ---


def test_duplicate_detection_survives_a_large_archive(env):
    """The guarantee must not decay as decisions accumulate: >200 later rows, still no twin."""
    page = env.opener.open(f"{env.base}/decision/{env.decision_id}?live=1").read().decode()
    form = _adopt_form(page)
    assert "New proposal created" in _post_adopt(env, **form)

    s = SqliteStore(env.db)
    for i in range(220):                                        # bury the adoption in history
        s.record_decision(title=f"filler {i}", status="active")
    assert len(s.list_decisions(limit=1000)) > 220

    again = _post_adopt(env, **form)                            # same displayed snapshot
    assert "already adopted" in again
    created = [d for d in s.list_decisions(limit=1000)
               if d.title.startswith("Adopt live wording")]
    assert len(created) == 1                                    # still exactly one


def test_identity_is_the_exact_key_not_evidence_text():
    """Two unrelated decisions whose evidence merely CONTAINS similar text must not collide."""
    from tc_growth.store.records import adopt_key

    s = SqliteStore(":memory:")
    src = s.record_decision(title="source", status="approved")
    other = s.record_decision(title="another", status="approved")
    k1 = adopt_key(source_id=src, source_revision=1, envelope_sha256="aa", snapshot_digest="dd")
    k2 = adopt_key(source_id=src, source_revision=2, envelope_sha256="aa", snapshot_digest="dd")
    k3 = adopt_key(source_id=other, source_revision=1, envelope_sha256="aa",
                   snapshot_digest="dd")
    assert len({k1, k2, k3}) == 3                               # revision and source both bind

    # A decision whose evidence text happens to contain the digest is NOT an adoption record.
    created = s.propose_decision(title="Mentions a digest", envelope=_envelope(),
                                 evidence="snapshot dd — pasted into a note by hand", **_CTX)
    assert s.adopted_decision_id(k1) is None                    # only the keyed table counts

    assert s.claim_adoption(k1, source_id=src, source_revision=1, envelope_sha256="aa",
                            snapshot_digest="dd") is True
    s.complete_adoption(k1, created)
    assert s.adopted_decision_id(k1) == created
    assert s.adopted_decision_id(k2) is None                    # neighbouring keys unaffected
    assert s.claim_adoption(k1, source_id=src, source_revision=1, envelope_sha256="aa",
                            snapshot_digest="dd") is False      # completed claims are final


def test_a_bad_source_reference_raises_instead_of_looking_like_a_duplicate():
    """The FK violation is a DEFECT: it must not be reported as 'already claimed'."""
    import sqlite3 as _sqlite3

    from tc_growth.store.records import adopt_key

    s = SqliteStore(":memory:")
    k = adopt_key(source_id=999, source_revision=0, envelope_sha256="a", snapshot_digest="d")
    with pytest.raises(_sqlite3.IntegrityError):
        s.claim_adoption(k, source_id=999, source_revision=0, envelope_sha256="a",
                         snapshot_digest="d")


def test_an_incomplete_claim_does_not_block_a_retry():
    """A claim orphaned by a failed attempt must be reclaimable — an interrupted adoption
    cannot become a permanent refusal."""
    from tc_growth.store.records import adopt_key

    s = SqliteStore(":memory:")
    src = s.record_decision(title="source", status="approved")
    k = adopt_key(source_id=src, source_revision=0, envelope_sha256="a", snapshot_digest="d")
    assert s.claim_adoption(k, source_id=src, source_revision=0, envelope_sha256="a",
                            snapshot_digest="d") is True        # claimed, never completed
    assert s.claim_adoption(k, source_id=src, source_revision=0, envelope_sha256="a",
                            snapshot_digest="d") is True        # retry allowed


def test_unexpected_defect_is_visible_as_a_defect_not_a_policy_refusal(env):
    """An injected programming error must NOT render as an ordinary refusal: the owner sees it
    is a defect, and it lands in the evidence ledger for diagnosis."""
    page = env.opener.open(f"{env.base}/decision/{env.decision_id}?live=1").read().decode()
    form = _adopt_form(page)

    def _boom(*a, **k):
        raise RuntimeError("injected defect in snapshot handling")
    env.monkeypatch.setattr(verify, "adopt_live_envelope", _boom)

    out = _post_adopt(env, **form)
    assert "WRONG INSIDE THE CONSOLE" in out and "defect, not a policy refusal" in out
    assert "Could not adopt the live content" not in out        # never the policy wording
    s = SqliteStore(env.db)
    assert len([d for d in s.list_decisions() if d.id != env.decision_id]) == 0  # created nothing
    errors = [r for r in s.list_runs(kind="console-error", limit=10)]
    assert errors and "RuntimeError" in (errors[0].summary or "")
    assert "injected defect" in (errors[0].detail or "")        # traceback kept as evidence


def test_v5_store_migrates_to_v6_leaving_every_existing_record_intact(tmp_path):
    """Criterion 1 of the deployment gate, evidenced BEFORE the deploy: v5→v6 adds the
    adoptions table and touches nothing else — decisions, events, verify attempts, artifacts
    and runs all survive byte-for-byte, and U4a/U4b history stays readable."""
    from tc_growth.store.db import SCHEMA_VERSION

    path = tmp_path / "v5.db"
    s = SqliteStore(path)
    # A production-shaped store: an executed decision with its full U4a/U4b trail.
    did = s.propose_decision(title="Improve homepage SEO", envelope=_envelope(), **_CTX)
    s.approve_decision(did, expected_revision=0)
    attempt = s.record_verify_attempt(decision_id=did, revision=1,
                                      envelope_sha256=s.get_decision(did).envelope_sha256,
                                      read_number=1, outcome="match", detail="{}",
                                      started_at="2026-08-04T19:39:00+00:00")
    s.execute_decision(did, expected_revision=1, evidence_attempt_id=attempt)
    s.log_run(kind="weekly-report", status="ok", summary="run")
    s.persist_report_artifact(kind="weekly-report", body="report", validator_ok=True,
                              validator_reason=None, validator_version="1")
    before = {
        "decision": s.get_decision(did),
        "events": [(e.action, e.revision) for e in s.list_decision_events(did)],
        "attempts": [(a.id, a.outcome) for a in s.list_verify_attempts(did)],
        "runs": len(s.list_runs(limit=50)),
        "artifacts": len(s.list_report_artifacts()),
    }
    # Rewind to v5: drop the v6 table and stamp the old version.
    s._conn.execute("DROP TABLE decision_adoptions;")
    s._conn.execute("UPDATE schema_version SET version = 5;")
    s._conn.commit()
    s.close()

    s = SqliteStore(path)                                        # reopen under current code
    assert s._conn.execute(
        "SELECT version FROM schema_version;").fetchone()[0] == SCHEMA_VERSION
    assert s._conn.execute(
        "SELECT name FROM sqlite_master WHERE name = 'decision_adoptions';").fetchone()
    after = s.get_decision(did)
    assert after == before["decision"]                            # every field, unchanged
    assert after.status == "executed" and after.execution_evidence == f"verify_attempt:{attempt}"
    assert [(e.action, e.revision) for e in s.list_decision_events(did)] == before["events"]
    assert [(a.id, a.outcome) for a in s.list_verify_attempts(did)] == before["attempts"]
    assert len(s.list_runs(limit=50)) == before["runs"]
    assert len(s.list_report_artifacts()) == before["artifacts"]
    s.close()
