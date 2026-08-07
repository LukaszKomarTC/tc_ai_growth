"""WP-U5.1 — the read-only Operations Intelligence foundation (issue #82).

These tests exercise behaviour, not formatting. The ones that matter most are the hostile cases:
a monitoring system's characteristic failure is not crashing, it is quietly reassuring.

Unprivileged by design, so CI runs every one of them.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tc_growth import inspection, store as store_mod
from tc_growth.collectors import FixtureCollector

T0 = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def store():
    s = store_mod.open_store(":memory:")
    try:
        yield s
    finally:
        s.close()


def ctx(profile="tossa-cycling", environment="production", *, now=None, **kw):
    return inspection.CollectionContext(
        profile=profile, environment=environment, repo_commit="deadbeef",
        now=(lambda: now or T0), **kw)


class _Stub:
    """A collector whose reading the test controls outright."""

    version = "1"

    def __init__(self, value, *, status="ok", scope="probe.scope", cid="stub",
                 boom: Exception | None = None, evidence=""):
        self.id, self.scope, self._value = cid, scope, value
        self._status, self._boom, self._evidence = status, boom, evidence

    def collect(self, c):
        if self._boom:
            raise self._boom
        return inspection.CollectorResult(scope=self.scope, status=self._status,
                                          value=self._value, source="stub",
                                          evidence=self._evidence, reason="stub reading")


# --- identity: the amendment-1 boundary ---------------------------------------------------------

@pytest.mark.parametrize("profile,environment", [
    ("", "production"), ("tossa", ""), ("   ", "production"), ("tossa", "   "),
])
def test_a_collection_without_explicit_identity_is_refused(profile, environment):
    """There is no default. A sweep that cannot say whose environment it inspects must not run —
    the evidence it produced would be unattributable, and worse, plausibly attributed."""
    with pytest.raises(inspection.CollectionRefused):
        inspection.CollectionContext(profile=profile, environment=environment)


def test_process_globals_cannot_contaminate_an_explicit_collection(store, monkeypatch):
    """The hostile case the reviewer asked for (issue #82, criterion 4).

    The process is configured for one business and environment; the collection is launched
    explicitly for another. Every row must name the one that was ASKED for — not the one the
    process happens to be holding.
    """
    monkeypatch.setenv("TC_SITE", "tour-de-girona")   # active_site() -> the WRONG profile
    monkeypatch.setenv("TC_ENV_KIND", "staging")      # settings env  -> the WRONG environment

    run_id = inspection.run_inspection(
        store, [_Stub({"v": 1})], ctx("tossa-cycling", "production"))

    run = store.get_inspection_run(run_id)
    assert (run["profile"], run["environment"]) == ("tossa-cycling", "production")
    rows = store.list_observations(run_id)
    assert rows and all((r["profile"], r["environment"]) == ("tossa-cycling", "production")
                        for r in rows)
    # Nothing anywhere in the durable record may carry the process-global identity.
    blob = str(run) + str(rows)
    assert "tour-de-girona" not in blob
    assert "staging" not in blob


def test_an_observation_cannot_be_filed_under_a_different_identity_than_its_run(store):
    """Belt and braces at the storage layer: even a caller that hand-built the arguments cannot
    split one run's identity across two businesses."""
    run_id = store.begin_inspection_run(profile="a", environment="production", trigger="cli",
                                        collector_set_version="u5/1", repo_commit="x")
    with pytest.raises(ValueError, match="does not match its inspection run"):
        store.record_observation(
            run_id, collector_id="c", collector_version="1", scope="s", source="src",
            profile="b", environment="production", captured_at=T0.isoformat(), status="ok",
            value_json="{}", value_digest="d", evidence=None, predecessor_id=None,
            change_class="baseline", severity="ok", confidence=None, reason=None)


def test_a_predecessor_is_never_resolved_across_profiles_or_environments(store):
    """Two businesses both have a `host.capacity`. A diff computed across them would be fiction."""
    inspection.run_inspection(store, [_Stub({"free_gb": 120}, scope="host.capacity")],
                              ctx("tossa-cycling", "production"))
    run_b = inspection.run_inspection(store, [_Stub({"free_gb": 42}, scope="host.capacity")],
                                      ctx("tour-de-girona", "production"))

    # The second profile has never been observed before, so this is ITS baseline — not a
    # dramatic 120 -> 42 drop borrowed from the neighbour.
    rows = store.list_observations(run_b)
    assert rows[0]["change_class"] == inspection.CHANGE_BASELINE
    assert rows[0]["predecessor_id"] is None

    # Same again across environments within one profile.
    run_stg = inspection.run_inspection(store, [_Stub({"free_gb": 9}, scope="host.capacity")],
                                        ctx("tossa-cycling", "staging"))
    assert store.list_observations(run_stg)[0]["change_class"] == inspection.CHANGE_BASELINE


def test_explicit_profile_reaches_execution_provenance(monkeypatch):
    """The narrow executor seam (amendment 1): an operation run on behalf of a named profile
    records THAT profile, not whichever site the process is configured for."""
    from tc_growth.core.actions import get_operation
    from tc_growth.core.executor import _provenance

    monkeypatch.setenv("TC_SITE", "tour-de-girona")
    op = get_operation("run_integrity_scan")
    assert _provenance(op, "production", "tossa-cycling")["profile"] == "tossa-cycling"
    # Unchanged for existing callers that do not know a profile.
    assert _provenance(op, "production")["profile"] == "tour-de-girona"


# --- baseline, diff and drift -------------------------------------------------------------------

def test_the_first_observation_is_baseline_not_unchanged(store):
    """A first sweep has compared nothing. Calling that 'no changes' is the easiest way for a
    monitor to look reassuring on day one (issue #82, criterion 7)."""
    run_id = inspection.run_inspection(store, [_Stub({"v": 1})], ctx())
    row = store.list_observations(run_id)[0]
    assert row["change_class"] == inspection.CHANGE_BASELINE
    assert row["predecessor_id"] is None


def test_an_identical_second_sweep_is_unchanged_and_quiet(store):
    """Criterion 9's other half: stable facts must not manufacture attention."""
    inspection.run_inspection(store, [_Stub({"v": 1})], ctx())
    second = inspection.run_inspection(store, [_Stub({"v": 1})], ctx())

    row = store.list_observations(second)[0]
    assert row["change_class"] == inspection.CHANGE_UNCHANGED
    assert row["severity"] == inspection.STATUS_OK
    assert row["predecessor_id"] is not None


def test_a_changed_value_produces_a_deterministic_diff_and_links_its_predecessor(store):
    first = inspection.run_inspection(store, [_Stub({"v": 1})], ctx())
    second = inspection.run_inspection(store, [_Stub({"v": 2})], ctx())

    before = store.list_observations(first)[0]
    after = store.list_observations(second)[0]
    assert after["change_class"] == inspection.CHANGE_CHANGED
    assert after["predecessor_id"] == before["id"]
    assert after["value_digest"] != before["value_digest"]
    # A diff is not automatically an alarm (issue #82 §7).
    assert after["severity"] == inspection.STATUS_WARN


def test_key_order_does_not_count_as_drift(store):
    """Canonicalization earns its place here: the same reading serialized differently is the
    same reading, and a monitor that alerts on dict ordering gets muted within a week."""
    inspection.run_inspection(store, [_Stub({"a": 1, "b": 2})], ctx())
    second = inspection.run_inspection(store, [_Stub({"b": 2, "a": 1})], ctx())
    assert store.list_observations(second)[0]["change_class"] == inspection.CHANGE_UNCHANGED


# --- failure semantics --------------------------------------------------------------------------

def test_a_collector_that_raises_becomes_unknown_and_does_not_stop_the_others(store):
    """Independent collectors (issue #82 §14): one unreadable source must not blank the page."""
    run_id = inspection.run_inspection(store, [
        _Stub(None, scope="broken.scope", cid="broken", boom=RuntimeError("permission denied")),
        _Stub({"v": 1}, scope="healthy.scope", cid="healthy"),
    ], ctx())

    rows = {r["scope"]: r for r in store.list_observations(run_id)}
    assert rows["broken.scope"]["status"] == inspection.STATUS_UNKNOWN
    assert rows["broken.scope"]["severity"] == inspection.STATUS_UNKNOWN
    assert "RuntimeError" in rows["broken.scope"]["evidence"]
    assert rows["healthy.scope"]["severity"] == inspection.STATUS_OK


def test_unknown_never_becomes_healthy_and_a_lost_source_is_reported(store):
    inspection.run_inspection(store, [_Stub({"v": 1})], ctx())
    lost = inspection.run_inspection(store, [_Stub(None, boom=OSError("gone"))], ctx())
    row = store.list_observations(lost)[0]
    assert row["change_class"] == inspection.CHANGE_DISAPPEARED
    assert row["severity"] == inspection.STATUS_UNKNOWN

    back = inspection.run_inspection(store, [_Stub({"v": 1})], ctx())
    assert store.list_observations(back)[0]["change_class"] == inspection.CHANGE_APPEARED


def test_a_collector_reported_breach_outranks_a_quiet_diff(store):
    """A threshold breach is a breach whether or not the value also changed."""
    inspection.run_inspection(store, [_Stub({"free_gb": 5}, status="action")], ctx())
    repeat = inspection.run_inspection(store, [_Stub({"free_gb": 5}, status="action")], ctx())
    row = store.list_observations(repeat)[0]
    assert row["change_class"] == inspection.CHANGE_UNCHANGED
    assert row["severity"] == inspection.STATUS_ACTION


# --- freshness is decided at read time ----------------------------------------------------------

def test_a_healthy_observation_goes_stale_without_a_new_write(store):
    """Issue #82, criterion 6. The row is append-only and still says `ok`; the page must not.

    This is the difference between 'it was fine when we looked' and 'it is fine' — and the whole
    reason freshness is not frozen into the record.
    """
    run_id = inspection.run_inspection(store, [_Stub({"v": 1})], ctx(now=T0))
    row = store.list_observations(run_id)[0]
    assert row["severity"] == inspection.STATUS_OK

    assert inspection.effective_status(row, now=T0 + timedelta(minutes=5)) == inspection.STATUS_OK
    assert inspection.freshness(row["captured_at"],
                                now=T0 + timedelta(hours=30)) == inspection.FRESH_AGING
    # Past the stale threshold the page can no longer claim health from this row.
    assert inspection.effective_status(
        row, now=T0 + timedelta(days=4)) == inspection.STATUS_UNKNOWN


def test_going_stale_never_downgrades_a_real_alarm(store):
    """An old fire is still a fire. Staleness may remove confidence, never urgency."""
    run_id = inspection.run_inspection(store, [_Stub({"v": 1}, status="action")], ctx(now=T0))
    row = store.list_observations(run_id)[0]
    assert inspection.effective_status(
        row, now=T0 + timedelta(days=9)) == inspection.STATUS_ACTION


def test_never_observed_and_undatable_are_both_dishonest_to_call_fresh():
    assert inspection.freshness(None, now=T0) == inspection.FRESH_NEVER
    assert inspection.freshness("not-a-date", now=T0) == inspection.FRESH_UNAVAILABLE


def test_unknown_outranks_warn_in_the_rollup():
    """Not knowing whether the backups exist is worse than knowing a disk fills slowly."""
    assert inspection.rollup(["ok", "warn", "unknown"]) == inspection.STATUS_UNKNOWN
    assert inspection.rollup(["ok", "warn", "unknown", "action"]) == inspection.STATUS_ACTION
    assert inspection.rollup(["ok", "ok"]) == inspection.STATUS_OK
    assert inspection.rollup([]) == inspection.STATUS_UNKNOWN


# --- evidence handling --------------------------------------------------------------------------

def test_evidence_is_redacted_before_it_is_bounded(store):
    """Order matters: truncating first could cut a secret in half and store the readable half."""
    secret_line = "TC_API_TOKEN=super-secret-value-that-must-never-land-in-the-record"
    run_id = inspection.run_inspection(
        store, [_Stub({"v": 1}, evidence=secret_line + "\n" + ("x" * 5000))], ctx())
    evidence = store.list_observations(run_id)[0]["evidence"]
    assert "super-secret-value" not in evidence
    assert "redacted" in evidence
    assert len(evidence.encode()) <= inspection.MAX_EVIDENCE_BYTES + 100  # + the truncation note


def test_observations_are_append_only_evidence(store):
    run_id = inspection.run_inspection(store, [_Stub({"v": 1})], ctx())
    row_id = store.list_observations(run_id)[0]["id"]
    conn = store._conn
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE observations SET severity='ok' WHERE id=?", (row_id,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM observations WHERE id=?", (row_id,))


