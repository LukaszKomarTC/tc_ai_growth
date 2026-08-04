"""WP-U4a — the decision approval workflow's storage truth.

What is proven here, per the acceptance criteria on PR #69 (claims stated at their precise
enforcement layer — review #71 finding 3):
- canonical envelope hashing is byte-exact and deterministic (fixed fixtures), and every
  material change — payload, target, profile, environment — changes the hash;
- DATABASE TRIGGERS enforce, even against raw SQL: approved-envelope immutability, executed
  terminality, append-only audit events, and the legal transition graph for workflow rows;
- the STORE API enforces revision-based stale-view rejection, proposal-boundary runtime-context
  checks (profile / environment / target hosts), and audit-event append in the same
  transaction as each transition — the audit COUPLING is an API guarantee, not a trigger one;
- legacy decisions stay visible but are not approvable, with a plain-English reason;
- the v3 -> v4 migration is additive and non-destructive against a production-shaped store.
"""

from __future__ import annotations

import sqlite3

import pytest

from tc_growth.envelope import canonical_json, envelope_sha256, validate_envelope
from tc_growth.store.records import (
    InvalidTransition,
    NotApprovable,
    StaleRevision,
)
from tc_growth.store.sqlite import SqliteStore


def _envelope(**overrides) -> dict:
    env = {
        "schema_version": "u4/1",
        "profile": "tossa-cycling",
        "environment": "production",
        "kind": "seo_meta_update",
        "target": {
            "object_type": "wp_post",
            "post_id": 13699,
            "expected_urls": {
                "es": "https://www.tossacycling.com/alquiler_bicicletas/",
                "en": "https://www.tossacycling.com/en/alquiler_bicicletas/",
            },
        },
        "payload": {"title_es": "Alquiler de bicicletas en Tossa de Mar",
                    "meta_es": "Reserva online — bicis de carretera y MTB."},
    }
    env.update(overrides)
    return env


def _store() -> SqliteStore:
    return SqliteStore(":memory:")


# The runtime context every proposal must present (review #71 finding 1) — tests state it
# explicitly, exactly like the CLI derives it from settings.
_CONTEXT = dict(expected_profile="tossa-cycling", allowed_environments=("production",),
                allowed_hosts=("www.tossacycling.com",))


def _propose(s: SqliteStore, **kw) -> int:
    defaults = dict(title="Bilingual SEO for the rental page", envelope=_envelope(),
                    rationale="1,502 impressions at position 14.9",
                    evidence="report artifact #1",
                    impact={"value": "+200–500 visits/mo", "label": "estimate",
                            "method": "GSC position/CTR heuristic",
                            "source": "report artifact #1", "as_of": "2026-08-03"},
                    **_CONTEXT)
    defaults.update(kw)
    return s.propose_decision(**defaults)


# --- canonicalization: byte-exact, deterministic, change-sensitive ------------------------------


def test_canonical_json_and_hash_are_byte_exact_pinned_fixtures():
    """The pinned serialization AND its hash, as literal fixtures — sorted keys, no
    insignificant whitespace, real Unicode (ñ stays ñ, no \\uXXXX). These literals ARE the
    schema: if this test needs an update, that's a schema change, not a refactor."""
    env = {"schema_version": "u4/1", "profile": "p", "environment": "staging",
           "kind": "k", "target": {"object_type": "wp_post", "expected_urls": {"es": "u"}},
           "payload": {"title_es": "Bicis de montaña"}}
    assert canonical_json(env) == (
        '{"environment":"staging","kind":"k","payload":{"title_es":"Bicis de montaña"},'
        '"profile":"p","schema_version":"u4/1",'
        '"target":{"expected_urls":{"es":"u"},"object_type":"wp_post"}}')
    assert envelope_sha256(env) == (
        "30f3e6cd1b423508ab0687cfab13a15e6b610d1419ef3e5c660b49cfbec5e6ab")


def test_key_order_never_changes_canonical_bytes():
    a = {"schema_version": "u4/1", "profile": "p", "environment": "staging", "kind": "k",
         "target": {"object_type": "wp_post", "expected_urls": {"es": "u"}},
         "payload": {"t": "v"}}
    # Same logical envelope, different construction order -> identical canonical bytes + hash.
    b = {"payload": {"t": "v"},
         "target": {"expected_urls": {"es": "u"}, "object_type": "wp_post"},
         "kind": "k", "environment": "staging", "profile": "p", "schema_version": "u4/1"}
    assert canonical_json(a) == canonical_json(b)
    assert envelope_sha256(a) == envelope_sha256(b)


