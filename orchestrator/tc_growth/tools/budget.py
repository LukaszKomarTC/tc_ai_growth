"""Ad-budget recommendation tool (read-only / dry-run).

Wraps the deterministic rule engine in core/budget. It analyses campaign rows the agent already
pulled (Google Ads / Meta) and returns bounded budget RECOMMENDATIONS. It changes nothing — the
actual budget write stays unimplemented and gated until ad-platform write access exists.
"""

from __future__ import annotations

from typing import Any

from ..core.budget import BudgetRule, evaluate_budgets, to_dicts
from .base import Tool, registry


def _recommend(args: dict[str, Any]) -> Any:
    rows = args.get("campaigns", []) or []
    rule = BudgetRule(
        min_spend=float(args.get("min_spend", 50.0)),
        target_ctr=float(args.get("target_ctr", 0.01)),
        max_decrease_pct=float(args.get("max_decrease_pct", 0.20)),
    )
    recs = evaluate_budgets(rows, rule)
    cuts = [r for r in recs if r.action == "decrease"]
    return {
        "recommendations": to_dicts(recs),
        "summary": {
            "campaigns": len(recs),
            "recommended_cuts": len(cuts),
            "max_decrease_pct": rule.max_decrease_pct,
            "note": "Recommendations only — no budgets are changed. Human approval required.",
        },
    }


registry.register(Tool(
    name="budget_recommendations",
    description="Analyse Google/Meta campaign rows and return BOUNDED budget-change recommendations "
                "(read-only, dry-run — changes nothing). Flags campaigns with meaningful spend, "
                "zero conversions, and low CTR for a capped reduction; all require human approval.",
    input_schema={
        "type": "object",
        "properties": {
            "campaigns": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Campaign rows from google_ads_query / meta_ads_insights "
                               "(fields: campaign/campaign_name, cost or spend, conversions, ctr).",
            },
            "min_spend": {"type": "number", "default": 50.0},
            "target_ctr": {"type": "number", "default": 0.01},
            "max_decrease_pct": {"type": "number", "default": 0.20},
        },
        "required": ["campaigns"],
    },
    handler=_recommend,
))
