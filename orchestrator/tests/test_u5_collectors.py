"""WP-U5.2 — the first four real collectors, their execution boundary and the Console trigger.

Every collector takes an injectable runner, so these tests drive fixed source output rather than
requiring wp-cli, systemd or a journal to exist. That is not only convenience: it is the only
way to exercise the failure paths — a missing program, a timeout, unparseable output — which are
the paths that decide whether this system tells the truth when something is wrong.

Unprivileged, so CI runs all of them.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from tc_growth import inspection, store as store_mod
from tc_growth.collectors import _exec, default_collectors
from tc_growth.collectors.host_capacity import HostCapacityCollector
from tc_growth.collectors.logs_signatures import LogSignaturesCollector, signature_of
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


def ctx(profile="tossa-cycling", environment="production", *, now=None):
    return inspection.CollectionContext(profile=profile, environment=environment,
                                        repo_commit="deadbeef", now=(lambda: now or T0))


def ok(stdout="", argv=("wp",)):
    return _exec.CommandResult(argv=argv, returncode=0, stdout=stdout, stderr="", ok=True)


def unavailable(detail="not installed", argv=("wp",)):
    return _exec.CommandResult(argv=argv, returncode=-1, stdout="", stderr="", ok=False,
                               unavailable=True, detail=detail)


def failed(stderr="boom", argv=("wp",)):
    return _exec.CommandResult(argv=argv, returncode=1, stdout="", stderr=stderr, ok=False)


# --- the execution boundary ---------------------------------------------------------------------

def test_only_permitted_command_forms_can_be_executed():
    """The boundary is closed over command FORMS, not program names. Allowlisting `wp` would
    permit `wp plugin install`; allowlisting `php` would permit anything at all."""
    for argv in (
        ("rm", "-rf", "/"),
        ("php", "-r", "system('id');"),                      # a general interpreter
        ("wp", "plugin", "install", "evil", "--activate"),   # write-capable wp subcommand
        ("wp", "user", "create", "eve", "eve@example.com", "--role=administrator"),
        ("wp", "core", "version", "--path=/etc"),            # extra argument, not the same form
        ("systemctl", "restart", "tc-console.service"),      # a state change
        ("journalctl", "-u", "tc-console.service"),          # unbounded read
    ):
        result = _exec.run_command(argv)
        assert result.unavailable, f"{argv} should not be runnable"
        assert "permitted read-only form" in result.detail
        assert result.returncode == -1


def test_no_general_interpreter_or_unused_program_is_reachable():
    """Nothing is permitted 'for future collectors'. Capability arrives with the collector that
    needs it and the review that approved it."""
    programs = {spec[0] for spec in _exec._ALLOWED_COMMANDS}
    assert programs == {"wp", "systemctl", "journalctl"}
    assert "php" not in programs and "du" not in programs and "stat" not in programs


def test_the_unit_slot_is_a_closed_set_not_a_pattern():
    """A syntactic rule would still permit reading any unit on the box. Read-only, but a wider
    host-introspection capability than the reviewed collectors need."""
    for bad in ("../../etc/passwd", "-u", "a.service; rm -rf /", "x" * 200, "notaunit",
                "ssh.service", "mysql.service", "sshd.service"):
        assert not _exec.is_allowed(_exec.systemctl_show(bad)), bad
        assert not _exec.is_allowed(_exec.journalctl_window(bad)), bad
    for good in _exec.ALLOWED_UNITS:
        assert _exec.is_allowed(_exec.systemctl_show(good))
    assert _exec.is_allowed(_exec.journalctl_probe("tc-console.service"))


def test_an_unrelated_but_syntactically_valid_unit_is_refused_at_the_door():
    result = _exec.run_command(_exec.journalctl_window("ssh.service"))
    assert result.unavailable and "permitted read-only form" in result.detail


class _FakeProc:
    """A child whose pipes the test controls, so termination is observable and deterministic.

    Real `os.pipe` file objects, because the drain loop registers them with a selector and needs
    genuine file descriptors.
    """

    def __init__(self, stdout: bytes = b"", stderr: bytes = b""):
        out_r, out_w = os.pipe()
        err_r, err_w = os.pipe()
        os.write(out_w, stdout)
        os.write(err_w, stderr)
        os.close(out_w)
        os.close(err_w)
        self.stdout = os.fdopen(out_r, "rb")
        self.stderr = os.fdopen(err_r, "rb")
        self.killed = False

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


def test_the_child_is_killed_the_moment_stdout_crosses_the_cap():
    """The invariant the docstring claimed. The previous version set a flag and kept draining to
    EOF, which bounded memory while leaving the process running."""
    proc = _FakeProc(stdout=b"x" * 4096)
    result = _exec._drain(proc, _exec.wp_core_version(), timeout_s=5, limit=64)

    assert proc.killed is True, "an overproducing child must be stopped, not merely ignored"
    assert result.unavailable
    assert "more than 64 bytes on stdout" in result.detail


def test_unbounded_stderr_is_also_stopped():
    """Unbounded stderr is unbounded output. The first version's overflow check ignored it
    entirely."""
    proc = _FakeProc(stdout=b"", stderr=b"e" * (_exec.STDERR_LIMIT + 5000))
    result = _exec._drain(proc, _exec.wp_core_version(), timeout_s=5,
                          limit=_exec.DEFAULT_OUTPUT_LIMIT)

    assert proc.killed is True
    assert result.unavailable
    assert "on stderr" in result.detail


def test_output_within_the_cap_is_returned_normally_and_the_child_is_not_killed():
    """The control: the bound must be invisible to a well-behaved command."""
    proc = _FakeProc(stdout=b"6.5.2\n")
    result = _exec._drain(proc, _exec.wp_core_version(), timeout_s=5, limit=64)

    assert proc.killed is False
    assert result.ok and result.stdout.strip() == "6.5.2"


def test_a_missing_program_is_unavailable_not_an_exception():
    result = _exec.run_command(_exec.wp_core_version())
    # wp-cli is not installed in CI; that must be evidence, not a crash.
    assert result.unavailable or result.ok or result.returncode >= 0


def test_output_is_bounded_while_the_child_runs_not_after_it_finishes():
    """The bound must stop production, not merely trim storage. A child that keeps talking past
    the cap is killed — `capture_output=True` would have buffered all of it first."""
    result = _exec.run_command(_exec.journalctl_probe("tc-console.service"), limit=8)
    # Either the journal is absent (unavailable) or it produced <= the cap; never more.
    assert result.unavailable or len(result.stdout.encode()) <= 8


def test_a_timeout_is_reported_as_unavailable_rather_than_hanging():
    result = _exec.run_command(_exec.journalctl_probe("tc-console.service"),
                               timeout_s=0.000001)
    assert result.unavailable or result.ok


def test_the_child_environment_carries_no_platform_configuration(monkeypatch):
    monkeypatch.setenv("TC_CONSOLE_TOKEN", "super-secret-token")
    assert "TC_CONSOLE_TOKEN" not in _exec._CHILD_ENV
    assert not any(k.startswith("TC_") for k in _exec._CHILD_ENV)


# --- wp.inventory ------------------------------------------------------------------------------

_PLUGINS = json.dumps([
    {"name": "woocommerce", "status": "active", "version": "9.1.2", "update": "none"},
    {"name": "akismet", "status": "inactive", "version": "5.3", "update": "available"},
    {"name": "zzz-tc-hardening", "status": "must-use", "version": "1.0", "update": "none"},
])
_THEMES = json.dumps([{"name": "shopkeeper", "status": "active", "version": "2.9.7"}])


def _wp_runner(core="6.5.2", plugins=_PLUGINS, themes=_THEMES):
    def run(argv, **kw):
        if argv[1] == "core":
            return ok(core)
        if argv[1] == "plugin":
            return ok(plugins)
        return ok(themes)
    return run


def test_wp_inventory_records_versions_and_separates_update_availability(tmp_path):
    """Issue #82 §6.1: observed drift, update availability and malfunction are three different
    things. An available update is recorded and must never move the status."""
    c = WpInventoryCollector(runner=_wp_runner(), docroot=str(tmp_path))
    result = c.collect(ctx())

    assert result.status == inspection.STATUS_OK
    assert result.value["core"]["version"] == "6.5.2"
    assert result.value["counts"] == {"plugins": 3, "active": 1, "must_use": 1, "themes": 1}
    assert result.value["updates_available"] == ["akismet"]
    assert "not a fault" in result.reason


def test_wp_inventory_requires_a_docroot_and_will_not_guess_one(monkeypatch):
    """Guessing a familiar path would mean inspecting whichever site lives there and filing it
    under this profile's name."""
    monkeypatch.delenv("TC_SITE_DOCROOT", raising=False)
    result = WpInventoryCollector(runner=_wp_runner()).collect(ctx())
    assert result.status == inspection.STATUS_UNKNOWN
    assert "TC_SITE_DOCROOT" in result.reason


