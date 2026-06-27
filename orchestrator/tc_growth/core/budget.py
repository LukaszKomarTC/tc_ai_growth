"""Bounded ad-budget rule engine (provider-neutral, deterministic).

Produces budget-change RECOMMENDATIONS from campaign performance — it never executes a change.
The actual budget write (`ad_budget_change`) is a Phase 3 / always-ask tool that stays
unimplemented until Google/Meta write access is granted; even then it runs only behind the
triple gate (phase + confirmation + the bounds enforced here).

The headline rule (from the plan):
    May recommend reducing budget by at most `max_decrease_pct` on a campaign with
    spend >= `min_spend` over the window, zero tracked bookings, and CTR below `target_ctr`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BudgetRule:
    min_spend: float = 50.0       # only consider campaigns that have spent at least this
    target_ctr: float = 0.01      # CTR below this is "under-performing"
    max_decrease_pct: float = 0.20  # hard cap on any single recommended cut (20%)


@dataclass
class BudgetRecommendation:
    campaign: str
    spend: float
    conversions: float
    ctr: float
    action: str            # "decrease" | "hold"
    change_pct: float      # negative for a cut, 0.0 for hold
    reason: str
    requires_approval: bool = True


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_budgets(rows: list[dict], rule: BudgetRule | None = None) -> list[BudgetRecommendation]:
    """Map campaign performance rows to bounded budget recommendations.

    Accepts rows from either ads tool (cost/spend, conversions, ctr; campaign/campaign_name).
    Pure function — no I/O, no side effects.
    """
    rule = rule or BudgetRule()
    out: list[BudgetRecommendation] = []
    for r in rows:
        campaign = r.get("campaign") or r.get("campaign_name") or "(unknown)"
        spend = _num(r.get("cost", r.get("spend")))
        conversions = _num(r.get("conversions"))
        ctr = _num(r.get("ctr"))

        if spend >= rule.min_spend and conversions == 0 and ctr < rule.target_ctr:
            # Recommend a cut, capped at the hard maximum. Never auto-applied.
            out.append(BudgetRecommendation(
                campaign=campaign, spend=round(spend, 2), conversions=conversions, ctr=ctr,
                action="decrease",
                change_pct=-abs(rule.max_decrease_pct),
                reason=(f"spend €{spend:.2f} >= €{rule.min_spend:.0f}, 0 conversions, "
                        f"CTR {ctr:.3f} < target {rule.target_ctr:.3f}"),
                requires_approval=True,
            ))
        else:
            out.append(BudgetRecommendation(
                campaign=campaign, spend=round(spend, 2), conversions=conversions, ctr=ctr,
                action="hold", change_pct=0.0, reason="within acceptable performance",
                requires_approval=True,
            ))

    # Surface the actionable cuts first.
    out.sort(key=lambda rec: rec.change_pct)
    return out


def to_dicts(recs: list[BudgetRecommendation]) -> list[dict]:
    return [rec.__dict__ for rec in recs]
