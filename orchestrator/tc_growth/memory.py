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


def known_cases_block(store=None, *, limit: int = 25) -> str:
    """A markdown 'Known cases' block for task injection, or '' when there are none / no store.

    `store` is any Store implementation (see store/base.py); None opens the configured backend.
    """
    try:
        from .store import open_store

        own = store is None
        if own:
            store = open_store()
        try:
            cases = store.list_cases(limit=limit)
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
    return (
        '## Known cases (your memory — consult before flagging anything as "new")\n'
        "Match each observation against these. If it matches, reference it by ref and its status "
        "instead of re-raising it as new; escalate ONLY on genuinely new evidence.\n\n" + lines
    )