def test_wp_inventory_is_unknown_when_wp_cli_is_missing(tmp_path):
    c = WpInventoryCollector(runner=lambda argv, **kw: unavailable("wp is not installed"),
                             docroot=str(tmp_path))
    result = c.collect(ctx())
    assert result.status == inspection.STATUS_UNKNOWN
    assert "unknown" in result.reason


def test_wp_inventory_refuses_a_partial_reading_rather_than_reporting_it(tmp_path):
    """Malformed source output is invalid evidence, not an empty success (issue #82 §14)."""
    c = WpInventoryCollector(runner=_wp_runner(plugins="{not json"), docroot=str(tmp_path))
    result = c.collect(ctx())
    assert result.status == inspection.STATUS_UNKNOWN
    assert "did not parse" in result.reason or "unusable" in result.reason


def test_a_wordpress_with_no_active_plugins_is_a_malfunction(tmp_path):
    plugins = json.dumps([{"name": "akismet", "status": "inactive", "version": "5.3"}])
    c = WpInventoryCollector(runner=_wp_runner(plugins=plugins), docroot=str(tmp_path))
    assert c.collect(ctx()).status == inspection.STATUS_ACTION


def test_a_plugin_update_is_informational_but_a_vanished_active_plugin_is_not(store, tmp_path):
    """The policy that keeps this page worth reading: routine maintenance is not an alert, and a
    plugin that was active and is not is worth attention (issue #82 §7)."""
    docroot = str(tmp_path)
    first = WpInventoryCollector(runner=_wp_runner(), docroot=docroot)
    inspection.run_inspection(store, [first], ctx(now=T0))

    # A version moves forward — routine.
    upgraded = json.dumps([
        {"name": "woocommerce", "status": "active", "version": "9.2.0", "update": "none"},
        {"name": "akismet", "status": "inactive", "version": "5.3", "update": "none"},
        {"name": "zzz-tc-hardening", "status": "must-use", "version": "1.0", "update": "none"},
    ])
    run = inspection.run_inspection(
        store, [WpInventoryCollector(runner=_wp_runner(plugins=upgraded), docroot=docroot)],
        ctx(now=T0))
    row = store.list_observations(run)[0]
    assert row["change_class"] == inspection.CHANGE_CHANGED
    assert row["severity"] == inspection.STATUS_OK          # informational, not a warning
    assert "version(s) changed" in row["reason"]

    # One of TWO active plugins disappears — not routine, but the site is still running, so
    # this must exercise the differ rather than the collector's own no-active-plugins check.
    two_active = json.dumps([
        {"name": "woocommerce", "status": "active", "version": "9.2.0", "update": "none"},
        {"name": "wp-rocket", "status": "active", "version": "3.15", "update": "none"},
    ])
    inspection.run_inspection(
        store, [WpInventoryCollector(runner=_wp_runner(plugins=two_active), docroot=docroot)],
        ctx(now=T0))
    gone = json.dumps([
        {"name": "woocommerce", "status": "active", "version": "9.2.0", "update": "none"},
    ])
    run = inspection.run_inspection(
        store, [WpInventoryCollector(runner=_wp_runner(plugins=gone), docroot=docroot)],
        ctx(now=T0))
    row = store.list_observations(run)[0]
    assert row["severity"] == inspection.STATUS_WARN
    assert "wp-rocket" in row["reason"]