def test_a_finished_run_is_terminal_and_its_identity_immutable(store):
    run_id = inspection.run_inspection(store, [_Stub({"v": 1})], ctx())
    conn = store._conn
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE inspection_runs SET summary='better' WHERE id=?", (run_id,))

    live = store.begin_inspection_run(profile="a", environment="production", trigger="cli",
                                      collector_set_version="u5/1", repo_commit="x")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE inspection_runs SET profile='b' WHERE id=?", (live,))


# --- the owner surface --------------------------------------------------------------------------

def _render(store, *, now, profile="tossa-cycling", environment="production"):
    from tc_growth import console_views

    return console_views.operations_health_body(
        store.latest_inspection_run(profile=profile, environment=environment),
        store.latest_observations(profile=profile, environment=environment),
        profile=profile, environment=environment, now=now,
        effective=inspection.effective_status, freshness=inspection.freshness,
        rollup=inspection.rollup, value_of=inspection.observation_value)


def test_no_evidence_never_renders_as_healthy(store):
    html = _render(store, now=T0)
    assert "Nothing observed yet" in html
    assert "absence of evidence" in html
    assert "Healthy" not in html


def test_the_surface_degrades_from_green_to_unknown_as_the_clock_advances(store):
    """The frozen-clock proof. Same append-only row, same store, no new write — only time."""
    inspection.run_inspection(store, [_Stub({"v": 1})], ctx(now=T0))

    fresh = _render(store, now=T0 + timedelta(minutes=1))
    assert "Operations healthy" in fresh

    later = _render(store, now=T0 + timedelta(days=4))
    assert "Operations healthy" not in later
    assert "⚪ Unknown" in later
    assert "STALE" in later


