"""Validation tooling (Release 0.3 — Type B: test harnesses, not product features).

Two things live here:

1. `run_draft_test` — the launcher the VALIDATION.md content tests require: a supervised,
   human-initiated run at DRAFTS phase so the existing draft tools (wp_create_seo_draft,
   wp_create_product_revision, ...) are admitted by the gate. The connector only reaches
   staging; nothing here changes production behavior or adds capabilities — the tools and the
   gate predate this file.

2. `validation_status` — parses docs/VALIDATION.md (the single source of truth; humans tick
   boxes there with evidence) into structured PASS/pending data for the CLI and the dashboard's
   Validation Report page. Read-only rendering of the acceptance record.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from pathlib import Path

from .config import ENV_PATH, model_for
from .core.approval import Phase
from .memory import known_cases_block
from .prompts import COORDINATOR
from .runtime.base import AgentRuntime
from .tools.load import load_all

VALIDATION_DOC = ENV_PATH.parents[1] / "docs" / "VALIDATION.md"

_DRAFT_TASK = """\
VALIDATION DRAFT TEST (staging only). Perform exactly this drafting task:

{instruction}

Rules:
- First read what you need (wp_seo_audit / wp_list) to ground the draft in the current page.
- Create the draft with the appropriate draft tool (wp_create_seo_draft for titles/meta,
  wp_create_product_revision for product copy). NEVER publish; drafts/revisions only.
- SCOPE: change only what the task above asks. Do NOT change the slug/URL or anything structural
  unless the task explicitly says so — recommend such changes separately, with risks, instead.
- MULTILINGUAL: if this page has a language twin (ES/EN), state which twin you found, and
  recommend the parallel draft for it — the pair must never desynchronise.
- Then report: the tool result (draft/revision id), the exact copy you wrote, and anything a
  human reviewer should check in staging wp-admin.
"""


def run_draft_test(runtime: AgentRuntime, instruction: str, *, phase: Phase = Phase.DRAFTS,
                   persist: bool = True) -> str:
    """Run one supervised draft task at DRAFTS phase against the (staging) connector."""
    from .report import persist_run  # late import to avoid a cycle

    tools = load_all()
    task = _DRAFT_TASK.format(instruction=instruction)
    memory = known_cases_block()
    if memory:
        task = f"{task}\n\n{memory}"
    started_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    t0 = time.perf_counter()
    result = runtime.run(
        system=COORDINATOR,
        task=task,
        tools=tools,
        phase=phase,
        model=model_for("draft-test"),
    )
    if persist:
        persist_run("draft-test", result, started_at=started_at,
                    duration_s=round(time.perf_counter() - t0, 2))
    header = f"# Draft Test ({dt.date.today().isoformat()})\n\n_Task: {instruction}_\n\n"
    footer = ""
    if result.blocked_calls:
        names = sorted({c["tool"] for c in result.blocked_calls})
        footer = "\n\n---\n_Blocked (gate refused): " + ", ".join(names) + "_"
    return header + result.text + footer


_SECTION = re.compile(r"^##\s+(?P<name>.+?)\s*$")
_ITEM = re.compile(r"^- \[(?P<mark>[ xX])\]\s+(?P<text>.+?)\s*$")


def validation_status(path: str | Path | None = None) -> dict:
    """Parse the validation checklist into {sections: [...], done, total, percent}."""
    doc = Path(path) if path else VALIDATION_DOC
    sections: list[dict] = []
    current: dict | None = None
    try:
        lines = doc.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"sections": [], "done": 0, "total": 0, "percent": 0}
    for line in lines:
        m = _SECTION.match(line)
        if m:
            current = {"name": m.group("name"), "items": []}
            sections.append(current)
            continue
        m = _ITEM.match(line)
        if m and current is not None:
            current["items"].append(
                {"done": m.group("mark").lower() == "x", "text": m.group("text")}
            )
    sections = [s for s in sections if s["items"]]
    done = sum(1 for s in sections for i in s["items"] if i["done"])
    total = sum(len(s["items"]) for s in sections)
    for s in sections:
        s["done"] = sum(1 for i in s["items"] if i["done"])
        s["total"] = len(s["items"])
        s["pass"] = s["done"] == s["total"]
    return {
        "sections": sections,
        "done": done,
        "total": total,
        "percent": round(100 * done / total) if total else 0,
    }
