"""WP-U5.2d — comparability is a separate property from health.

Found by the first on-host acceptance run, when the deliberate-change proof could not be
performed. `platform.services` was `unknown` — because `tc-autodeploy.timer` is inactive — and
while a scope read `unknown`, `classify` returned `unchanged` for ANY material change inside it:

    status=unknown  change=baseline    material=c7e1221bc5d0
    status=unknown  change=unchanged   material=24f03de8fde2
                           ^^^^^^^^^              genuinely different

The old rule was `if is_unknown and was_unknown: return CHANGE_UNCHANGED`, with a comment reading
"Still unreadable. Nothing was compared." That comment describes an unreadable source. It was
being applied to a reading where systemd answered every query and a material state was fully
established — the collector had merely *judged* the health unknown.

So `status` was answering two questions:

  * health — is this thing healthy / warning / action / not confirmable?
  * comparability — did this reading establish a material state that may be compared?

They are not the same property, and the consequence of conflating them is that **the change
detector went blind exactly when a scope was non-green** — the window in which movement matters
most. Comparability is now explicit, declared by the collector and persisted with the row.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from tc_growth import inspection, store as store_mod
from tc_growth.collectors._exec import CommandResult
from tc_growth.collectors.platform_services import PlatformServicesCollector

T0 = datetime(2026, 8, 8, 13, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def store():
    s = store_mod.open_store(":memory:")
    try:
        yield s
    finally:
        s.close()


def ctx(now=T0):
    return inspection.CollectionContext(profile="tossa-cycling", environment="production",
                                        repo_commit="deadbeef", now=lambda: now)


def systemd(weekly_active="active", readable=True):
    """A host where autodeploy is inactive — so health is `unknown` — and systemd answers fully."""
    def run(argv, **kw):
        unit = argv[2]
        if not readable:
            return CommandResult(argv=argv, returncode=-1, stdout="", stderr="", ok=False,
                                 unavailable=True, detail="systemctl is not installed")
        active = {"tc-console.service": "active",
                  "tc-weekly-report.timer": weekly_active,
                  "tc-autodeploy.timer": "inactive"}[unit]
        return CommandResult(argv=argv, returncode=0, ok=True, stderr="", stdout=(
            f"LoadState=loaded\nActiveState={active}\nSubState=running\nResult=success\n"
            "ExecMainStatus=0\nExecMainExitTimestamp=n/a\nLastTriggerUSec=0\n"))
    return run


def sweep(store, collector, now=T0):
    run_id = inspection.run_inspection(store, [collector], ctx(now))
    return store.list_observations(run_id)[0]


# === the defect, as a regression =================================================================

def test_a_material_change_under_a_sustained_unknown_is_reported(store):
    """The measurement that blocked the acceptance run, now the other way round.

    Both readings are health-`unknown` (autodeploy is inactive in both). The weekly timer stops
    between them — a real, deliberate, material change. It must be `changed`.
    """
    first = sweep(store, PlatformServicesCollector(runner=systemd(), scan_log=__file__))
    second = sweep(store, PlatformServicesCollector(
        runner=systemd(weekly_active="inactive"), scan_log=__file__), now=T0 + timedelta(minutes=5))

    assert first["status"] == inspection.STATUS_UNKNOWN
    assert second["status"] == inspection.STATUS_UNKNOWN      # health unchanged...
    assert second["change_class"] == inspection.CHANGE_CHANGED  # ...but the state moved
    assert first["material_digest"] != second["material_digest"]


def test_recovery_under_a_sustained_unknown_is_also_reported(store):
    """The other half of the acceptance fixture: restoring the timer must be visible too.

    A detector that notices the break and not the repair leaves the owner unable to confirm they
    fixed anything.
    """
    sweep(store, PlatformServicesCollector(runner=systemd(), scan_log=__file__))
    sweep(store, PlatformServicesCollector(runner=systemd(weekly_active="inactive"),
                                           scan_log=__file__), now=T0 + timedelta(minutes=5))
    restored = sweep(store, PlatformServicesCollector(runner=systemd(), scan_log=__file__),
                     now=T0 + timedelta(minutes=10))

    assert restored["change_class"] == inspection.CHANGE_CHANGED
    assert json.loads(restored["material_json"])["units"][
        "tc-weekly-report.timer"]["active_state"] == "active"


def test_an_idle_host_under_a_sustained_unknown_still_says_nothing(store):
    """The property that must survive the fix. Making `unknown` scopes comparable is only correct
    if they stay quiet when nothing happens — otherwise this trades a blind spot for noise."""
    sweep(store, PlatformServicesCollector(runner=systemd(), scan_log=__file__))
    second = sweep(store, PlatformServicesCollector(runner=systemd(), scan_log=__file__),
                   now=T0 + timedelta(hours=2))

    assert second["status"] == inspection.STATUS_UNKNOWN
    assert second["change_class"] == inspection.CHANGE_UNCHANGED
    assert second["severity"] == inspection.STATUS_UNKNOWN


# === the other direction: a genuinely unreadable source must not churn ===========================

def test_an_unreadable_source_does_not_drift_on_its_own_error_text(store):
    """The case the old rule was written for, and the only one it was right about.

    `comparable=False` means no comparison is attempted at all — so a changing error message from
    a source that was never read cannot manufacture drift.
    """
    class Flaky:
        id, version, scope = "flaky", "1", "flaky.scope"

        def __init__(self, detail):
            self.detail = detail

        def collect(self, c):
            return inspection.CollectorResult(
                scope=self.scope, status=inspection.STATUS_UNKNOWN, source="x",
                value={"error": self.detail}, evidence=self.detail,
                reason="this source could not be read", comparable=False)

    sweep(store, Flaky("connection refused on attempt 1"))
    second = sweep(store, Flaky("connection refused on attempt 2"), now=T0 + timedelta(minutes=5))

    assert second["change_class"] == inspection.CHANGE_UNCHANGED
    assert second["severity"] == inspection.STATUS_UNKNOWN


def test_systemd_itself_being_unreachable_is_not_comparable(store):
    """`platform.services` is comparable because systemd ANSWERED — not because of its verdict.
    When nothing answers, nothing was established."""
    row = sweep(store, PlatformServicesCollector(runner=systemd(readable=False),
                                                 scan_log=__file__))
    assert row["material_comparable"] == 0


def test_a_collector_that_raised_establishes_nothing(store):
    class Broken:
        id, version, scope = "broken", "1", "broken.scope"

        def collect(self, c):
            raise RuntimeError("boom")

    assert sweep(store, Broken())["material_comparable"] == 0


def test_an_oversized_value_is_not_comparable(store):
    """The replacement stub digests identically forever, so comparing it would read as a
    permanent `unchanged` about a reading that was never retained."""
    class Huge:
        id, version, scope = "huge", "1", "huge.scope"

        def collect(self, c):
            return inspection.CollectorResult(
                scope=self.scope, status=inspection.STATUS_OK, source="x",
                value={"blob": "x" * 20_000})

    row = sweep(store, Huge())
    assert row["material_comparable"] == 0
    assert row["status"] == inspection.STATUS_UNKNOWN


# === the contract: omission cannot mean "proven" =================================================

def test_a_collector_cannot_omit_comparability():
    """The fail-closed contract, as a mechanical fact rather than a convention.

    The first cut of this defaulted `comparable=True`, reasoning that a collector which returns
    has normally read something. That is backwards for an evidence system (PR #90 review):
    comparability is a POSITIVE claim, and a default makes *omission* mean *proven*. A collector
    added later that returns `status=unknown` and forgets the flag would silently become
    comparable and turn a changing error payload into false drift — and U5.3 adds collectors
    next, handing the footgun straight to the code most likely to fire it.

    Required and keyword-only, so the author has to answer the question once, in writing.
    """
    with pytest.raises(TypeError, match="comparable"):
        inspection.CollectorResult(scope="s", status=inspection.STATUS_OK,
                                   value={"a": 1}, source="x")

    # And it cannot be smuggled in positionally either.
    with pytest.raises(TypeError):
        inspection.CollectorResult("s", inspection.STATUS_OK, {"a": 1}, "x", "", "", None,
                                   None, True)


def test_a_collector_that_forgets_the_flag_cannot_produce_drift(store):
    """Criterion 3 end to end: a forgetful collector fails loudly at the boundary and its reading
    becomes `unknown`, rather than quietly claiming comparability it never established."""
    class Forgetful:
        id, version, scope = "forgetful", "1", "forgetful.scope"

        def __init__(self, payload):
            self.payload = payload

        def collect(self, c):
            return inspection.CollectorResult(          # noqa: no `comparable=` on purpose
                scope=self.scope, status=inspection.STATUS_UNKNOWN, source="x",
                value={"error": self.payload})

    first = sweep(store, Forgetful("attempt 1"))
    second = sweep(store, Forgetful("attempt 2"), now=T0 + timedelta(minutes=5))

    assert first["material_comparable"] == 0
    assert second["change_class"] != inspection.CHANGE_CHANGED


# === each real collector's branches ==============================================================

def test_platform_services_branches():
    """Comparable when systemd answered — whatever its verdict; not when it did not."""
    c = ctx()
    assert PlatformServicesCollector(runner=systemd(), scan_log=__file__).collect(c).comparable
    assert not PlatformServicesCollector(runner=systemd(readable=False),
                                         scan_log=__file__).collect(c).comparable


def test_host_capacity_branches(tmp_path):
    """A partial reading is comparable — its material names every path and band, `unreadable`
    included. Nothing readable at all is not."""
    from tc_growth.collectors.host_capacity import HostCapacityCollector

    class Stat:
        f_frsize, f_blocks, f_bavail, f_files, f_favail = 4096, 26_000_000, 13_000_000, 10, 9

    def half(path):
        if path == "/unreadable":
            raise PermissionError(13, "denied")
        return Stat()

    partial = HostCapacityCollector(paths=(str(tmp_path), "/unreadable"), statvfs=half,
                                    store_path="").collect(ctx())
    assert partial.comparable
    assert partial.status == inspection.STATUS_UNKNOWN     # honest about the half it missed

    def none(path):
        raise PermissionError(13, "denied")

    assert not HostCapacityCollector(paths=("/a", "/b"), statvfs=none,
                                     store_path="").collect(ctx()).comparable


def test_logs_signatures_branches():
    """A read journal is comparable; an unreadable one is not — that is the case the old
    classifier comment described, and the only one it was right about."""
    from tc_growth.collectors._exec import CommandResult
    from tc_growth.collectors.logs_signatures import LogSignaturesCollector

    def journal(readable):
        def run(argv, **kw):
            if not readable:
                return CommandResult(argv=argv, returncode=1, stdout="", stderr="denied",
                                     ok=False)
            if "-p" not in argv:
                return CommandResult(argv=argv, returncode=0, stdout="started\n", stderr="",
                                     ok=True)
            return CommandResult(argv=argv, returncode=0, stdout="timeout on db1\n", stderr="",
                                 ok=True)
        return run

    assert LogSignaturesCollector(runner=journal(True)).collect(ctx()).comparable
    assert not LogSignaturesCollector(runner=journal(False)).collect(ctx()).comparable


def test_wp_inventory_branches(tmp_path):
    """An inventory that parsed is comparable; every unreadable docroot state is not."""
    import json as _json

    from tc_growth.collectors._exec import CommandResult
    from tc_growth.collectors.wp_inventory import WpInventoryCollector

    def wp(argv, **kw):
        if argv[:3] == ("wp", "core", "version"):
            return CommandResult(argv=argv, returncode=0, stdout="6.8.1\n", stderr="", ok=True)
        if argv[:3] == ("wp", "plugin", "list"):
            return CommandResult(argv=argv, returncode=0, ok=True, stderr="", stdout=_json.dumps(
                [{"name": "akismet", "status": "active", "version": "5.3", "update": "none"}]))
        return CommandResult(argv=argv, returncode=0, stdout="[]", stderr="", ok=True)

    assert WpInventoryCollector(runner=wp, docroot=str(tmp_path)).collect(ctx()).comparable
    for docroot in ("", "/no/such/docroot"):
        assert not WpInventoryCollector(runner=wp, docroot=docroot).collect(ctx()).comparable


def test_the_fixture_collector_states_it_too():
    from tc_growth.collectors.fixture import FixtureCollector

    assert FixtureCollector("stable").collect(ctx()).comparable
    assert not FixtureCollector("x" * 10_000).collect(ctx()).comparable


# === the transitions ============================================================================

def test_becoming_comparable_is_appeared_and_losing_it_is_disappeared(store):
    class Source:
        id, version, scope = "src", "1", "src.scope"

        def __init__(self, comparable):
            self.comparable = comparable

        def collect(self, c):
            return inspection.CollectorResult(
                scope=self.scope,
                status=inspection.STATUS_OK if self.comparable else inspection.STATUS_UNKNOWN,
                source="x", value={"state": "up"}, comparable=self.comparable)

    sweep(store, Source(False))
    appeared = sweep(store, Source(True), now=T0 + timedelta(minutes=5))
    disappeared = sweep(store, Source(False), now=T0 + timedelta(minutes=10))

    assert appeared["change_class"] == inspection.CHANGE_APPEARED
    assert disappeared["change_class"] == inspection.CHANGE_DISAPPEARED


def test_classification_no_longer_consults_status_at_all():
    """Structural: the same status pair yields different verdicts purely on comparability."""
    prev = {"status": inspection.STATUS_UNKNOWN, "value_digest": "v",
            "material_digest": "m1", "material_comparable": 1}

    assert inspection.classify(prev, comparable=True, digest="m2") == inspection.CHANGE_CHANGED
    assert inspection.classify(prev, comparable=True, digest="m1") == inspection.CHANGE_UNCHANGED
    assert inspection.classify(prev, comparable=False, digest="m2") == \
        inspection.CHANGE_DISAPPEARED


# === legacy rows ================================================================================

def test_a_legacy_row_reproduces_the_old_classifier_rather_than_guessing():
    """A pre-v11 row has no stored comparability. Inferring from `status` is exactly what this
    change removes — but for a legacy row there is nothing else, and reproducing the OLD
    behaviour is the one choice that cannot invent a transition at the migration."""
    healthy_legacy = {"status": inspection.STATUS_OK, "value_digest": "abc",
                      "material_digest": "m1"}
    unknown_legacy = {"status": inspection.STATUS_UNKNOWN, "value_digest": "abc",
                      "material_digest": "m1"}

    assert inspection.was_comparable(healthy_legacy) is True
    assert inspection.was_comparable(unknown_legacy) is False

    # A healthy legacy predecessor compares normally — no spurious `appeared` for every scope.
    assert inspection.classify(healthy_legacy, comparable=True, digest="m1") == \
        inspection.CHANGE_UNCHANGED
    # An unknown legacy predecessor yields ONE `appeared`, which the review accepted explicitly —
    # and critically NOT `changed`, which would be a fact about the migration, not the host.
    assert inspection.classify(unknown_legacy, comparable=True, digest="m2") == \
        inspection.CHANGE_APPEARED


def test_a_stored_false_is_honoured_not_overridden_by_a_healthy_status():
    """Once the property exists it is authoritative; status must not be consulted behind it."""
    prev = {"status": inspection.STATUS_OK, "value_digest": "abc", "material_digest": "m1",
            "material_comparable": 0}
    assert inspection.was_comparable(prev) is False
    assert inspection.classify(prev, comparable=True, digest="m2") == inspection.CHANGE_APPEARED


def test_the_migration_adds_the_column_without_rewriting_rows(tmp_path):
    import sqlite3

    from tc_growth.store import db

    path = tmp_path / "legacy.sqlite3"
    conn = db.connect(path)
    db.init_db(conn)
    conn.execute("ALTER TABLE observations DROP COLUMN material_comparable;")
    conn.execute("UPDATE schema_version SET version = 10;")
    conn.commit()
    conn.close()

    store = store_mod.open_store(str(path))
    try:
        row = sweep(store, PlatformServicesCollector(runner=systemd(), scan_log=__file__))
        assert row["material_comparable"] == 1
    finally:
        store.close()

    conn = sqlite3.connect(path)
    names = {r[1] for r in conn.execute("PRAGMA table_info(observations)")}
    assert "material_comparable" in names
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == db.SCHEMA_VERSION
    conn.close()