def test_hostile_collector_output_cannot_inject_markup(store):
    """Plugin names and log lines come from inspected systems. They are hostile input."""
    payload = "<script>alert('xss')</script>"
    inspection.run_inspection(
        store, [_Stub({"plugin": payload}, scope=payload, evidence=payload)], ctx(now=T0))

    html = _render(store, now=T0)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_one_unreadable_collector_does_not_remove_the_page(store):
    inspection.run_inspection(store, [
        _Stub(None, scope="broken.scope", cid="broken", boom=RuntimeError("nope")),
        _Stub({"v": 1}, scope="healthy.scope", cid="healthy"),
    ], ctx(now=T0))

    html = _render(store, now=T0)
    assert "broken.scope" in html and "healthy.scope" in html
    assert "⚪ Unknown" in html


# --- the fixture collector, and what U5.1 deliberately does NOT do -------------------------------

def test_the_fixture_collector_drives_the_whole_chain(store):
    """Criterion 9 end to end, through the real collector rather than a test double."""
    first = inspection.run_inspection(store, [FixtureCollector("stable")], ctx(now=T0))
    assert store.list_observations(first)[0]["change_class"] == inspection.CHANGE_BASELINE

    same = inspection.run_inspection(store, [FixtureCollector("stable")], ctx(now=T0))
    assert store.list_observations(same)[0]["change_class"] == inspection.CHANGE_UNCHANGED

    drifted = inspection.run_inspection(store, [FixtureCollector("changed")], ctx(now=T0))
    row = store.list_observations(drifted)[0]
    assert row["change_class"] == inspection.CHANGE_CHANGED
    assert row["severity"] == inspection.STATUS_WARN
    assert row["collector_id"] == "fixture"
    assert row["value_digest"] and row["captured_at"]