# --- platform.services --------------------------------------------------------------------------

def _systemctl(states: dict[str, str]):
    def run(argv, **kw):
        unit = argv[2]
        state = states.get(unit, "active")
        if state == "missing":
            return ok("LoadState=not-found\nActiveState=inactive\nResult=success\n")
        return ok(f"LoadState=loaded\nActiveState={state}\nSubState=running\n"
                  f"Result={'failed' if state == 'failed' else 'success'}\n"
                  f"ExecMainStatus=0\nLastTriggerUSec=0\n")
    return run


def test_platform_services_reports_a_failed_unit_as_action(tmp_path):
    log = tmp_path / "scan.log"
    log.write_text("scan ok")
    c = PlatformServicesCollector(runner=_systemctl({"tc-weekly-report.timer": "failed"}),
                                  scan_log=str(log))
    result = c.collect(ctx())
    assert result.status == inspection.STATUS_ACTION
    assert "tc-weekly-report.timer" in result.reason


def test_platform_services_treats_a_missing_unit_as_a_real_absence(tmp_path):
    log = tmp_path / "scan.log"
    log.write_text("x")
    c = PlatformServicesCollector(runner=_systemctl({"tc-console.service": "missing"}),
                                  scan_log=str(log))
    assert c.collect(ctx()).status == inspection.STATUS_ACTION


