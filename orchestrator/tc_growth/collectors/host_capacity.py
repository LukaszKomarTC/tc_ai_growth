"""`host.capacity` — free disk and inode pressure on the filesystems this project uses.

No subprocess at all: `os.statvfs` answers the same question `df` does, without a command, a
parse or a timeout. The less this reaches outside the process, the less there is to review.

**It does not forecast** (issue #82 §9, and the review's instruction not to project a breach
until enough historical points exist). U5.2 records the numbers and says plainly that trend
projection begins once there is history to project from. A "~9 days until breach" computed from
two samples is a guess wearing a number's clothes, and the owner would rightly stop trusting the
page after the first one that was wrong.

The thresholds below are **proposed defaults, not verified policy**. Which filesystems count as
"the project's" is one of the assumptions listed for owner verification on issue #82, and the
reason is written so the page says so rather than implying a number was agreed.
"""

from __future__ import annotations

import os
from typing import Callable

from ..inspection import (STATUS_ACTION, STATUS_OK, STATUS_UNKNOWN, STATUS_WARN,
                          CollectionContext, CollectorResult)
from ..runtime_identity import DOCROOT_ENV, DOCROOT_PRESENT_STATES, probe_docroot

#: Proposed defaults pending owner confirmation. Percent free, per filesystem.
WARN_BELOW_PERCENT = 20.0
ACTION_BELOW_PERCENT = 10.0
#: A large filesystem can be under 10% and still have room; a small one at 20% may not. Both
#: have to be low before this escalates, so a 4 TB disk at 8% does not cry wolf.
ACTION_BELOW_FREE_GB = 5.0