def test_an_oversized_fixture_source_reports_unknown_rather_than_storing_it(store):
    run_id = inspection.run_inspection(store, [FixtureCollector("x" * 5000)], ctx())
    row = store.list_observations(run_id)[0]
    assert row["status"] == inspection.STATUS_UNKNOWN
    assert "x" * 500 not in row["value_json"]


def test_u5_creates_no_cases(store):
    """Amendment 2: case linkage waits for machine-enforced identity keying in U5.4. Until then
    U5 must not attach findings to cases at all — prose in a case body is not an isolation
    boundary, and a wrong link is worse than no link."""
    inspection.run_inspection(store, [_Stub({"v": 1}, status="action")], ctx())
    rows = store._conn.execute("SELECT case_id FROM observations").fetchall()
    assert rows and all(r["case_id"] is None for r in rows)
    assert store.list_cases() == []


def test_u5_adds_no_write_capability_to_the_registry():
    """Criterion 10: the registry must be exactly as write-capable as it was before U5."""
    from tc_growth.core.actions import OPERATIONS, get_operation, validate_registry

    validate_registry()
    assert get_operation("deploy_release").enabled is False
    assert get_operation("deploy_release").production_write is True
    enabled_writers = [o.id for o in OPERATIONS if o.enabled and o.production_write]
    assert enabled_writers == []