@pytest.mark.parametrize("change", [
    {"payload": {"title_es": "DIFFERENT"}},
    {"profile": "other-site"},
    {"environment": "staging"},
    {"kind": "other_kind"},
    {"target": {"object_type": "wp_post", "post_id": 999,
                "expected_urls": {"es": "https://www.tossacycling.com/otra/"}}},
])
def test_any_material_change_changes_the_hash(change):
    assert envelope_sha256(_envelope(**change)) != envelope_sha256(_envelope())


def test_validate_envelope_refuses_bad_shapes():
    assert validate_envelope("not a dict")
    assert any("missing keys" in p for p in validate_envelope({}))
    assert any("unknown keys" in p for p in validate_envelope(_envelope(extra_key=1)))
    assert any("schema_version" in p for p in validate_envelope(_envelope(schema_version="u4/2")))
    assert any("environment" in p for p in validate_envelope(_envelope(environment="prod")))
    assert any("expected_urls" in p
               for p in validate_envelope(_envelope(target={"object_type": "wp_post",
                                                            "expected_urls": {}})))
    assert any("payload" in p for p in validate_envelope(_envelope(payload={})))
    assert validate_envelope(_envelope()) == []


def test_target_schema_is_closed_per_kind():
    """Review #71 finding 2: a hashed-but-unvalidated target field is a hole, not a feature."""
    base_target = _envelope()["target"]
    # Unknown target keys refused.
    t = dict(base_target, hidden_semantics="surprise")
    assert any("unknown target keys" in p for p in validate_envelope(_envelope(target=t)))
    # Unknown kinds cannot be proposed at all — a kind starts with its schema.
    assert any("unknown kind" in p for p in validate_envelope(_envelope(kind="mystery_kind")))
    # seo_meta_update requires post_id (positive int) and BOTH language URLs.
    t = {k: v for k, v in base_target.items() if k != "post_id"}
    assert any("post_id" in p for p in validate_envelope(_envelope(target=t)))
    t = dict(base_target, post_id=True)
    assert any("post_id" in p for p in validate_envelope(_envelope(target=t)))
    t = dict(base_target, expected_urls={"es": base_target["expected_urls"]["es"]})
    assert any("missing required language" in p for p in validate_envelope(_envelope(target=t)))
    # URLs must be well-formed HTTPS with a host.
    for bad in ("http://www.tossacycling.com/x/", "ftp://x/", "not a url", "https://"):
        t = dict(base_target,
                 expected_urls={"es": bad, "en": base_target["expected_urls"]["en"]})
        assert validate_envelope(_envelope(target=t)), bad


def test_valid_bilingual_envelope_canonicalizes_to_stable_pinned_bytes():
    """The FULL valid production envelope (both languages, real hosts) hashes to a pinned
    value — tightened validation must never move canonical bytes for the same dict."""
    assert envelope_sha256(_envelope()) == (
        "5e01ed67d42139abe147ae03abd2d03d4ac698ccce7a13a42259d86b3e815fda")


# --- proposal boundary: runtime context, not envelope self-authority ----------------------------


def test_wrong_profile_fails_closed_with_no_decision_and_no_event():
    s = _store()
    with pytest.raises(ValueError, match="does not match the active profile"):
        _propose(s, envelope=_envelope(profile="other-site"))
    assert s.list_decisions() == []
    assert s._conn.execute("SELECT COUNT(*) FROM decision_events;").fetchone()[0] == 0


def test_disallowed_environment_fails_closed():
    s = _store()
    with pytest.raises(ValueError, match="not permitted in this context"):
        _propose(s, envelope=_envelope(environment="staging"))  # context allows production only
    assert s.list_decisions() == []


