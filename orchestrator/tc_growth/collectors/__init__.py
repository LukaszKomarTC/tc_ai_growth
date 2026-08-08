"""WP-U5 collectors. Each one is named, bounded, read-only, and reports `unknown` rather than
guessing when its source cannot be read.

U5.2 adds the first four real ones, deliberately a small set. Every external command goes
through `_exec.run_command` — fixed argv, allowlisted program, no shell, bounded time and
output, scrubbed environment — and every string they return crosses the redaction and bounding
boundary in `inspection.run_inspection` before it is stored or shown.

None of them needs privilege. `platform.services` is the case worth knowing about: the integrity
scan runs from root's crontab, which the service user cannot read, so it observes the scan's
*effect* — the log it appends to — rather than asking for a privileged wrapper to read the
schedule. That is both privilege-free and better evidence, since a configured schedule is not
proof of execution.

U5.3a adds `backup.coverage`, which is a different shape from the other four: it reads a declared
policy rather than a live source. That is the honest first increment for Backup Guardian, because
on this host the platform can reach none of the real backup sources — and a Guardian whose first
act is to state exactly what it cannot see, and what each gap would need, is more useful than one
reporting green from a config file.

Still absent by design: Plesk, Duplicator and Google Drive readings (U5.3b, gated on the
credential review and on R9), case creation (U5.4), and scheduled collection.
"""

from .backup_coverage import BackupCoverageCollector
from .fixture import FixtureCollector
from .host_capacity import HostCapacityCollector
from .logs_signatures import LogSignaturesCollector
from .platform_services import PlatformServicesCollector
from .wp_inventory import WpInventoryCollector

__all__ = [
    "BackupCoverageCollector",
    "FixtureCollector",
    "HostCapacityCollector",
    "LogSignaturesCollector",
    "PlatformServicesCollector",
    "WpInventoryCollector",
    "default_collectors",
]


def default_collectors() -> list:
    """The set a real sweep runs.

    The fixture is not in it: it observes nothing real, and a production page should not carry a
    row that exists to exercise the machinery. Tests and the on-host acceptance construct it
    explicitly when they want it.
    """
    return [
        WpInventoryCollector(),
        PlatformServicesCollector(),
        HostCapacityCollector(),
        LogSignaturesCollector(),
        BackupCoverageCollector(),
    ]