# --- the migration, evidenced before deployment -------------------------------------------------

_ES_URL = "https://tossacycling.com/es/alquiler/"
_EN_URL = "https://tossacycling.com/en/rental/"


def _u4_envelope() -> dict:
    return {"schema_version": "u4/1", "profile": "default", "environment": "production",
            "kind": "seo_meta_update",
            "target": {"object_type": "wp_post", "post_id": 11038,
                       "expected_urls": {"es": _ES_URL, "en": _EN_URL}},
            "payload": {"title_es": "Título", "meta_es": "Meta",
                        "title_en": "Title", "meta_en": "Meta"}}


def test_v8_store_migrates_to_v9_leaving_every_existing_record_intact(tmp_path):
    """The deployment evidence this increment owes, produced BEFORE it is installed anywhere.

    v8 → v9 adds two tables and three indexes and touches nothing else. The store this runs
    against is production-shaped — an executed decision with its full U4a/U4b trail, a run, an
    artifact and an acceptance run with phases — because a migration test on an empty database
    proves only that the DDL parses.
    """
    from tc_growth.store.db import SCHEMA_VERSION
    from tc_growth.store.sqlite import SqliteStore

    path = tmp_path / "v8.db"
    s = SqliteStore(path)
    ctx_kw = dict(expected_profile="default", allowed_environments=("production",),
                  allowed_hosts=("tossacycling.com",))
    did = s.propose_decision(title="Improve homepage SEO", envelope=_u4_envelope(), **ctx_kw)
    s.approve_decision(did, expected_revision=0)
    attempt = s.record_verify_attempt(decision_id=did, revision=1,
                                      envelope_sha256=s.get_decision(did).envelope_sha256,
                                      read_number=1, outcome="match", detail="{}",
                                      started_at="2026-08-07T12:00:00+00:00")
    s.execute_decision(did, expected_revision=1, evidence_attempt_id=attempt)
    s.log_run(kind="weekly-report", status="ok", summary="run")
    s.persist_report_artifact(kind="weekly-report", body="report", validator_ok=True,
                              validator_reason=None, validator_version="1")
    acc = s.begin_acceptance_run(requested_by="owner", root="/srv/probe")
    s.record_acceptance_phase(acc, seq=1, name="launch", status="ok")

    before = {
        "decision": s.get_decision(did),
        "events": [(e.action, e.revision) for e in s.list_decision_events(did)],
        "attempts": [(a.id, a.outcome) for a in s.list_verify_attempts(did)],
        "runs": len(s.list_runs(limit=50)),
        "artifacts": len(s.list_report_artifacts()),
        "phases": [(p["seq"], p["name"], p["status"]) for p in s.list_acceptance_phases(acc)],
    }

    # Rewind to v8: drop the v9 tables and stamp the old version.
    s._conn.execute("DROP TABLE observations;")
    s._conn.execute("DROP TABLE inspection_runs;")
    s._conn.execute("UPDATE schema_version SET version = 8;")
    s._conn.commit()
    s.close()

    s = SqliteStore(path)                                        # reopen under current code
    assert s._conn.execute(
        "SELECT version FROM schema_version;").fetchone()[0] == SCHEMA_VERSION
    for table in ("inspection_runs", "observations"):
        assert s._conn.execute(
            "SELECT name FROM sqlite_master WHERE name = ?;", (table,)).fetchone()

    after = s.get_decision(did)
    assert after == before["decision"]                            # every field, unchanged
    assert after.status == "executed" and after.execution_evidence == f"verify_attempt:{attempt}"
    assert [(e.action, e.revision) for e in s.list_decision_events(did)] == before["events"]
    assert [(a.id, a.outcome) for a in s.list_verify_attempts(did)] == before["attempts"]
    assert len(s.list_runs(limit=50)) == before["runs"]
    assert len(s.list_report_artifacts()) == before["artifacts"]
    assert [(p["seq"], p["name"], p["status"])
            for p in s.list_acceptance_phases(acc)] == before["phases"]

    # And the new tables are usable on the migrated store, with their triggers in force.
    run_id = inspection.run_inspection(s, [FixtureCollector("stable")],
                                       ctx("tossa-cycling", "production"))
    assert s.list_observations(run_id)[0]["change_class"] == inspection.CHANGE_BASELINE
    with pytest.raises(sqlite3.IntegrityError):
        s._conn.execute("DELETE FROM observations")
    s.close()
