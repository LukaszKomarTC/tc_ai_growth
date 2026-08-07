"""`logs.signatures` — repeated error signatures in a bounded, named window.

The rule that shapes this collector: **no uncontrolled log tail reaches the model, the browser
or the durable record** (issue #82 §6.4). What is stored is not log lines but *signatures* —
each line stripped of the parts that make it unique (timestamps, numbers, hex, quoted strings,
paths) and counted. That keeps the record small, makes "the same error 400 times" one fact
instead of four hundred, and means a new signature appearing is genuinely new rather than the
same fault with a different request id.

Bounds are hard: a fixed window, a line cap passed to `journalctl` itself, a priority floor, a
signature length cap and a top-N. Redaction happens again at the U5 boundary, but a signature
that never contained the payload is better than one that had it removed.

`"no errors observed"` always names its window and source. An empty result from a 24-hour
journal read is a different claim from an empty result because the journal could not be read,
and the second is `unknown`.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Callable

from ..inspection import (STATUS_OK, STATUS_UNKNOWN, STATUS_WARN, CollectionContext,
                          CollectorResult)
from ._exec import CommandResult, run_command

WINDOW = "24 hours ago"
WINDOW_HOURS = 24
#: journalctl enforces this itself, so the cap applies before the bytes exist rather than after.
MAX_LINES = 2000
#: Warning and above. Info-level chatter is not what this collector is for.
PRIORITY = "warning"
UNIT = "tc-console.service"
MAX_SIGNATURE_LEN = 160
TOP_N = 12
#: Enough repetition to mean something rather than one bad request.
WARN_AT_OCCURRENCES = 25

_NORMALIZERS = (
    (re.compile(r"\b[0-9a-fA-F]{8,}\b"), "<hex>"),
    (re.compile(r"\b\d[\d:.,-]*\b"), "<n>"),
    (re.compile(r"([\"'])(?:(?!\1).)*\1"), "<str>"),
    (re.compile(r"(?<=\s)/[^\s]+"), "<path>"),
    (re.compile(r"\s+"), " "),
)

Runner = Callable[..., CommandResult]


def signature_of(line: str) -> str:
    """Strip what varies, keep what recurs. Deterministic — the same fault always collapses to
    the same signature, or counting them would be meaningless."""
    text = line.strip()
    for pattern, replacement in _NORMALIZERS:
        text = pattern.sub(replacement, text)
    return text.strip()[:MAX_SIGNATURE_LEN]


class LogSignaturesCollector:
    id = "logs.signatures"
    version = "1"
    scope = "logs.signatures"

    def __init__(self, *, runner: Runner | None = None, unit: str = UNIT):
        self._run = runner or run_command
        self._unit = unit

    def collect(self, ctx: CollectionContext) -> CollectorResult:
        window = {"unit": self._unit, "window_hours": WINDOW_HOURS, "priority": PRIORITY,
                  "line_cap": MAX_LINES}

        # First, evidence that this unit logs here AT ALL — found by running it: `journalctl`
        # exits 0 with empty output for a unit that does not exist, so the filtered read alone
        # cannot tell "no errors in 24h" from "no such unit, no journal, nothing was ever
        # inspected". Reporting the second as the first is precisely the reassuring lie this
        # collector exists to avoid (issue #82 §6.4).
        probe = self._run(("journalctl", "-u", self._unit, "--no-pager", "-o", "cat", "-n", "1"))
        if probe.unavailable or not probe.ok:
            return self._unknown(window, (probe.detail or probe.stderr.strip())[:300],
                                 f"the journal for {self._unit} could not be read")
        if not probe.stdout.strip():
            return self._unknown(
                window, f"{self._unit} has no journal entries at all",
                f"{self._unit} has never written to this journal, so there is nothing to "
                f"inspect — absence of entries is not absence of errors")

        argv = ("journalctl", "-u", self._unit, "--since", WINDOW, "--no-pager",
                "-o", "cat", "-n", str(MAX_LINES), "-p", PRIORITY)
        result = self._run(argv)

        if result.unavailable or not result.ok:
            return self._unknown(window, (result.detail or result.stderr.strip())[:300],
                                 f"the journal for {self._unit} could not be read")

        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        counts = Counter(signature_of(ln) for ln in lines if signature_of(ln))
        top = counts.most_common(TOP_N)
        value = {
            **window,
            "lines_inspected": len(lines),
            "distinct_signatures": len(counts),
            "signatures": [{"signature": sig, "count": n} for sig, n in top],
            "truncated": len(counts) > TOP_N,
        }

        if not counts:
            return CollectorResult(
                scope=self.scope, status=STATUS_OK, value=value, source="journalctl",
                evidence=f"{self._unit}, last {WINDOW_HOURS}h, priority {PRIORITY} and above",
                reason=(f"no errors observed for {self._unit} in the last {WINDOW_HOURS}h at "
                        f"priority {PRIORITY} and above"),
                confidence="high")

        worst_sig, worst_count = top[0]
        if worst_count >= WARN_AT_OCCURRENCES:
            return CollectorResult(
                scope=self.scope, status=STATUS_WARN, value=value, source="journalctl",
                evidence=f"{self._unit}, last {WINDOW_HOURS}h",
                reason=(f"one error signature recurred {worst_count} times in {WINDOW_HOURS}h — "
                        f"a repeating fault, not a one-off"),
                confidence="high")

        return CollectorResult(
            scope=self.scope, status=STATUS_OK, value=value, source="journalctl",
            evidence=f"{self._unit}, last {WINDOW_HOURS}h",
            reason=(f"{len(counts)} error signature(s) in {WINDOW_HOURS}h, none recurring more "
                    f"than {worst_count} times"),
            confidence="high")

    def _unknown(self, window: dict, evidence: str, why: str) -> CollectorResult:
        """Every unreadable path lands here, so none of them can accidentally look healthy."""
        return CollectorResult(
            scope=self.scope, status=STATUS_UNKNOWN,
            value={"error": "journal unavailable", **window}, source="journalctl",
            evidence=evidence,
            reason=f"{why}, so recent errors are unknown — this is not a clean bill of health",
            confidence="none")