def test_off_profile_host_fails_closed():
    s = _store()
    env = _envelope()
    env["target"]["expected_urls"]["en"] = "https://evil.example.com/en/alquiler_bicicletas/"
    with pytest.raises(ValueError, match="not among this profile's allowed hosts"):
        _propose(s, envelope=env)
    assert s.list_decisions() == []
    # Host comparison is case-insensitive — equivalent hosts must not be refused.
    env = _envelope()
    env["target"]["expected_urls"]["en"] = env["target"]["expected_urls"]["en"].replace(
        "www.tossacycling.com", "WWW.TossaCycling.com")
    assert _propose(s, envelope=env) > 0


def test_missing_context_is_refused_not_defaulted():
    """Every piece of the proposal context is mandatory AT THE STORE BOUNDARY (review #71
    round 2): there is no unconstrained mode a future agent caller could reach — an empty host
    allowlist is a refusal, not a wildcard."""
    s = _store()
    with pytest.raises(ValueError, match="expected_profile"):
        s.propose_decision(title="t", envelope=_envelope(), expected_profile="",
                           allowed_environments=("production",),
                           allowed_hosts=("www.tossacycling.com",))
    with pytest.raises(ValueError, match="allowed_environments"):
        s.propose_decision(title="t", envelope=_envelope(), expected_profile="tossa-cycling",
                           allowed_environments=(),
                           allowed_hosts=("www.tossacycling.com",))
    with pytest.raises(ValueError, match="allowed_hosts"):
        s.propose_decision(title="t", envelope=_envelope(), expected_profile="tossa-cycling",
                           allowed_environments=("production",), allowed_hosts=())
    with pytest.raises(TypeError):                            # not even omittable
        s.propose_decision(title="t", envelope=_envelope(), expected_profile="tossa-cycling",
                           allowed_environments=("production",))
    assert s.list_decisions() == []


def test_repropose_new_envelope_requires_hosts_too():
    s = _store()
    did = _propose(s)
    s.reject_decision(did, expected_revision=0, reason="x")
    with pytest.raises(ValueError, match="full proposal context"):
        s.repropose_decision(did, expected_revision=1, envelope=_envelope(),
                             expected_profile="tossa-cycling",
                             allowed_environments=("production",))  # hosts missing
    assert s.get_decision(did).status == "rejected"


# --- CLI context derivation: three settings, three concepts -------------------------------------


def _set_context_env(monkeypatch, *, env_kind="staging", targets="", hosts=""):
    monkeypatch.setenv("TC_ENV_KIND", env_kind)
    monkeypatch.setenv("TC_DECISION_TARGET_ENVIRONMENTS", targets)
    monkeypatch.setenv("TC_DECISION_URL_HOSTS", hosts)


def test_staging_console_proposes_production_when_explicitly_configured(monkeypatch):
    """The reviewer's core round-2 case: env_kind describes how the Console OPERATES; the
    target-environment setting says what decisions may TARGET. A STAGING/read-only Console with
    an explicit production target setting proposes a production envelope successfully — U4's
    primary real use case."""
    from tc_growth.cli import decision_proposal_context

    _set_context_env(monkeypatch, env_kind="staging", targets="production",
                     hosts="www.tossacycling.com,tossacycling.com")
    profile, envs, hosts = decision_proposal_context()
    assert envs == ("production",) and "www.tossacycling.com" in hosts
    s = _store()
    did = s.propose_decision(title="prod decision from staging console", envelope=_envelope(),
                             expected_profile="tossa-cycling", allowed_environments=envs,
                             allowed_hosts=hosts)
    assert s.get_decision(did).status == "proposed"


def test_production_envelope_rejected_when_target_setting_excludes_it(monkeypatch):
    from tc_growth.cli import decision_proposal_context

    _set_context_env(monkeypatch, env_kind="production", targets="staging",
                     hosts="www.tossacycling.com")
    _, envs, hosts = decision_proposal_context()
    s = _store()
    with pytest.raises(ValueError, match="not permitted in this context"):
        s.propose_decision(title="t", envelope=_envelope(),                # production envelope
                           expected_profile="tossa-cycling", allowed_environments=envs,
                           allowed_hosts=hosts)
    assert s.list_decisions() == []


