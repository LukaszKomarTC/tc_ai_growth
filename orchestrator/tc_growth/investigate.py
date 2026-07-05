"""Forensic investigation mode — a second operating mode beside the weekly report.

Given a question or anomaly, the agent runs read-only forensics (timelines, filtered GSC/GA4
queries) and returns an evidence-graded findings document that separates observations from
conclusions. Same read-only tools, same phase gate — different prompt and output shape.
"""

from __future__ import annotations

import datetime as dt

from .config import get_settings
from .core.approval import Phase
from .prompts import INVESTIGATION
from .runtime.base import AgentRuntime
from .tools.load import load_all


def build_investigation(runtime: AgentRuntime, question: str, *, phase: Phase = Phase.READ_ONLY) -> str:
    """Run a forensic investigation for `question` and return the findings report."""
    tools = load_all()
    s = get_settings()
    task = (
        f"Investigate the following, in FORENSIC mode (read-only, evidence-graded):\n\n{question}\n\n"
        "Build a timeline from Search Console (use page_filter + dimensions=['date'] over a long "
        "lookback, and check the most recent days for ongoing activity) and corroborate with GA4 "
        "where useful. Separate Observations from Hypotheses; list the Recommended verification a "
        "human must run before locking a conclusion; then give a calibrated Conclusion with a "
        "confidence level. Do not assert an active compromise without supporting verification."
    )
    result = runtime.run(
        system=INVESTIGATION,
        task=task,
        tools=tools,
        phase=phase,
        model=s.ai_model,
    )
    header = f"# Forensic Investigation ({dt.date.today().isoformat()})\n\n_Question: {question}_\n\n"
    footer = ""
    if result.blocked_calls:
        names = sorted({c["tool"] for c in result.blocked_calls})
        footer = "\n\n---\n_Blocked (need higher phase / human approval): " + ", ".join(names) + "_"
    return header + result.text + footer