def test_an_integrity_scan_log_that_stopped_growing_is_a_warning(tmp_path):
    """The privilege-free half of issue #82 §6.3: a configured schedule is not proof of
    execution, but a log that stopped being appended to is proof of its absence."""
    log = tmp_path / "scan.log"
    log.write_text("last run")
    old = (T0.timestamp() - 60 * 60 * 96)
    os.utime(log, (old, old))
    c = PlatformServicesCollector(runner=_systemctl({}), scan_log=str(log))
    result = c.collect(ctx())
    assert result.status == inspection.STATUS_WARN
    assert "stopped running" in result.reason


def test_an_unreadable_scan_log_is_unknown_not_healthy(tmp_path):
    c = PlatformServicesCollector(runner=_systemctl({}),
                                  scan_log=str(tmp_path / "nope.log"))
    result = c.collect(ctx())
    assert result.status == inspection.STATUS_UNKNOWN
    assert "unknown" in result.reason


def test_platform_services_never_reads_root_crontab():
    """U5 adds no privilege. The scan is observed through its effect, so `crontab` must appear
    nowhere in the allowlist or the collector."""
    import inspect as pyinspect

    from tc_growth.collectors import platform_services

    src = pyinspect.getsource(platform_services)
    # The word appears in the docstring explaining why it is NOT read; what must be absent is
    # crontab as a command.
    assert '"crontab"' not in src and "'crontab'" not in src
    programs = {spec[0] for spec in _exec._ALLOWED_COMMANDS}
    assert "crontab" not in programs and "sudo" not in programs


# --- host.capacity ------------------------------------------------------------------------------

class _Statvfs:
    def __init__(self, free_pct, total_gb=100.0, inode_pct=90.0):
        self.f_frsize = 4096
        self.f_blocks = int(total_gb * 1e9 / 4096)
        self.f_bavail = int(self.f_blocks * free_pct / 100)
        self.f_files = 1_000_000
        self.f_favail = int(self.f_files * inode_pct / 100)


def test_host_capacity_reports_free_space_and_does_not_forecast(tmp_path):
    """Refusing to forecast is the honest behaviour with two samples; a made-up 'days remaining'
    is a guess wearing a number's clothes."""
    c = HostCapacityCollector(paths=("/srv",), statvfs=lambda p: _Statvfs(55.0),
                              store_path=str(tmp_path / "s.db"))
    result = c.collect(ctx())
    assert result.status == inspection.STATUS_OK
    assert "not attempted" in result.value["forecast"]
    assert result.value["thresholds"]["verified"] is False


def test_a_nearly_full_small_filesystem_is_action_but_a_large_one_is_not():
    """Percent alone would cry wolf on a 4 TB disk at 8%; both signals must agree."""
    small = HostCapacityCollector(paths=("/srv",), statvfs=lambda p: _Statvfs(4.0, total_gb=50),
                                  store_path="")
    assert small.collect(ctx()).status == inspection.STATUS_ACTION

    large = HostCapacityCollector(paths=("/srv",), statvfs=lambda p: _Statvfs(8.0, total_gb=4000),
                                  store_path="")
    assert large.collect(ctx()).status == inspection.STATUS_WARN


