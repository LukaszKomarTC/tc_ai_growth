"""Opportunity scoring — the Tossa Cycling business chain in code.

    keyword -> landing page -> availability -> price -> booking -> revenue -> action

These helpers are deterministic and provider-neutral. The agent can call them (via a tool) or
the orchestrator can run them directly to pre-rank what the agent should focus on, keeping the
LLM reasoning grounded in real numbers rather than vibes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SeoOpportunity:
    query: str
    page: str
    impressions: int
    ctr: float
    position: float
    score: float
    reason: str


def score_seo_rows(rows: list[dict]) -> list[SeoOpportunity]:
    """Rank Search Console rows by opportunity.

    Priority targets:
      * High impressions + low CTR (a title/meta rewrite can capture existing demand).
      * Position 5-20 (a realistic push to page-1 / top-3).
    """
    out: list[SeoOpportunity] = []
    for r in rows:
        impressions = int(r.get("impressions", 0))
        ctr = float(r.get("ctr", 0.0))
        position = float(r.get("position", 0.0))
        keys = r.get("keys", [])
        query = keys[0] if keys else ""
        page = keys[1] if len(keys) > 1 else ""

        score = 0.0
        reasons = []
        # Demand we under-capture: lots of impressions but weak CTR.
        if impressions >= 100 and ctr < 0.02:
            score += impressions * (0.02 - ctr)
            reasons.append("high impressions, low CTR")
        # Striking distance: ranks 5-20.
        if 5 <= position <= 20:
            score += impressions * 0.5
            reasons.append(f"striking distance (pos {position:.1f})")

        if score > 0:
            out.append(SeoOpportunity(
                query=query, page=page, impressions=impressions, ctr=ctr,
                position=position, score=round(score, 2), reason="; ".join(reasons),
            ))

    out.sort(key=lambda o: o.score, reverse=True)
    return out


def wasted_ad_spend(rows: list[dict], min_spend: float = 50.0) -> list[dict]:
    """Flag campaigns with meaningful spend and zero tracked conversions."""
    flagged = []
    for r in rows:
        spend = float(r.get("cost", r.get("spend", 0)) or 0)
        conversions = float(r.get("conversions", 0) or 0)
        if spend >= min_spend and conversions == 0:
            flagged.append({
                "campaign": r.get("campaign") or r.get("campaign_name"),
                "spend": round(spend, 2),
                "conversions": 0,
                "recommendation": "Investigate landing page / targeting; candidate for budget cut "
                                  "(human-approved only).",
            })
    return flagged
