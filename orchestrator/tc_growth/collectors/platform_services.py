"""`platform.services` — do the project's own scheduled mechanisms actually run?

**A configured schedule is not proof of execution** (issue #82 §6.3), and that distinction is
the whole point of this collector. `systemctl` will happily report a timer as `active` forever
while the job behind it has failed every night since March. So each unit is judged on evidence
of *execution* — last trigger, last exit status, how long ago — and its mere existence is
recorded but never treated as health.

The integrity scan is the case that proves the rule. It runs from **root's crontab**, which the
service user cannot read, and #82 §11 says to propose a privileged wrapper rather than assume
one. This collector adds no privilege: it observes the scan's *effect* instead — the mtime and
size of the log it appends to on every run. That is both privilege-free and better evidence,
because a log that stopped growing tells you the job stopped running, which reading the crontab
never would.

Note for whoever reads a stale scan result here: issue **#84** records that the v0 scan's own
operational acceptance was never completed, so `unknown` from this collector may be an honest
description of the scan's real state rather than a fault in the reading.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Callable

from ..inspection import (STATUS_ACTION, STATUS_OK, STATUS_UNKNOWN, STATUS_WARN,
                          CollectionContext, CollectorResult)
from ..runtime_identity import (AUTODEPLOY_TIMER, CONSOLE_UNIT, PROJECT_UNITS,
                                WEEKLY_REPORT_TIMER)
from ._exec import CommandResult, run_command, systemctl_show

#: The project's own units, and what "running" MEANS for each. Literals: no unit name is ever
#: derived from data.
#:
#: A timer needs a cadence, not just a state. `ActiveState=active` on a timer that has never
#: fired is the reassuring lie this collector exists to prevent (PR #86 review) — systemd is
#: perfectly happy to report a timer as active forever while the job behind it has not run since
#: March. So each timer declares how stale its last trigger may be before its health is in
#: doubt, and a timer that cannot prove it ever ran is `unknown`, never `ok`.
#:
#: The windows are the schedule plus generous slack, so an ordinary late run is not an alert.
UNITS = PROJECT_UNITS

UNIT_POLICY: dict[str, dict] = {
    # A long-running service proves itself by being active; it has no trigger cadence.
    CONSOLE_UNIT: {"kind": "service"},
    # Weekly, Monday 07:00 Europe/Madrid — 9 days covers a missed run plus a DST edge.
    WEEKLY_REPORT_TIMER: {"kind": "timer", "max_trigger_age_hours": 9 * 24},
    # Every 5 minutes; hours of silence means the deploy path is dead, not merely late.
    AUTODEPLOY_TIMER: {"kind": "timer", "max_trigger_age_hours": 3},
}

#: Where the v0 integrity scan appends. Overridable because the scan's own docs make it so.
SCAN_LOG_ENV = "TC_INSPECTOR_LOG"
DEFAULT_SCAN_LOG = "/var/log/tc-inspector.log"
#: The scan is scheduled daily, so a log untouched for this long means it is not running.
SCAN_STALE_HOURS = 48

Runner = Callable[..., CommandResult]


class PlatformServicesCollector:
    id = "platform.services"
    version = "1"
    scope = "platform.services"

    def __init__(self, *, runner: Runner | None = None, scan_log: str | None = None,
                 units: tuple[str, ...] = UNITS):
        self._run = runner or run_command
        self._scan_log = scan_log
        self._units = units

    def collect(self, ctx: CollectionContext) -> CollectorResult:
        now = ctx.now()
        units: dict[str, dict] = {}
        unreadable: list[str] = []
        failed: list[str] = []
        inactive: list[str] = []
        overdue: list[str] = []
        unproven: list[str] = []

        for unit in self._units:
            result = self._run(systemctl_show(unit))
            if result.unavailable or not result.ok:
                units[unit] = {"state": "unreadable"}
                unreadable.append(unit)
                continue
            props = _parse_properties(result.stdout)
            load, active = props.get("LoadState", ""), props.get("ActiveState", "")
            entry = {
                "load_state": load,
                "active_state": active,
                "sub_state": props.get("SubState", ""),
                "result": props.get("Result", ""),
                "last_exit_status": props.get("ExecMainStatus", ""),
                "last_run_age_hours": _age_hours(props.get("ExecMainExitTimestamp", ""), now),
                "last_trigger_age_hours": _usec_age_hours(props.get("LastTriggerUSec", ""), now),
            }
            units[unit] = entry

            if load == "not-found":
                # Not installed at all. That is a real absence, not a degraded reading.
                failed.append(unit)
                entry["verdict"] = "missing"
            elif props.get("Result") not in ("", "success") or active == "failed":
                failed.append(unit)
                entry["verdict"] = "failed"
            elif active not in ("active", "activating"):
                inactive.append(unit)
                entry["verdict"] = "inactive"
            else:
                verdict, note = _judge_execution(unit, entry)
                entry["verdict"] = verdict
                if note:
                    entry["note"] = note
                if verdict == "overdue":
                    overdue.append(unit)
                elif verdict == "unproven":
                    unproven.append(unit)

        scan = self._scan_evidence(now)
        value = {"units": units, "integrity_scan": scan}

        if failed:
            status, reason = STATUS_ACTION, (
                f"{', '.join(sorted(failed))} is not running as it should — the work it does is "
                f"not happening")
        elif overdue:
            status, reason = STATUS_WARN, (
                f"{', '.join(sorted(overdue))} is active but has not actually run within its "
                f"expected window — a schedule that stopped firing looks exactly like this")
        elif scan.get("state") == "stale":
            status, reason = STATUS_WARN, (
                f"the integrity scan's log has not been written for "
                f"{scan.get('age_hours')}h; a daily scan that stopped writing has stopped running")
        elif inactive or unreadable or unproven or scan.get("state") == "unreadable":
            bits = sorted(inactive + unreadable + unproven)
            status, reason = STATUS_UNKNOWN, (
                "could not confirm that " + (", ".join(bits) if bits else "the integrity scan")
                + " is running, so its state is unknown — not healthy")
        else:
            status, reason = STATUS_OK, (
                f"{len(self._units)} project unit(s) active and running on schedule; "
                f"integrity-scan log active")

        return CollectorResult(
            scope=self.scope, status=status, value=value, source="systemd",
            evidence="; ".join(f"{u}={units[u].get('active_state', units[u].get('state'))}"
                               for u in self._units),
            reason=reason, confidence="medium" if status == STATUS_UNKNOWN else "high",
            material=_material(units, scan))

    def _scan_evidence(self, now: datetime) -> dict:
        """The scan's effect, not its schedule. No privilege required to stat a log file."""
        path = self._scan_log or os.environ.get(SCAN_LOG_ENV, "") or DEFAULT_SCAN_LOG
        try:
            st = os.stat(path)
        except OSError as exc:
            return {"state": "unreadable", "path": path, "error": type(exc).__name__}
        age = (now - datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)).total_seconds() / 3600
        return {
            # "log activity observed" is the honest claim. mtime does NOT prove the cron fired:
            # #84 records that the v0 scan's operational acceptance — including whether it
            # writes this log on every invocation — was never completed. Until that is proven,
            # this evidence may downgrade health but must never be the reason for green.
            "state": "stale" if age > SCAN_STALE_HOURS else "log-activity-observed",
            "proves_scheduled_execution": False,
            "path": path, "age_hours": round(age, 1), "size_bytes": st.st_size,
        }