def test_inode_exhaustion_is_caught_even_with_free_bytes():
    c = HostCapacityCollector(paths=("/srv",),
                              statvfs=lambda p: _Statvfs(80.0, inode_pct=2.0), store_path="")
    assert c.collect(ctx()).status == inspection.STATUS_ACTION


def test_an_unreadable_filesystem_is_unknown_not_healthy():
    def boom(path):
        raise OSError("permission denied")

    c = HostCapacityCollector(paths=("/srv",), statvfs=boom, store_path="")
    result = c.collect(ctx())
    assert result.status == inspection.STATUS_UNKNOWN
    assert "unknown" in result.reason


# --- logs.signatures ----------------------------------------------------------------------------

def test_a_signature_collapses_the_parts_that_vary():
    a = signature_of('2026-08-07 12:00:01 ERROR request 4f3a9b2c failed for "/es/alquiler"')
    b = signature_of('2026-08-07 13:22:47 ERROR request 9911aabb failed for "/en/rental"')
    assert a == b, "the same fault with different ids must collapse to one signature"


def test_repeated_errors_are_counted_not_stored_line_by_line():
    line = "ERROR database connection refused after 5 retries\n"
    c = LogSignaturesCollector(runner=_journal(filtered=line * 60))
    result = c.collect(ctx())
    assert result.status == inspection.STATUS_WARN
    assert result.value["distinct_signatures"] == 1
    assert result.value["signatures"][0]["count"] == 60
    # The raw lines are not what gets stored.
    assert len(json.dumps(result.value)) < 2000


def _journal(probe="Aug 07 12:00:00 console started", filtered=""):
    """The collector reads twice: an unfiltered probe (does this unit log here at all?) and the
    priority-filtered window. Only the second is about errors."""
    def run(argv, **kw):
        return ok(filtered if "-p" in argv else probe)
    return run


def test_no_errors_observed_names_its_window_and_source():
    """'Nothing found' and 'could not look' must never read the same (issue #82 §6.4)."""
    c = LogSignaturesCollector(runner=_journal())
    result = c.collect(ctx())
    assert result.status == inspection.STATUS_OK
    assert "24h" in result.reason and "tc-console.service" in result.reason


def test_a_unit_that_has_never_logged_is_unknown_not_error_free():
    """Found by running it: journalctl exits 0 with empty output for a unit that does not exist,
    so the filtered read alone would report 'no errors observed' for a service that has never
    run. An empty journal is an absence of evidence, not evidence of health."""
    c = LogSignaturesCollector(runner=_journal(probe=""))
    result = c.collect(ctx())
    assert result.status == inspection.STATUS_UNKNOWN
    assert "never written" in result.reason
    assert "not a clean bill of health" in result.reason


def test_an_unreadable_journal_is_unknown_and_names_the_dependency():
    c = LogSignaturesCollector(runner=lambda argv, **kw: unavailable("journalctl not installed"))
    result = c.collect(ctx())
    assert result.status == inspection.STATUS_UNKNOWN
    assert "not a clean bill of health" in result.reason
    assert "journalctl" in result.evidence


def test_a_journal_read_that_fails_is_also_unknown():
    c = LogSignaturesCollector(runner=lambda argv, **kw: failed("no such unit"))
    assert c.collect(ctx()).status == inspection.STATUS_UNKNOWN


def test_the_journal_read_is_bounded_at_the_source():
    """The cap is passed to journalctl, so the bytes never exist rather than being trimmed."""
    seen = {}

    def run(argv, **kw):
        if "-p" in argv:          # the filtered read — the one that is bounded for errors
            seen["argv"] = argv
            return ok("")
        return ok("console started")

    LogSignaturesCollector(runner=run).collect(ctx())
    assert "-n" in seen["argv"] and "2000" in seen["argv"]
    assert "-p" in seen["argv"] and "warning" in seen["argv"]


