"""Commercial-lifecycle classification (WP-06 slice 3). Pure functions, no I/O.

Why this exists: run #1 recommended CTR-optimising an expired event; run #2 recommended
routing CTAs the event plugin already renders. Both were lifecycle blindness. This module
turns those misunderstandings into a rule the agent applies automatically.

Evidence ladder (owner + reviewer, 2026-07-20) — higher tiers WIN, lower tiers only fill in:
1. APPROVED RULE   — owner-reviewed rules below (repo changes = human approval via PR).
2. STRUCTURED      — explicit date/status fields passed by the caller (e.g. Sugar Calendar
                     event dates once the connector/DB reader exposes them).
3. CONTENT-DATE    — dates parsed from slug/URL/title.
4. INFERENCE       — type defaults, explicitly marked uncertain.

Conflict discipline: mixed evidence NEVER resolves silently. A page with one past date and
one future date is "unknown" with both cited — never "past" because a single field is old.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

# Owner-approved lifecycle rules. Editing this list is a human act (PR review) — it is the
# machine-readable slice of SITE_PROFILE's lifecycle knowledge, not something the agent writes.
# Order matters: first match wins. "state" decides immediately (tier 1); "policy" delegates
# to date evidence with the given fallback.
APPROVED_RULES: list[dict[str, str]] = [
    {"slug": "tour_de_girona-listado", "state": "evergreen",
     "why": "TdG hub — the permanent home of all editions (site policy; editions route here)"},
    {"type": "events", "policy": "date-governed", "fallback": "unknown",
     "why": "event pages live and die by their date; without one we do not guess"},
    {"type": "product", "policy": "date-governed", "fallback": "unknown",
     "why": "availability is not visible to structure reads — only dated editions classify"},
    {"type": "page", "policy": "date-governed", "fallback": "evergreen",
     "why": "pages are evergreen unless they carry explicit date evidence"},
    {"type": "post", "policy": "date-governed", "fallback": "evergreen",
     "why": "posts are evergreen content unless explicitly dated"},
]

# Scanned independently (NOT one alternation): in a slug like "...-2026-24-06-2026" a combined
# pattern consumes the invalid "2026-24-06" first and swallows the real "24-06-2026" inside it.
_DMY = re.compile(r"\b(\d{1,2})-(\d{1,2})-(20\d{2})\b")
_YMD = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
_BARE_YEAR = re.compile(r"\b(20\d{2})\b")


def _parse_dates(text: str) -> tuple[list[dt.date], list[int]]:
    """(full dates, bare years) found in text. dd-mm-yyyy and yyyy-mm-dd both supported;
    impossible dates are ignored rather than guessed."""
    dates: set[dt.date] = set()
    for pattern, order in ((_DMY, (2, 1, 0)), (_YMD, (0, 1, 2))):
        for m in pattern.finditer(text):
            g = m.groups()
            try:
                dates.add(dt.date(int(g[order[0]]), int(g[order[1]]), int(g[order[2]])))
            except ValueError:
                continue
    covered = {d.year for d in dates}
    years = [int(y) for y in _BARE_YEAR.findall(text) if int(y) not in covered]
    return sorted(dates), years


def _classify_by_dates(dates: list[dt.date], years: list[int], today: dt.date) -> dict[str, Any] | None:
    """Date evidence -> state, or None when there is no evidence. Mixed signals -> unknown."""
    past = [d for d in dates if d < today]
    future = [d for d in dates if d >= today]
    if past and future:
        return {"state": "unknown", "confidence": "low",
                "basis": f"conflicting date evidence: past {past} vs future {future} — needs interpretation"}
    if future:
        return {"state": "upcoming", "confidence": "high", "basis": f"future date(s) {future}"}
    if past:
        return {"state": "past", "confidence": "medium",
                "basis": f"past date(s) {past}; no future evidence — verify no future edition shares this page"}
    if years:
        past_years = [y for y in years if y < today.year]
        future_years = [y for y in years if y > today.year]
        if past_years and not future_years:
            return {"state": "past", "confidence": "low",
                    "basis": f"year(s) {past_years} only — no full date; treat as uncertain"}
        if future_years and not past_years:
            return {"state": "upcoming", "confidence": "low",
                    "basis": f"year(s) {future_years} only — no full date; treat as uncertain"}
        return {"state": "unknown", "confidence": "low",
                "basis": f"current-or-mixed year(s) {years} — cannot place within the year"}
    return None


def classify_lifecycle(
    item: dict[str, Any],
    *,
    today: dt.date,
    structured: dict[str, Any] | None = None,
    rules: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Classify one snapshot item. Returns {state, tier, confidence, basis} — basis is always
    stated so a report can cite WHY, and uncertainty is explicit, never smoothed over."""
    rules = APPROVED_RULES if rules is None else rules

    rule = next(
        (r for r in rules
         if r.get("slug", item.get("slug")) == item.get("slug")
         and r.get("type", item.get("type")) == item.get("type")),
        None,
    )
    if rule and "state" in rule:
        return {"state": rule["state"], "tier": "approved-rule", "confidence": "high",
                "basis": rule.get("why", "approved rule")}

    # Tier 2 — structured fields from the caller (event tables, availability, explicit status).
    if structured:
        if "status" in structured:
            return {"state": str(structured["status"]), "tier": "structured", "confidence": "high",
                    "basis": f"explicit status field: {structured['status']}"}
        s_dates = [v for k, v in structured.items() if "date" in k.lower() and isinstance(v, dt.date)]
        verdict = _classify_by_dates(s_dates, [], today)
        if verdict:
            return {**verdict, "tier": "structured", "confidence": "high",
                    "basis": f"structured field(s): {verdict['basis']}"}

    # Tier 3 — dates in slug / URL / raw title.
    evidence_text = " ".join(str(item.get(k, "")) for k in ("slug", "url", "title"))
    verdict = _classify_by_dates(*_parse_dates(evidence_text), today)
    if verdict:
        return {**verdict, "tier": "content-date"}

    # Tier 4 — the rule's fallback, explicitly uncertain when it is a guess.
    fallback = (rule or {}).get("fallback", "unknown")
    return {"state": fallback, "tier": "inference",
            "confidence": "medium" if fallback == "evergreen" else "low",
            "basis": (rule or {}).get("why", "no rule matched; no date evidence")}
