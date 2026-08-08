"""WP-U5.2a — drift is computed over the MATERIAL state, not over the whole reading.

The defect these tests pin down was not in any one collector. Each of the four was sound read on
its own; the fault was in what the digest was taken *over*. Because `value` contains the
measurement as well as the state — ages recomputed against `now`, free bytes, occurrence counts,
upstream release availability — a digest of it could differ from its predecessor's on a host
where nothing had happened. `platform.services` could not avoid it: `last_trigger_age_hours` is
`now` minus a fixed instant, so its digest was different by construction on every single sweep.

Measured on the collectors exactly as merged in PR #86, two sweeps ten minutes apart on an idle
host:

    platform.services   changed   warn
    host.capacity       changed   warn
    logs.signatures     changed   warn

Three warnings, every sweep, forever, for nothing — the alert fatigue issue #82 §7 forbids,
arriving through the mechanism that was supposed to prevent it.

So the tests come in pairs, and the second half is the one that matters. Any change-detector can
be made quiet by never reporting change; what has to hold is that it goes quiet on movement and
still speaks on substance.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from tc_growth import inspection, store as store_mod
from tc_growth.collectors import _exec
from tc_growth.collectors.host_capacity import HostCapacityCollector
from tc_growth.collectors.logs_signatures import LogSignaturesCollector
from tc_growth.collectors.platform_services import PlatformServicesCollector
from tc_growth.collectors.wp_inventory import WpInventoryCollector

T0 = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def store():
    s = store_mod.open_store(":memory:")
    try:
        yield s
    finally:
        s.close()


def ctx(*, now=T0, profile="tossa-cycling", environment="production"):
    return inspection.CollectionContext(profile=profile, environment=environment,
                                        repo_commit="deadbeef", now=(lambda: now))


def sweep(store, collector, *, now=T0) -> dict:
    """One sweep of one collector; returns its observation row."""
    run_id = inspection.run_inspection(store, [collector], ctx(now=now))
    return store.list_observations(run_id)[0]


def ok(stdout="", argv=("wp",)):
    return _exec.CommandResult(argv=argv, returncode=0, stdout=stdout, stderr="", ok=True)


# --- fake sources ---------------------------------------------------------------------------------

def systemd_runner(*, last_trigger: datetime | None = None, active="active", result="success",
                   journal_lines=("connection refused for host db1",)):
    """A host whose systemd and journal say the same thing every time they are asked."""
    usec = int(last_trigger.timestamp() * 1_000_000) if last_trigger else 0

    def run(argv, **kw):
        if argv[0] == "systemctl":
            return ok(argv=argv, stdout=(
                f"LoadState=loaded\nActiveState={active}\nSubState=running\nResult={result}\n"
                f"ExecMainStatus=0\nExecMainExitTimestamp=Fri 2026-08-07 10:00:00 UTC\n"
                f"LastTriggerUSec={usec}\nNextElapseUSecRealtime=0\n"))
        if argv[0] == "journalctl":
            if "-p" not in argv:                       # the unfiltered probe
                return ok(argv=argv, stdout="service started\n")
            return ok(argv=argv, stdout="".join(f"{ln}\n" for ln in journal_lines))
        raise AssertionError(argv)

    return run


class FakeStatvfs:
    f_frsize = 4096

    def __init__(self, blocks, bavail, files=1_000_000, favail=900_000):
        self.f_blocks, self.f_bavail, self.f_files, self.f_favail = blocks, bavail, files, favail


def capacity(bavail_blocks, *, total_blocks=26_000_000):
    return HostCapacityCollector(
        paths=("/data",), store_path="",
        statvfs=lambda p: FakeStatvfs(total_blocks, bavail_blocks))


def wp_runner(plugins, *, core="6.8.1", themes=(("twentytwentyfour", "active", "1.0"),)):
    def run(argv, **kw):
        if argv[:3] == ("wp", "core", "version"):
            return ok(argv=argv, stdout=f"{core}\n")
        if argv[:3] == ("wp", "plugin", "list"):
            return ok(argv=argv, stdout=json.dumps(
                [{"name": n, "status": s, "version": v, "update": u}
                 for n, s, v, u in plugins]))
        if argv[:3] == ("wp", "theme", "list"):
            return ok(argv=argv, stdout=json.dumps(
                [{"name": n, "status": s, "version": v} for n, s, v in themes]))
        raise AssertionError(argv)

    return run


def wp_collector(plugins, **kw):
    return WpInventoryCollector(runner=wp_runner(plugins, **kw), docroot="/")


# === platform.services ============================================================================

def test_platform_services_does_not_drift_merely_because_time_passed(store):
    """The measured regression, and the clearest case of it.

    Nothing about this host changes between the two sweeps — the timer's last trigger is the
    same fixed instant both times. Only the clock moves. Before the material state existed, the
    ages recomputed against `now` guaranteed a different digest, so this scope reported `changed`
    on every sweep it ever made.
    """
    runner = systemd_runner(last_trigger=T0 - timedelta(hours=1))
    collector = PlatformServicesCollector(runner=runner, scan_log=__file__)

    first = sweep(store, collector, now=T0)
    second = sweep(store, collector, now=T0 + timedelta(hours=2))

    assert first["change_class"] == inspection.CHANGE_BASELINE
    assert second["change_class"] == inspection.CHANGE_UNCHANGED
    assert second["severity"] == inspection.STATUS_OK
    # The ages are still recorded — they were never the problem, only their place in the digest.
    value = json.loads(second["value_json"])
    assert value["units"]["tc-autodeploy.timer"]["last_trigger_age_hours"] == 3.0
    assert "last_trigger_age_hours" not in json.loads(second["material_json"])["units"][
        "tc-autodeploy.timer"]


def test_platform_services_still_reports_a_unit_that_failed(store):
    """The half that matters: quiet on the clock, loud on the host."""
    good = PlatformServicesCollector(
        runner=systemd_runner(last_trigger=T0 - timedelta(hours=1)), scan_log=__file__)
    sweep(store, good, now=T0)

    broken = PlatformServicesCollector(
        runner=systemd_runner(last_trigger=T0 - timedelta(hours=1), active="failed"),
        scan_log=__file__)
    second = sweep(store, broken, now=T0 + timedelta(minutes=10))

    assert second["change_class"] == inspection.CHANGE_CHANGED
    assert second["severity"] == inspection.STATUS_ACTION


def test_platform_services_reports_a_unit_that_stopped_as_changed(store):
    """A unit going inactive is a CHANGE, not a disappearance — and this assertion is the
    inverse of what it was.

    It used to expect `disappeared`, because health going `ok` -> `unknown` was what drove the
    classification. That was the defect: `status` was answering both "is this healthy?" and "may
    this be compared?". systemd answered every query here and the material state is fully
    established, so the honest verdict is that the state changed. Health still degrades to
    `unknown` — the collector cannot confirm the work is happening — and the two facts are now
    reported separately instead of one overwriting the other (issue #82, U5.2d).

    `disappeared` keeps its own meaning: the source stopped being readable at all. See
    tests/test_u5_comparability.py.
    """
    sweep(store, PlatformServicesCollector(
        runner=systemd_runner(last_trigger=T0 - timedelta(hours=1)), scan_log=__file__), now=T0)

    second = sweep(store, PlatformServicesCollector(
        runner=systemd_runner(last_trigger=T0 - timedelta(hours=1), active="inactive"),
        scan_log=__file__), now=T0 + timedelta(minutes=10))

    assert second["change_class"] == inspection.CHANGE_CHANGED
    assert second["status"] == inspection.STATUS_UNKNOWN
    assert second["severity"] == inspection.STATUS_UNKNOWN


def test_platform_services_reports_a_timer_that_became_overdue(store):
    """A verdict crossing its window is material even though only the clock moved.

    This is the distinction the material state is drawing: the *age* is not compared, the
    *judgement made from it* is. `tc-autodeploy.timer` allows 3 hours; at 2 hours it is running
    and at 30 it is overdue, and only the second is a fact worth telling an owner.
    """
    runner = systemd_runner(last_trigger=T0 - timedelta(hours=2))
    sweep(store, PlatformServicesCollector(runner=runner, scan_log=__file__), now=T0)

    # Same fixed last-trigger, much later clock: the timer has stopped firing.
    later = T0 + timedelta(hours=28)
    second = sweep(store, PlatformServicesCollector(runner=runner, scan_log=__file__), now=later)

    assert json.loads(second["material_json"])["units"]["tc-autodeploy.timer"]["verdict"] == \
        "overdue"
    assert second["change_class"] == inspection.CHANGE_CHANGED
    assert second["severity"] == inspection.STATUS_WARN


# === host.capacity ================================================================================

def test_host_capacity_does_not_drift_on_ordinary_free_space_movement(store):
    """55.0% to 54.8% is a disk being used, not an event. It used to be a warning."""
    first = sweep(store, capacity(13_500_000), now=T0)
    second = sweep(store, capacity(13_450_000), now=T0 + timedelta(minutes=10))

    assert json.loads(first["value_json"])["filesystems"]["/data"]["free_percent"] != \
        json.loads(second["value_json"])["filesystems"]["/data"]["free_percent"]
    assert second["change_class"] == inspection.CHANGE_UNCHANGED
    assert second["severity"] == inspection.STATUS_OK


def test_host_capacity_still_reports_crossing_the_threshold(store):
    """Movement is ignored; crossing a band is not."""
    sweep(store, capacity(13_500_000), now=T0)                       # ~52% free
    second = sweep(store, capacity(4_000_000), now=T0 + timedelta(hours=1))   # ~15% free

    assert json.loads(second["material_json"])["filesystems"]["/data"] == "low"
    assert second["change_class"] == inspection.CHANGE_CHANGED
    # The collector's own threshold logic is what raises this, and it dominates the override.
    assert second["severity"] == inspection.STATUS_WARN


def test_host_capacity_recovery_is_recorded_but_does_not_warn(store):
    """A disk getting emptier is not a page.

    This is the one thing `_SCOPE_CHANGE_SEVERITY['host.capacity']` actually decides: the
    breach direction is already covered by the collector's own status, so the override can only
    affect the return to health.
    """
    sweep(store, capacity(4_000_000), now=T0)                                # low
    second = sweep(store, capacity(13_500_000), now=T0 + timedelta(hours=1))  # healthy again

    assert second["change_class"] == inspection.CHANGE_CHANGED
    assert second["severity"] == inspection.STATUS_OK


# === logs.signatures ==============================================================================

def test_logs_signatures_does_not_drift_on_occurrence_counts(store):
    """The same fault happening once more is the same fault.

    A rolling 24-hour window guarantees these counts move on their own, so digesting them made
    any site with a recurring error report drift on every sweep.
    """
    line = "connection refused for host db1"
    first = sweep(store, LogSignaturesCollector(runner=systemd_runner(journal_lines=(line,))))
    second = sweep(store, LogSignaturesCollector(
        runner=systemd_runner(journal_lines=(line, line, line))), now=T0 + timedelta(minutes=10))

    assert json.loads(second["value_json"])["signatures"][0]["count"] == 3
    assert second["change_class"] == inspection.CHANGE_UNCHANGED
    assert second["severity"] == inspection.STATUS_OK


def test_logs_signatures_still_reports_a_new_error(store):
    """A signature that was not there yesterday is exactly what this collector is for — and it
    is deliberately NOT overridden to informational, because nothing else would catch it."""
    sweep(store, LogSignaturesCollector(runner=systemd_runner(journal_lines=("timeout on db1",))))
    second = sweep(store, LogSignaturesCollector(
        runner=systemd_runner(journal_lines=("timeout on db1", "segfault in php-fpm"))),
        now=T0 + timedelta(minutes=10))

    assert second["change_class"] == inspection.CHANGE_CHANGED
    assert second["severity"] == inspection.STATUS_WARN


def test_logs_signatures_reports_a_fault_that_started_repeating(store):
    """Crossing into 'this is now a repeating fault' is a transition, not a count."""
    line = "connection refused for host db1"
    sweep(store, LogSignaturesCollector(runner=systemd_runner(journal_lines=(line,))))
    second = sweep(store, LogSignaturesCollector(
        runner=systemd_runner(journal_lines=(line,) * 40)), now=T0 + timedelta(minutes=10))

    assert json.loads(second["material_json"])["repeating"] == [line]
    assert second["change_class"] == inspection.CHANGE_CHANGED
    assert second["severity"] == inspection.STATUS_WARN


# === wp.inventory =================================================================================

def test_wp_inventory_does_not_drift_when_only_an_upstream_release_appears(store):
    """WordPress publishing a new version of a plugin is not a change to this site.

    The module docstring already said update availability must never influence status. It was
    true of the collector and false of the digest taken over its output.
    """
    before = (("akismet", "active", "5.3", "none"), ("wordfence", "active", "7.11", "none"))
    after = (("akismet", "active", "5.3", "available"), ("wordfence", "active", "7.11", "none"))

    first = sweep(store, wp_collector(before))
    second = sweep(store, wp_collector(after), now=T0 + timedelta(hours=1))

    assert json.loads(second["value_json"])["updates_available"] == ["akismet"]
    assert "updates_available" not in json.loads(second["material_json"])
    assert first["change_class"] == inspection.CHANGE_BASELINE
    assert second["change_class"] == inspection.CHANGE_UNCHANGED


def test_wp_inventory_still_reports_an_applied_update_informationally(store):
    """An installed version moving IS material — and stays informational, as before."""
    sweep(store, wp_collector((("akismet", "active", "5.3", "available"),
                               ("wordfence", "active", "7.11", "none"))))
    second = sweep(store, wp_collector((("akismet", "active", "5.4", "none"),
                                        ("wordfence", "active", "7.11", "none"))),
                   now=T0 + timedelta(hours=1))

    assert second["change_class"] == inspection.CHANGE_CHANGED
    assert second["severity"] == inspection.STATUS_OK


def test_wp_inventory_still_escalates_an_active_plugin_going_missing(store):
    """The differ's escalation survives the narrowing — it reads the full stored value."""
    sweep(store, wp_collector((("akismet", "active", "5.3", "none"),
                               ("wordfence", "active", "7.11", "none"))))
    second = sweep(store, wp_collector((("wordfence", "active", "7.11", "none"),)),
                   now=T0 + timedelta(hours=1))

    assert second["change_class"] == inspection.CHANGE_CHANGED
    assert second["severity"] in (inspection.STATUS_WARN, inspection.STATUS_ACTION)
    assert "akismet" in second["reason"]


# === the mechanism ================================================================================

def test_a_collector_that_declares_nothing_compares_its_whole_value():
    """The default is the old behaviour, which is correct for a reading that does not move."""
    result = inspection.CollectorResult(scope="s", status=inspection.STATUS_OK,
                                        value={"a": 1}, source="x")
    assert inspection.material_of(result) == {"a": 1}


def test_the_material_state_is_redacted_like_everything_else(store):
    """A projection of a value is not automatically safer than the value it came from."""
    class Leaky:
        id, version, scope = "leaky", "1", "leaky.scope"

        def collect(self, ctx):
            return inspection.CollectorResult(
                scope=self.scope, status=inspection.STATUS_OK, source="x",
                value={"api_token": "s3cret", "state": "up"},
                material={"api_token": "s3cret", "state": "up"})

    row = sweep(store, Leaky())
    assert "s3cret" not in row["material_json"]
    assert json.loads(row["material_json"])["api_token"] == "***redacted***"


def test_an_oversized_material_state_degrades_the_reading_to_unknown(store):
    """Same rule as the value: something we cannot record faithfully is not evidence."""
    class Huge:
        id, version, scope = "huge", "1", "huge.scope"

        def collect(self, ctx):
            return inspection.CollectorResult(
                scope=self.scope, status=inspection.STATUS_OK, source="x",
                value={"state": "up"}, material={"blob": "x" * 20_000})

    row = sweep(store, Huge())
    assert row["status"] == inspection.STATUS_UNKNOWN
    assert "not healthy" in row["reason"]


def test_the_stored_material_is_what_was_actually_compared(store):
    """`changed` is auditable rather than asserted: the row carries both digests, and the
    material digest is the one drift was decided on."""
    row = sweep(store, capacity(13_500_000))
    material = json.loads(row["material_json"])
    assert row["material_digest"] == inspection.value_digest(material)
    assert row["material_digest"] != row["value_digest"]


# === the migration ================================================================================

def test_a_predecessor_written_before_material_digests_is_compared_the_old_way():
    """The upgrade itself must not report every scope as changed.

    A v9 row has no material digest. Comparing a fresh material digest against it would differ
    for every narrowed collector at once — a fact about the migration, not about the host.
    """
    legacy = {"status": inspection.STATUS_OK, "value_digest": "abc"}

    assert inspection.classify(legacy, comparable=True,
                               digest="material-xyz", value_digest="abc") == \
        inspection.CHANGE_UNCHANGED
    assert inspection.classify(legacy, comparable=True,
                               digest="material-xyz", value_digest="def") == \
        inspection.CHANGE_CHANGED


def test_migrating_a_v9_store_adds_the_columns_and_reports_no_drift(tmp_path):
    """End to end over the real migration path, not a hand-built row."""
    import sqlite3

    from tc_growth.store import db

    path = tmp_path / "legacy.sqlite3"
    conn = db.connect(path)
    db.init_db(conn)
    # Rewind to v9 and drop the columns, so the migration has real work to do.
    conn.execute("ALTER TABLE observations DROP COLUMN material_json;")
    conn.execute("ALTER TABLE observations DROP COLUMN material_digest;")
    conn.execute("UPDATE schema_version SET version = 9;")
    conn.commit()
    conn.close()

    store = store_mod.open_store(str(path))
    try:
        # A v9-shaped row: recorded without any material at all.
        first = sweep(store, capacity(13_500_000), now=T0)
        assert first["material_json"] is not None  # migration ran before this write
    finally:
        store.close()

    # And the columns really are there, on the migrated file.
    conn = sqlite3.connect(path)
    names = {r[1] for r in conn.execute("PRAGMA table_info(observations)")}
    assert {"material_json", "material_digest"} <= names
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == db.SCHEMA_VERSION
    conn.close()


def test_a_v9_row_does_not_manufacture_drift_on_the_first_sweep_after_upgrade(store, monkeypatch):
    """The realistic upgrade: a row written by the OLD code, then a sweep by the new code."""
    collector = capacity(13_500_000)
    row = sweep(store, collector, now=T0)
    # Blank the material digest to make it a v9 row. Observations are append-only by trigger,
    # so this goes around it deliberately — the point is to reproduce a row the old code wrote.
    store._conn.execute("DROP TRIGGER trg_observations_no_update")
    store._conn.execute("UPDATE observations SET material_json = NULL, material_digest = NULL "
                        "WHERE id = ?", (row["id"],))
    store._conn.commit()

    second = sweep(store, collector, now=T0 + timedelta(hours=1))
    assert second["change_class"] == inspection.CHANGE_UNCHANGED


# === the regression, as one sweep of the real set =================================================

def test_an_idle_host_produces_no_attention_on_a_second_sweep(store):
    """The acceptance criterion, as a test: click, click, nothing shouts.

    This is the shape of the U5.2 on-host acceptance run — deploy, sweep, sweep again, confirm
    stable facts raise no false attention. Running that on the host with this defect present
    would have produced three warnings and burned the run.
    """
    def collectors():
        return [
            PlatformServicesCollector(
                runner=systemd_runner(last_trigger=T0 - timedelta(hours=1)), scan_log=__file__),
            LogSignaturesCollector(runner=systemd_runner()),
            capacity(13_500_000),
            wp_collector((("akismet", "active", "5.3", "none"),
                          ("wordfence", "active", "7.11", "none"))),
        ]

    inspection.run_inspection(store, collectors(), ctx(now=T0))
    run_id = inspection.run_inspection(store, collectors(), ctx(now=T0 + timedelta(minutes=10)))

    rows = store.list_observations(run_id)
    assert len(rows) == 4
    assert {r["change_class"] for r in rows} == {inspection.CHANGE_UNCHANGED}
    assert {r["severity"] for r in rows} == {inspection.STATUS_OK}