def test_context_settings_fail_closed_and_validate_vocabulary(monkeypatch):
    from tc_growth.cli import decision_proposal_context

    _set_context_env(monkeypatch, targets="", hosts="www.tossacycling.com")
    with pytest.raises(ValueError, match="TC_DECISION_TARGET_ENVIRONMENTS is not set"):
        decision_proposal_context()
    _set_context_env(monkeypatch, targets="prod", hosts="www.tossacycling.com")
    with pytest.raises(ValueError, match="unknown value"):
        decision_proposal_context()
    _set_context_env(monkeypatch, targets="production", hosts="")
    with pytest.raises(ValueError, match="TC_DECISION_URL_HOSTS is not set"):
        decision_proposal_context()


def test_repropose_with_new_envelope_reenters_the_full_boundary():
    s = _store()
    did = _propose(s)
    s.reject_decision(did, expected_revision=0, reason="wrong title")
    new_env = _envelope(profile="other-site")
    # No context -> refused; wrong profile WITH context -> refused; decision stays rejected.
    with pytest.raises(ValueError, match="full proposal context"):
        s.repropose_decision(did, expected_revision=1, envelope=new_env)
    with pytest.raises(ValueError, match="does not match the active profile"):
        s.repropose_decision(did, expected_revision=1, envelope=new_env, **_CONTEXT)
    assert s.get_decision(did).status == "rejected"
    s.repropose_decision(did, expected_revision=1, envelope=_envelope(), **_CONTEXT)
    assert s.get_decision(did).status == "proposed"


# --- lifecycle: the exhaustive state machine ----------------------------------------------------


def test_propose_approve_records_full_audit_trail():
    s = _store()
    did = _propose(s)
    d = s.get_decision(did)
    assert (d.status, d.revision, d.kind) == ("proposed", 0, "seo_meta_update")
    assert d.envelope_sha256 == envelope_sha256(_envelope())
    assert d.envelope == canonical_json(_envelope())          # stored text == hashed text

    assert s.approve_decision(did, expected_revision=0, actor="owner") == "approved"
    d = s.get_decision(did)
    assert (d.status, d.revision, d.approved_by) == ("approved", 1, "owner")
    assert d.approved_at

    events = s.list_decision_events(did)
    assert [(e.action, e.from_status, e.to_status, e.revision) for e in events] == [
        ("propose", None, "proposed", 0), ("approve", "proposed", "approved", 1)]
    for e in events:
        assert e.at and e.actor and e.envelope_sha256 == d.envelope_sha256


def test_duplicate_approve_is_a_noop_success():
    s = _store()
    did = _propose(s)
    s.approve_decision(did, expected_revision=0)
    # A re-posted form (any stale revision) must be a calm no-op, never an error or a re-mutation.
    assert s.approve_decision(did, expected_revision=0) == "already-approved"
    assert s.get_decision(did).revision == 1
    assert len(s.list_decision_events(did)) == 2              # no third event


def test_stale_revision_is_rejected_without_mutation():
    s = _store()
    did = _propose(s)
    with pytest.raises(StaleRevision):
        s.approve_decision(did, expected_revision=7)
    d = s.get_decision(did)
    assert (d.status, d.revision) == ("proposed", 0)
    assert len(s.list_decision_events(did)) == 1              # propose only — no phantom audit


def test_reject_requires_a_reason_and_stores_it():
    s = _store()
    did = _propose(s)
    with pytest.raises(ValueError):
        s.reject_decision(did, expected_revision=0, reason="   ")
    assert s.get_decision(did).status == "proposed"
    s.reject_decision(did, expected_revision=0, reason="Wrong meta wording for ES")
    assert s.get_decision(did).status == "rejected"
    assert s.list_decision_events(did)[-1].detail == "Wrong meta wording for ES"


def test_invalid_transitions_are_refused_loudly():
    s = _store()
    did = _propose(s)
    with pytest.raises(InvalidTransition):
        s.unapprove_decision(did, expected_revision=0)        # proposed -> unapprove: not listed
    s.approve_decision(did, expected_revision=0)
    with pytest.raises(InvalidTransition):
        s.reject_decision(did, expected_revision=1, reason="x")  # approved -> reject: not listed
    with pytest.raises(InvalidTransition):
        s.repropose_decision(did, expected_revision=1)        # approved -> re-propose: not listed