class HostCapacityCollector:
    id = "host.capacity"
    version = "1"
    scope = "host.capacity"

    def __init__(self, *, paths: tuple[str, ...] | None = None,
                 statvfs: Callable[[str], os.statvfs_result] | None = None,
                 store_path: str | None = None):
        self._paths = paths
        self._statvfs = statvfs or os.statvfs
        self._store_path = store_path

    def _resolve_paths(self) -> tuple[str, ...]:
        if self._paths is not None:
            return self._paths
        candidates = [os.path.dirname(self._resolve_store()) or "/"]
        # A configured docroot this service cannot reach — or cannot even classify — is still
        # one of the project's filesystems, and dropping it silently made the page say "1 project
        # filesystem(s)" while the site's own disk went unwatched with nothing to say so (first
        # on-host acceptance run). It is included, fails to read, and degrades this scope to
        # `unknown` — correct, because that filesystem's capacity genuinely is unknown.
        #
        # `unverified` is in the present set deliberately: a probe error is the case where the
        # temptation to drop the path is strongest and the justification weakest (PR #89
        # re-review). Only `unset` and an ESTABLISHED absence are excluded — there is no
        # filesystem to report on, and an unreadable row for a path nobody configured is noise.
        docroot = os.environ.get(DOCROOT_ENV, "").strip()
        if docroot and probe_docroot(docroot) in DOCROOT_PRESENT_STATES:
            candidates.append(docroot)
        # De-duplicate while keeping order: two paths on one filesystem are one fact.
        seen, out = set(), []
        for path in candidates:
            if path not in seen:
                seen.add(path)
                out.append(path)
        return tuple(out)

    def _resolve_store(self) -> str:
        if self._store_path is not None:
            return self._store_path
        try:
            from ..store.db import resolved_db_path

            return str(resolved_db_path())
        except (Exception, SystemExit):
            # SystemExit is deliberate, not sloppy: config.load_env() raises it for an unknown
            # site profile. A capacity reading must not be able to kill an entire sweep because
            # some other part of the configuration is wrong.
            return ""

    def collect(self, ctx: CollectionContext) -> CollectorResult:
        filesystems: dict[str, dict] = {}
        unreadable: list[str] = []
        worst_percent: float | None = None
        critical: list[str] = []
        low: list[str] = []

        bands: dict[str, str] = {}

        for path in self._resolve_paths():
            try:
                st = self._statvfs(path)
            except OSError as exc:
                filesystems[path] = {"state": "unreadable", "error": type(exc).__name__}
                unreadable.append(path)
                bands[path] = "unreadable"
                continue
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            free_pct = round(free / total * 100, 1) if total else 0.0
            inodes_pct = (round(st.f_favail / st.f_files * 100, 1)
                          if getattr(st, "f_files", 0) else None)
            filesystems[path] = {
                "total_gb": round(total / 1e9, 1),
                "free_gb": round(free / 1e9, 1),
                "free_percent": free_pct,
                "inodes_free_percent": inodes_pct,
            }
            worst_percent = free_pct if worst_percent is None else min(worst_percent, free_pct)
            band = "healthy"
            if free_pct < ACTION_BELOW_PERCENT and free / 1e9 < ACTION_BELOW_FREE_GB:
                critical.append(path)
                band = "critical"
            elif free_pct < WARN_BELOW_PERCENT:
                low.append(path)
                band = "low"
            if inodes_pct is not None and inodes_pct < ACTION_BELOW_PERCENT:
                critical.append(path)
                band = "critical-inodes"
            bands[path] = band

        store = self._resolve_store()
        value = {
            "filesystems": filesystems,
            "store_bytes": (os.path.getsize(store)
                            if store and os.path.exists(store) else None),
            # Said in the record, not only in the docstring: nobody reading this row later
            # should think a forecast was attempted and came back empty.
            "forecast": "not attempted — trend projection needs history this increment does not "
                        "yet have",
            "thresholds": {"warn_below_percent": WARN_BELOW_PERCENT,
                           "action_below_percent": ACTION_BELOW_PERCENT,
                           "action_below_free_gb": ACTION_BELOW_FREE_GB,
                           "verified": False},
        }

        # Which BAND each filesystem is in, never how full it is. Free space moves every minute
        # on a live host: on a ten-minute re-run of a completely idle box, 55.0% became 54.8%
        # and this scope reported `changed`. A digest over a continuously-varying measurement is
        # a drift detector that fires on the measurement, and an owner who is warned about disk
        # movement every sweep learns to click past the row that finally matters (#82 §7).
        # Crossing a threshold IS material, and that is what a band records.
        material = {"filesystems": bands,
                    "thresholds": value["thresholds"]}

        if not filesystems or len(unreadable) == len(filesystems):
            # Nothing was read, so nothing was established — the one branch here that is not
            # comparable. A PARTIAL reading still is: its material names each path and its band,
            # `unreadable` included, so the record honestly represents what was and was not seen
            # and a band moving is a real change worth reporting (issue #82, U5.2d).
            return CollectorResult(
                scope=self.scope, status=STATUS_UNKNOWN, value=value, source="statvfs",
                evidence=f"unreadable: {', '.join(unreadable)}" if unreadable else "no paths",
                reason="no project filesystem could be read, so capacity is unknown",
                confidence="none", material=material, comparable=False)

        if critical:
            status, reason = STATUS_ACTION, (
                f"{sorted(set(critical))[0]} is nearly full — this becomes an outage before it "
                f"becomes an inconvenience")
        elif low:
            status, reason = STATUS_WARN, (
                f"{sorted(low)[0]} is below {WARN_BELOW_PERCENT:g}% free (threshold proposed, "
                f"not yet confirmed by the owner)")
        elif unreadable:
            status, reason = STATUS_UNKNOWN, (
                f"{', '.join(unreadable)} could not be read, so capacity is only partly known")
        else:
            status, reason = STATUS_OK, (
                f"lowest free space {worst_percent:g}% across "
                f"{len(filesystems)} project filesystem(s)")

        return CollectorResult(
            scope=self.scope, status=status, value=value, source="statvfs",
            evidence="; ".join(f"{p}={d.get('free_percent', d.get('state'))}%"
                               for p, d in filesystems.items()),
            reason=reason, confidence="high", material=material)
