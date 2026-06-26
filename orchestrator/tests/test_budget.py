"""Bounded ad-budget rule engine + dry-run tool."""

from __future__ import annotations

from tc_growth.core.approval import Phase, is_tool_allowed, needs_confirmation
from tc_growth.core.budget import BudgetRule, evaluate_budgets
from tc_growth.tools.load import load_all


def test_flags_high_spend_zero_conversion_low_ctr_with_capped_cut():
    rows = [{"campaign": "Wasteful", "cost": 120.0, "conversions": 0, "ctr": 0.004}]
    recs = evaluate_budgets(rows)
    assert recs[0].action == "decrease"
    assert recs[0].change_pct == -0.20            # capped at max_decrease_pct
    assert recs[0].requires_approval is True


def test_holds_converting_campaign():
    rows = [{"campaign": "Good", "cost": 200.0, "conversions": 8, "ctr": 0.05}]
    recs = evaluate_budgets(rows)
    assert recs[0].action == "hold"
    assert recs[0].change_pct == 0.0


def test_low_spend_is_not_cut_even_with_zero_conversions():
    rows = [{"campaign": "Tiny", "cost": 10.0, "conversions": 0, "ctr": 0.001}]
    recs = evaluate_budgets(rows)
    assert recs[0].action == "hold"


def test_cut_never_exceeds_configured_cap():
    rows = [{"campaign": "X", "cost": 999.0, "conversions": 0, "ctr": 0.0}]
    recs = evaluate_budgets(rows, BudgetRule(max_decrease_pct=0.10))
    assert recs[0].change_pct == -0.10


def test_budget_tool_is_read_only_and_changes_nothing():
    reg = load_all()
    names = {t.name for t in reg.all()}
    assert "budget_recommendations" in names
    assert is_tool_allowed("budget_recommendations", Phase.READ_ONLY)

    out = reg.dispatch("budget_recommendations", {
        "campaigns": [{"campaign": "Wasteful", "cost": 120.0, "conversions": 0, "ctr": 0.004}],
    })
    assert out["ok"] is True
    assert out["result"]["summary"]["recommended_cuts"] == 1
    assert "no budgets are changed" in out["result"]["summary"]["note"].lower()


def test_ad_budget_change_remains_unregistered_and_gated():
    # The executing tool is declared in the gate but has no handler — so it can't be dispatched.
    names = {t.name for t in load_all().all()}
    assert "ad_budget_change" not in names
    assert needs_confirmation("ad_budget_change")
    assert not is_tool_allowed("ad_budget_change", Phase.DRAFTS)