def test_unapprove_is_the_only_path_back_and_clears_approval_fields():
    s = _store()
    did = _propose(s)
    s.approve_decision(did, expected_revision=0)
    s.unapprove_decision(did, expected_revision=1)
    d = s.get_decision(did)
    assert (d.status, d.revision) == ("proposed", 2)
    assert d.approved_at is None and d.approved_by is None
    # ...but the audit trail keeps who had approved what.
    actions = [e.action for e in s.list_decision_events(did)]
    assert actions == ["propose", "approve", "unapprove"]


def test_repropose_after_reject_allows_a_new_envelope():
    s = _store()
    did = _propose(s)
    s.reject_decision(did, expected_revision=0, reason="wrong title")
    new_env = _envelope(payload={"title_es": "Better title", "meta_es": "Better meta"})
    s.repropose_decision(did, expected_revision=1, envelope=new_env, **_CONTEXT)
    d = s.get_decision(did)
    assert (d.status, d.revision) == ("proposed", 2)
    assert d.envelope_sha256 == envelope_sha256(new_env)


# --- storage-layer guards (triggers, not API politeness) ----------------------------------------


def test_approved_envelope_is_immutable_at_the_database_layer():
    s = _store()
    did = _propose(s)
    s.approve_decision(did, expected_revision=0)
    for stmt, params in (
        ("UPDATE decisions SET envelope = '{}' WHERE id = ?;", (did,)),
        ("UPDATE decisions SET envelope_sha256 = 'ff' WHERE id = ?;", (did,)),
        ("UPDATE decisions SET kind = 'other' WHERE id = ?;", (did,)),
    ):
        with pytest.raises(sqlite3.IntegrityError, match="approved envelope is immutable"):
            s._conn.execute(stmt, params)


def test_executed_decision_is_terminal_at_the_database_layer():
    s = _store()
    did = _propose(s)
    s.approve_decision(did, expected_revision=0)
    # Simulate U4b's terminal transition directly (no API path exists yet, by design).
    s._conn.execute("UPDATE decisions SET status = 'executed' WHERE id = ?;", (did,))
    with pytest.raises(sqlite3.IntegrityError, match="terminal"):
        s._conn.execute("UPDATE decisions SET title = 'edited' WHERE id = ?;", (did,))


def test_illegal_raw_sql_transitions_are_refused_by_trigger():
    """The transition graph holds even against raw SQL (review #71 finding 3): a future code
    bug cannot move a workflow decision along an edge the spec does not list."""
    s = _store()
    did = _propose(s)
    for illegal in ("executed",):                             # proposed -> executed: not listed
        with pytest.raises(sqlite3.IntegrityError, match="illegal decision transition"):
            s._conn.execute("UPDATE decisions SET status = ? WHERE id = ?;", (illegal, did))
    s.reject_decision(did, expected_revision=0, reason="x")
    for illegal in ("approved", "executed"):                  # rejected -> only proposed
        with pytest.raises(sqlite3.IntegrityError, match="illegal decision transition"):
            s._conn.execute("UPDATE decisions SET status = ? WHERE id = ?;", (illegal, did))
    # Legacy rows (no envelope) keep their pre-U4 lifecycle, untouched by the graph.
    lid = s.record_decision(title="legacy", status="proposed")
    s._conn.execute("UPDATE decisions SET status = 'active' WHERE id = ?;", (lid,))


def test_decision_events_are_append_only():
    s = _store()
    did = _propose(s)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        s._conn.execute("UPDATE decision_events SET actor = 'evil' WHERE decision_id = ?;",
                        (did,))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        s._conn.execute("DELETE FROM decision_events WHERE decision_id = ?;", (did,))


# --- legacy decisions ---------------------------------------------------------------------------


def test_legacy_decision_is_visible_but_not_approvable_with_plain_reason():
    s = _store()
    lid = s.record_decision(title="Pre-U4 decision", status="proposed")
    assert s.get_decision(lid).envelope_sha256 is None        # renders, carries no envelope
    with pytest.raises(NotApprovable, match="no bound envelope"):
        s.approve_decision(lid, expected_revision=0)
    # The legacy CLI path still works for legacy rows...
    s.update_decision(lid, status="approved")
    assert s.get_decision(lid).status == "approved"


def test_generic_update_refuses_status_changes_on_workflow_decisions():
    s = _store()
    did = _propose(s)
    with pytest.raises(ValueError, match="approve/reject/unapprove"):
        s.update_decision(did, status="approved")
    assert s.get_decision(did).status == "proposed"
    s.update_decision(did, rationale="notes are fine")        # non-status fields stay allowed


