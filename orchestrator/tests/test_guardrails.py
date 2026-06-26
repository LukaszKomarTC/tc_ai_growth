"""Guardrail + portability invariants. These are the safety backbone — keep them green."""

from __future__ import annotations

import pathlib

from tc_growth.core.approval import (
    FORBIDDEN_CAPABILITIES,
    Phase,
    assert_not_forbidden,
    is_tool_allowed,
)
from tc_growth.core.opportunities import score_seo_rows, wasted_ad_spend
from tc_growth.tools.load import load_all


def test_draft_tools_blocked_in_read_only_phase():
    assert is_tool_allowed("gsc_search_analytics", Phase.READ_ONLY)
    assert not is_tool_allowed("wp_create_seo_draft", Phase.READ_ONLY)
    assert is_tool_allowed("wp_create_seo_draft", Phase.DRAFTS)


def test_unknown_tool_denied_by_default():
    assert not is_tool_allowed("definitely_not_a_tool", Phase.CONTROLLED_EXECUTION)


def test_forbidden_capabilities_raise():
    for cap in FORBIDDEN_CAPABILITIES:
        try:
            assert_not_forbidden(cap)
        except PermissionError:
            continue
        raise AssertionError(f"{cap} should be forbidden")


def test_seo_scoring_prioritises_high_impression_low_ctr():
    rows = [
        {"keys": ["road bike rental costa brava", "/road"], "impressions": 1000, "ctr": 0.005, "position": 9.0},
        {"keys": ["random low-value", "/x"], "impressions": 10, "ctr": 0.30, "position": 1.0},
    ]
    ranked = score_seo_rows(rows)
    assert ranked[0].query == "road bike rental costa brava"


def test_wasted_spend_flags_zero_conversion_campaigns():
    flagged = wasted_ad_spend([{"campaign": "A", "cost": 120, "conversions": 0}])
    assert flagged and flagged[0]["campaign"] == "A"


def test_tools_and_core_do_not_import_an_ai_sdk():
    """Portability invariant: only runtime/ may depend on a provider SDK."""
    root = pathlib.Path(__file__).resolve().parents[1] / "tc_growth"
    banned = ("import anthropic", "from anthropic", "import openai", "from openai", "google.generativeai")
    offenders = []
    for path in list((root / "tools").rglob("*.py")) + list((root / "core").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in banned):
            offenders.append(str(path))
    assert not offenders, f"AI-SDK import leaked into tools/ or core/: {offenders}"


def test_registry_populates():
    reg = load_all()
    names = {t.name for t in reg.all()}
    assert {"gsc_search_analytics", "wp_create_seo_draft", "pagespeed_check"} <= names


def test_woo_revenue_attribution_is_read_only_tool():
    names = {t.name for t in load_all().all()}
    assert "woo_revenue_attribution" in names
    assert is_tool_allowed("woo_revenue_attribution", Phase.READ_ONLY)