# --- the set, and the whole chain ---------------------------------------------------------------

def test_the_default_set_is_the_real_collectors_and_not_the_fixture():
    """Extended deliberately in U5.3a. The fixture stays out — it observes nothing real, and a
    production page should not carry a row that exists to exercise the machinery."""
    ids = [c.id for c in default_collectors()]
    assert ids == ["wp.inventory", "platform.services", "host.capacity", "logs.signatures",
                   "backup.coverage"]
    assert "fixture" not in ids
    assert "fixture" not in ids


def test_a_sweep_with_every_source_missing_still_produces_a_readable_page(store):
    """The worst realistic case on a fresh host: nothing is installed. The page must say
    `unknown` for every scope, not disappear and not go green."""
    run_id = inspection.run_inspection(store, default_collectors(), ctx(now=T0))
    rows = store.list_observations(run_id)
    assert len(rows) == len(default_collectors())
    assert all(r["severity"] in ("unknown", "ok", "warn", "action") for r in rows)
    assert any(r["severity"] == inspection.STATUS_UNKNOWN for r in rows)

    from tc_growth import console_views

    html = console_views.operations_health_body(
        store.latest_inspection_run(profile="tossa-cycling", environment="production"),
        store.latest_observations(profile="tossa-cycling", environment="production"),
        profile="tossa-cycling", environment="production", now=T0,
        effective=inspection.effective_status, freshness=inspection.freshness,
        rollup=inspection.rollup, value_of=inspection.observation_value)
    assert "Operations healthy" not in html
    assert "⚪ Unknown" in html


def test_collector_output_still_crosses_the_redaction_boundary(store, tmp_path):
    """U5.1's boundary must still hold now that real collectors feed it."""
    leaky = json.dumps([{"name": "TC_API_TOKEN=leakme", "status": "active", "version": "1"}])
    c = WpInventoryCollector(runner=_wp_runner(plugins=leaky), docroot=str(tmp_path))
    run_id = inspection.run_inspection(store, [c], ctx(now=T0))
    assert "leakme" not in store.list_observations(run_id)[0]["value_json"]


def test_the_console_trigger_takes_no_arguments_and_writes_nothing():
    """The registry entry is the contract: no args, its own surface, read-only, not a
    production write."""
    from tc_growth.core.actions import get_operation, validate_registry

    validate_registry()
    op = get_operation("run_inspection")
    assert op.allowed_args == ()
    assert op.self_service is False          # no argument-less path via /api/execute
    assert op.production_write is False
    assert op.approval.value == "none"
    assert dict(op.result_policy)[2] == "findings"   # findings are attention, not failure


def test_the_native_runner_stamps_the_identity_it_was_given(store, monkeypatch):
    """Amendment 1 through the executor: a sweep run on behalf of a named profile records that
    profile, whatever the process globals say."""
    from tc_growth.core.executor import ExecutionIdentity, _run_inspection

    monkeypatch.setenv("TC_SITE", "tour-de-girona")
    monkeypatch.setattr(store_mod, "open_store", lambda *a, **k: store)
    monkeypatch.setattr(store, "close", lambda: None)

    code, summary = _run_inspection({}, lambda ev: None,
                                    ExecutionIdentity("tossa-cycling", "production"))
    assert code in (0, 2)
    run = store.latest_inspection_run(profile="tossa-cycling", environment="production")
    assert run is not None and run["trigger"] == "console"
    assert store.latest_inspection_run(profile="tour-de-girona", environment="production") is None


# --- timer cadence: an active timer is not a running one (PR #86 review) -------------------------

def _timer_runner(*, last_trigger_usec: str = "0", active: str = "active",
                  result: str = "success", load: str = "loaded", unreadable: bool = False):
    """systemd's answer for a single timer under test."""
    def run(argv, **kw):
        if unreadable:
            return unavailable("systemctl is not available")
        return ok(f"LoadState={load}\nActiveState={active}\nSubState=waiting\n"
                  f"Result={result}\nExecMainStatus=0\n"
                  f"LastTriggerUSec={last_trigger_usec}\n")
    return run


def _usec_hours_ago(hours: float) -> str:
    return str(int((T0.timestamp() - hours * 3600) * 1_000_000))


