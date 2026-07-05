"""Forensic investigation mode — a second operating mode beside the weekly report.

Given a question or anomaly, the agent runs read-only forensics (timelines, filtered GSC/GA4
queries) and returns an evidence-graded findings document that separates observations from
conclusions. Same read-only tools, same phase gate — different prompt and output shape.
"""

from __future__ import annotations

import datetime as dt
import time

from .config import model_for
from .core.approval import Phase
from .memory import known_cases_block
from .prompts import INVESTIGATION
from .report import persist_run
from .runtime.base import AgentRuntime
from .tools.load import load_all


def build_investigation(runtime: AgentRuntime, question: str, *, phase: Phase = Phase.READ_ONLY, persist: bool = True) -> str:
    """Run a forensic investigation for `question` and return the findings report."""
    tools = load_all()
    task = (
        f"Investigate the following, in FORENSIC mode (read-only, evidence-graded):\n\n{question}\n\n"
        "Build a timeline from Search Console (use page_filter + dimensions=['date'] over a long "
        "lookback, and check the most recent days for ongoing activity) and corroborate with GA4 "
        "where useful. Separate Observations from Hypotheses; list the Recommended verification a "
        "human must run before locking a conclusion; then give a calibrated Conclusion with a "
        "confidence level. Do not assert an active compromise without supporting verification."
    )
    memory = known_cases_block()
    if memory:
        task = f"{task}\n\n{memory}"
    started_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    t0 = time.perf_counter()
    result = runtime.run(
        system=INVESTIGATION,
        task=task,
        tools=tools,
        phase=phase,
        model=model_for("investigate"),
    )
    if persist:
        persist_run("investigate", result, started_at=started_at, duration_s=round(time.perf_counter() - t0, 2))
    header = f"# Forensic Investigation ({dt.date.today().isoformat()})\n\n_Question: {question}_\n\n"
    footer = ""
    if result.blocked_calls:
        names = sorted({c["tool"] for c in result.blocked_calls})
        footer = "\n\n---\n_Blocked (need higher phase / human approval): " + ", ".join(names) + "_"
    return header + result.text + footer