#: The fields whose change is a fact about the host. Everything else this collector records is
#: still stored as evidence — it just does not decide `changed`.
_MATERIAL_UNIT_FIELDS = ("state", "load_state", "active_state", "sub_state", "result",
                         "last_exit_status", "verdict")


def _material(units: dict[str, dict], scan: dict) -> dict:
    """The judged state, with the clock taken out of it.

    `last_trigger_age_hours` and `last_run_age_hours` are `now` minus a fixed instant, so they
    differ on every sweep of a host where nothing whatsoever happened — a digest over them can
    never equal its predecessor's, and this collector reported `changed` every single time it
    ran. The *verdict* those ages feed (`running` / `overdue` / `unproven`) is the fact worth
    comparing: it changes when the unit's health changes and holds still when it does not.

    Same argument for the scan: `age_hours` and `size_bytes` move whenever the log is appended
    to, which is the log doing its job. `state` — `log-activity-observed` versus `stale` versus
    `unreadable` — is what an owner would want to be told changed.
    """
    return {
        "units": {name: {k: entry[k] for k in _MATERIAL_UNIT_FIELDS if k in entry}
                  for name, entry in units.items()},
        "integrity_scan": {"state": scan.get("state"), "path": scan.get("path")},
    }


def _judge_execution(unit: str, entry: dict) -> tuple[str, str]:
    """Is this unit actually doing its job, or merely switched on?

    Returns one of `running` (proven), `overdue` (fired, but too long ago) or `unproven`
    (systemd cannot show that it ever fired). `unproven` is deliberately not a failure: the unit
    may be newly installed. It is also deliberately not `ok` — the whole point of this collector
    is that an active timer is not evidence its job has run (PR #86 review).
    """
    policy = UNIT_POLICY.get(unit, {})
    if policy.get("kind") != "timer":
        return "running", ""
    age = entry.get("last_trigger_age_hours")
    if age is None:
        return "unproven", ("systemd reports no last-trigger time, so there is no evidence this "
                            "timer has ever fired")
    limit = policy.get("max_trigger_age_hours")
    if limit is not None and age > limit:
        return "overdue", f"last fired {age}h ago, beyond its {limit}h expected window"
    return "running", f"last fired {age}h ago"


def _parse_properties(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


def _age_hours(stamp: str, now: datetime) -> float | None:
    """systemd's human timestamp, e.g. 'Fri 2026-08-07 21:00:00 UTC'. Unparseable is None, not 0
    — a zero would read as 'just ran'."""
    if not stamp or stamp in ("n/a", "0"):
        return None
    for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%a %Y-%m-%d %H:%M:%S"):
        try:
            when = datetime.strptime(stamp, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        return round((now - when).total_seconds() / 3600, 1)
    return None


def _usec_age_hours(usec: str, now: datetime) -> float | None:
    """LastTriggerUSec is microseconds since the epoch; 0 means 'never triggered'."""
    try:
        value = int(usec)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    when = datetime.fromtimestamp(value / 1_000_000, tz=timezone.utc)
    return round((now - when).total_seconds() / 3600, 1)
