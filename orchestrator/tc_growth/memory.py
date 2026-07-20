"""Case memory -> prompt context (Phase 2, slice 3).

Turns the stored cases into a compact "Known cases" block injected into the weekly report and
investigations, so the coordinator consults what it already knows before flagging anything as new.
This is what stops the agent re-raising a resolved incident (e.g. the Merchant Center tobacco spam)
as a fresh critical threat every week.

Best-effort by construction: if the store is missing or unreadable, it returns "" and the run
proceeds exactly as before.
"""

from __future__ import annotations


def _case_line(case) -> str:
    bits = [case.status]
    if case.priority:
        bits.append(case.priority)
    if case.confidence:
        bits.append(f"conf {case.confidence}")
    ref = case.ref or f"#{case.id}"
    return f"- {ref} — [{' · '.join(bits)}] {case.title}"


def _decision_line(decision, case_ref_by_id) -> str:
    link = f" (case {case_ref_by_id.get(decision.case_id, f'#{decision.case_id}')})" if decision.case_id else ""
    state = decision.status
    if decision.outcome:  # execution result recorded — "approved · executed: worked"
        state += f" · executed: {decision.outcome}"
    return f"- D#{decision.id} [{state}] {decision.title}{link}"


def known_cases_block(store=None, *, limit: int = 25) -> str:
    """A markdown memory block for task injection — known cases + the decision queue — or ''
    when there is nothing / no store.

    The decision queue is what keeps decided things decided: approved decisions are in force,
    rejected ones are settled, proposed ones await the human — the agent must not re-propose any
    of them as if they were new ideas.

    `store` is any Store implementation (see store/base.py); None opens the configured backend.
    """
    try:
        from .store import open_store

        own = store is None
        if own:
            store = open_store()
        try:
            cases = store.list_cases(limit=limit)
            decisions = store.list_decisions(limit=15)
        finally:
            if own:
                store.close()
    except Exception:  # noqa: BLE001 - memory is an enhancement, never a hard dependency
        return ""

    if not cases:
        return ""
    # Open/monitoring first, then resolved/closed; stable, so each group stays most-recent-first.
    ordered = sorted(cases, key=lambda c: c.status in ("resolved", "closed"))
    lines = "\n".join(_case_line(c) for c in ordered)
    block = (
        '## Known cases (your memory — consult before flagging anything as "new")\n'
        "Match each observation against these. If it matches, reference it by ref and its status "
        "instead of re-raising it as new; escalate ONLY on genuinely new evidence.\n\n" + lines
    )
    if decisions:
        case_ref_by_id = {c.id: (c.ref or f"#{c.id}") for c in cases}
        dlines = "\n".join(_decision_line(d, case_ref_by_id) for d in decisions)
        block += (
            "\n\n## Decision queue (statuses are authoritative — do not re-propose decided items)\n"
            "approved = in force, act consistently with it · rejected = settled, do not re-propose "
            "without NEW evidence · proposed = awaiting human review, reference it instead of "
            "duplicating it.\n\n" + dlines
        )
    return block


def site_intel_block(store=None) -> str:
    """SITE INTELLIGENCE digest for task injection (WP-06 slice 4), or '' without a snapshot.

    Same resilience contract as known_cases_block: any failure returns '' — a missing or broken
    snapshot must never break a scheduled report. The digest stays compact by design; the model
    queries site_map_query for detail instead of receiving the whole snapshot."""
    try:
        import json

        from .core.site_intel import format_digest
        from .store import open_store

        own = store is None
        if own:
            store = open_store()
        try:
            row = store.latest_snapshot()
        finally:
            if own:
                store.close()
        if row is None:
            return ""
        snapshot = json.loads(row.payload)
        drift = json.loads(row.drift) if row.drift else None
        return "## " + format_digest(row.taken_at, snapshot, drift)
    except Exception:
        return ""