def test_propose_refuses_invalid_envelopes_and_bare_number_provenance():
    s = _store()
    with pytest.raises(ValueError, match="invalid envelope"):
        _propose(s, envelope=_envelope(environment="prod"))
    with pytest.raises(ValueError, match="provenance object"):
        _propose(s, impact=0.8)  # bare numbers are exactly what the spec forbids


# --- migration ----------------------------------------------------------------------------------


_V3_SCHEMA = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
CREATE TABLE cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE, title TEXT NOT NULL, category TEXT,
    status TEXT NOT NULL DEFAULT 'open', priority TEXT NOT NULL DEFAULT 'medium',
    confidence TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    opened_by TEXT, closed_by TEXT, body TEXT);
CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
    kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ok', model TEXT, prompt_tokens INTEGER,
    completion_tokens INTEGER, cost_usd REAL, duration_s REAL, summary TEXT, detail TEXT,
    case_id INTEGER REFERENCES cases(id));
CREATE TABLE decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, made_at TEXT NOT NULL, title TEXT NOT NULL,
    rationale TEXT, status TEXT NOT NULL DEFAULT 'active', outcome TEXT, made_by TEXT,
    case_id INTEGER REFERENCES cases(id));
CREATE TABLE report_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER REFERENCES runs(id),
    kind TEXT NOT NULL, profile TEXT, window TEXT, generated_at TEXT NOT NULL,
    format_version TEXT NOT NULL, validator_version TEXT NOT NULL, validator_ok INTEGER NOT NULL,
    validator_reason TEXT, model TEXT, cost_usd REAL, content_sha256 TEXT NOT NULL,
    body TEXT NOT NULL, delivery_status TEXT NOT NULL DEFAULT 'pending',
    delivery_attempts INTEGER NOT NULL DEFAULT 0, delivered_at TEXT);
INSERT INTO schema_version (version) VALUES (3);
INSERT INTO decisions (made_at, title, rationale, status, made_by)
    VALUES ('2026-08-01T10:00:00+00:00', 'Apply bilingual SEO', 'GSC evidence', 'approved', 'human');
INSERT INTO report_artifacts (kind, generated_at, format_version, validator_version,
    validator_ok, content_sha256, body)
    VALUES ('weekly-report', '2026-08-03T05:00:00+00:00', 'md/1', '1', 1, 'ab', 'report body');
"""


def test_v3_database_migrates_to_v4_preserving_rows(tmp_path):
    """A production-shaped v3 store opens under v4 code: rows intact, new columns NULL/default,
    the lifecycle immediately usable, and the v3 artifact-immutability trigger still armed."""
    path = tmp_path / "v3.db"
    raw = sqlite3.connect(path)
    raw.executescript(_V3_SCHEMA)
    # The v3 artifact trigger exists on the real store; recreate it as deployed.
    raw.executescript("""
CREATE TRIGGER trg_report_artifacts_immutable
BEFORE UPDATE ON report_artifacts
WHEN OLD.body IS NOT NEW.body OR OLD.content_sha256 IS NOT NEW.content_sha256
BEGIN SELECT RAISE(ABORT, 'report artifact is immutable'); END;
""")
    raw.commit()
    raw.close()

    from tc_growth.store.db import SCHEMA_VERSION

    s = SqliteStore(path)
    assert s._conn.execute(
        "SELECT version FROM schema_version;").fetchone()[0] == SCHEMA_VERSION
    # Legacy decision survived with NULL workflow fields and default revision 0.
    d = s.get_decision(1)
    assert d.title == "Apply bilingual SEO" and d.status == "approved"
    assert d.envelope is None and d.envelope_sha256 is None and d.revision == 0
    # Legacy artifact survived; new column reads as None.
    a = s.get_report_artifact(1)
    assert a.body == "report body" and a.recommendations_count is None
    # The workflow is immediately usable on the migrated store, triggers included.
    did = _propose(s)
    s.approve_decision(did, expected_revision=0)
    with pytest.raises(sqlite3.IntegrityError):
        s._conn.execute("UPDATE decisions SET envelope = 'x' WHERE id = ?;", (did,))
    s.close()
