"""A deterministic collector that exists to exercise the machinery, not to observe a real system.

It is what proves the foundation works end to end — two sweeps, a real predecessor link, a
deterministic diff and an owner-visible state — without pretending to inspect infrastructure
whose access has not been agreed yet.

It is also the safe controlled fixture the on-host acceptance protocol needs (issue #82 §19.6):
setting `TC_U5_FIXTURE_VALUE` on the host changes what it reports, so drift and recovery can be
demonstrated without touching a real service, a real backup or production application code. The
variable is host configuration set by a maintainer — never a browser value, never a path, never
a command — and its content is bounded and redacted like any other evidence.
"""

from __future__ import annotations

import os

from ..inspection import STATUS_OK, STATUS_UNKNOWN, CollectionContext, CollectorResult

FIXTURE_ENV = "TC_U5_FIXTURE_VALUE"
#: Long enough to demonstrate drift, short enough that nobody is tempted to smuggle a payload.
MAX_FIXTURE_LEN = 200


class FixtureCollector:
    """Reports a stable value unless the host overrides it, so a repeat sweep is quiet."""

    id = "fixture"
    version = "1"
    scope = "fixture.probe"

    def __init__(self, value: str | None = None):
        #: Injected by tests; production reads the environment.
        self._value = value

    def collect(self, ctx: CollectionContext) -> CollectorResult:
        raw = self._value if self._value is not None else os.environ.get(FIXTURE_ENV, "stable")
        if len(raw) > MAX_FIXTURE_LEN:
            return CollectorResult(
                scope=self.scope,
                status=STATUS_UNKNOWN,
                value={"error": "fixture value exceeds the permitted length"},
                source=FIXTURE_ENV,
                evidence=f"{len(raw)} characters, limit {MAX_FIXTURE_LEN}",
                reason="the fixture source was not readable within its bounds",
            )
        return CollectorResult(
            scope=self.scope,
            status=STATUS_OK,
            value={"value": raw},
            source=FIXTURE_ENV,
            evidence=f"{FIXTURE_ENV}={raw}",
            reason="fixture probe — exercises the collection machinery, observes nothing real",
            confidence="high",
        )