def _one_timer(runner, tmp_path, fresh_log=True):
    log = tmp_path / "scan.log"
    log.write_text("scan")
    if not fresh_log:
        old = T0.timestamp() - 96 * 3600
        os.utime(log, (old, old))
    return PlatformServicesCollector(runner=runner, scan_log=str(log),
                                     units=("tc-autodeploy.timer",))


def test_a_timer_that_has_fired_recently_is_healthy(tmp_path):
    c = _one_timer(_timer_runner(last_trigger_usec=_usec_hours_ago(0.1)), tmp_path)
    result = c.collect(ctx())
    assert result.status == inspection.STATUS_OK
    assert result.value["units"]["tc-autodeploy.timer"]["verdict"] == "running"


def test_a_timer_that_has_never_fired_is_unknown_not_ok(tmp_path):
    """The false positive the previous version shipped: LoadState=loaded, ActiveState=active,
    Result=success, LastTriggerUSec=0 — and a green page. systemd is happy to call a timer
    active forever while the job behind it has never run."""
    c = _one_timer(_timer_runner(last_trigger_usec="0"), tmp_path)
    result = c.collect(ctx())
    assert result.status == inspection.STATUS_UNKNOWN
    assert result.value["units"]["tc-autodeploy.timer"]["verdict"] == "unproven"
    assert "no evidence" in result.value["units"]["tc-autodeploy.timer"]["note"]


def test_a_materially_overdue_timer_is_not_ok(tmp_path):
    """tc-autodeploy runs every 5 minutes; 9 hours of silence means the path is dead."""
    c = _one_timer(_timer_runner(last_trigger_usec=_usec_hours_ago(9)), tmp_path)
    result = c.collect(ctx())
    assert result.status == inspection.STATUS_WARN
    assert result.value["units"]["tc-autodeploy.timer"]["verdict"] == "overdue"


def test_cadence_is_per_unit_not_one_global_threshold(tmp_path):
    """A weekly report firing 30 hours ago is perfectly healthy; autodeploy is not."""
    log = tmp_path / "scan.log"
    log.write_text("scan")
    weekly = PlatformServicesCollector(
        runner=_timer_runner(last_trigger_usec=_usec_hours_ago(30)), scan_log=str(log),
        units=("tc-weekly-report.timer",))
    assert weekly.collect(ctx()).status == inspection.STATUS_OK

    auto = PlatformServicesCollector(
        runner=_timer_runner(last_trigger_usec=_usec_hours_ago(30)), scan_log=str(log),
        units=("tc-autodeploy.timer",))
    assert auto.collect(ctx()).status == inspection.STATUS_WARN


def test_a_failed_timer_is_action_whatever_its_trigger_age(tmp_path):
    c = _one_timer(_timer_runner(last_trigger_usec=_usec_hours_ago(0.1), result="exit-code"),
                   tmp_path)
    assert c.collect(ctx()).status == inspection.STATUS_ACTION


def test_an_unreadable_unit_is_unknown(tmp_path):
    c = _one_timer(_timer_runner(unreadable=True), tmp_path)
    assert c.collect(ctx()).status == inspection.STATUS_UNKNOWN


def test_a_long_running_service_needs_no_trigger_cadence(tmp_path):
    """A service proves itself by being active; requiring a trigger age would report every
    healthy daemon as unproven."""
    log = tmp_path / "scan.log"
    log.write_text("scan")
    c = PlatformServicesCollector(runner=_timer_runner(last_trigger_usec="0"),
                                  scan_log=str(log), units=("tc-console.service",))
    assert c.collect(ctx()).status == inspection.STATUS_OK


def test_the_scan_log_claims_only_activity_not_proof_of_a_scheduled_run(tmp_path):
    """#84 is open precisely because the v0 scan's operational acceptance was never completed,
    so mtime must not be presented as proof the cron fired."""
    c = _one_timer(_timer_runner(last_trigger_usec=_usec_hours_ago(0.1)), tmp_path)
    scan = c.collect(ctx()).value["integrity_scan"]
    assert scan["state"] == "log-activity-observed"
    assert scan["proves_scheduled_execution"] is False
