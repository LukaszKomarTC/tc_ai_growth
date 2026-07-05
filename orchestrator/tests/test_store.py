"""Persistence layer: schema, CRUD round-trips, case-linking, and the seed."""

from __future__ import annotations

import sqlite3

import pytest

from tc_growth import store


def _db():
    return store.connect(":memory:")


def test_init_creates_tables_and_version():
    conn = _db()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';")}
    assert {"cases", "runs", "decisions", "schema_version"} <= tables
    assert conn.execute("SELECT version FROM schema_version;").fetchone()[0] == store.db.SCHEMA_VERSION


def test_run_round_trips_with_token_cost():
    conn = _db()
    rid = store.record_run(
        conn, kind="weekly-report", model="claude-sonnet-4-6",
        prompt_tokens=1200, completion_tokens=800, cost_usd=0.0156, duration_s=42.0,
        summary="4 SEO opportunities, tracking gap flagged",
    )
    runs = store.list_runs(conn)
    assert len(runs) == 1 and runs[0].id == rid
    assert runs[0].kind == "weekly-report"
    assert runs[0].cost_usd == pytest.approx(0.0156)
    assert runs[0].prompt_tokens == 1200


def test_case_create_get_and_unique_ref():
    conn = _db()
    cid = store.create_case(conn, ref="INC-1", title="Spam", category="incident", priority="high")
    got = store.get_case_by_ref(conn, "INC-1")
    assert got and got.id == cid and got.priority == "high"
    assert store.get_case(conn, cid).title == "Spam"
    with pytest.raises(sqlite3.IntegrityError):
        store.create_case(conn, ref="INC-1", title="dup")


def test_update_case_bumps_timestamp_and_rejects_unknown_fields():
    conn = _db()
    cid = store.create_case(conn, title="t", body="old")
    before = store.get_case(conn, cid).updated_at
    store.update_case(conn, cid, status="resolved", body="new")
    after = store.get_case(conn, cid)
    assert after.status == "resolved" and after.body == "new"
    assert after.updated_at >= before
    with pytest.raises(ValueError):
        store.update_case(conn, cid, not_a_column="x")


def test_find_open_cases_matches_open_only():
    conn = _db()
    store.create_case(conn, title="Merchant Center tobacco spam", status="open", body="cigarettes")
    store.create_case(conn, title="Old resolved thing", status="resolved", body="tobacco")
    hits = store.find_open_cases(conn, "tobacco spam URLs")
    assert len(hits) == 1
    assert hits[0].title.startswith("Merchant Center")


def test_decision_links_to_case():
    conn = _db()
    cid = store.create_case(conn, title="c")
    did = store.record_decision(conn, title="Keep spam URLs at 410", rationale="avoid 301", case_id=cid)
    ds = store.list_decisions(conn, case_id=cid)
    assert len(ds) == 1 and ds[0].id == did and ds[0].case_id == cid


def test_estimate_cost_known_unknown_and_missing_tokens():
    from tc_growth.core.cost import estimate_cost

    # opus 4.8 = $5 in / $25 out per 1M → 1M+1M = $30
    assert estimate_cost("claude-opus-4-8", 1_000_000, 1_000_000) == pytest.approx(30.0)
    assert estimate_cost("claude-sonnet-4-6", 1_000_000, 0) == pytest.approx(3.0)
    assert estimate_cost("some-other-model", 100, 100) is None      # unknown → None, not a guess
    assert estimate_cost("claude-opus-4-8", None, 5) is None         # missing tokens → None


def test_log_run_stamps_cost():
    conn = _db()
    store.log_run(conn, kind="investigate", model="claude-sonnet-4-6",
                  prompt_tokens=1_000_000, completion_tokens=0, duration_s=1.0)
    assert store.list_runs(conn)[0].cost_usd == pytest.approx(3.0)


def test_sqlite_store_conforms_to_store_protocol():
    # The repository seam: SqliteStore satisfies Store; a future PostgresStore must pass this same
    # check to be a drop-in. runtime_checkable verifies the full method surface exists.
    from tc_growth.store import SqliteStore, Store

    s = SqliteStore(":memory:")
    assert isinstance(s, Store)
    # And the object surface round-trips end to end (no conn ever handled by the caller).
    cid = s.create_case(title="via store object", ref="OBJ-1")
    s.update_case(cid, status="monitoring")
    assert s.get_case_by_ref("OBJ-1").status == "monitoring"
    s.record_decision(title="d", case_id=cid)
    assert s.list_decisions(case_id=cid)[0].title == "d"
    s.log_run(kind="investigate", model="claude-haiku-4-5", prompt_tokens=1000, completion_tokens=100)
    assert s.list_runs(kind="investigate")[0].cost_usd is not None
    assert s.find_open_cases("store object")[0].id == cid
    s.close()


def test_open_store_returns_working_store(tmp_path):
    from tc_growth.store import open_store

    s = open_store(tmp_path / "t.db")
    s.seed_incident_case()
    assert s.get_case_by_ref(store.INCIDENT_REF) is not None
    s.close()


def test_seed_incident_is_idempotent():
    conn = _db()
    a = store.seed_incident_case(conn)
    b = store.seed_incident_case(conn)
    assert a == b
    case = store.get_case_by_ref(conn, store.INCIDENT_REF)
    assert case.status == "resolved" and case.category == "incident"
    assert len(store.list_cases(conn)) == 1
