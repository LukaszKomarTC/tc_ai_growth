"""Approval & guardrail rules (provider-neutral, enforced in code — not just in prompts).

The phase gate is the safety backbone. Even if a prompt or model misbehaves, the orchestrator
will refuse to dispatch a tool action that the current phase does not permit.
"""

from __future__ import annotations

from enum import IntEnum


class Phase(IntEnum):
    READ_ONLY = 0          # Phase 1: read + report only
    DRAFTS = 1             # Phase 1-2: read + WordPress/ad-copy drafts
    CONTROLLED_EXECUTION = 2  # Phase 3: publish approved changes, draft campaigns, bounded budget moves


# Map each tool to the minimum phase that may CALL it. Read tools are always allowed.
# Anything that writes is gated. Nothing here can change price/availability/booking/checkout —
# those capabilities simply do not exist as tools.
TOOL_MIN_PHASE: dict[str, Phase] = {
    # read-only (lever data) — always allowed
    "gsc_search_analytics": Phase.READ_ONLY,
    "ga4_report": Phase.READ_ONLY,
    "google_ads_query": Phase.READ_ONLY,
    "meta_ads_insights": Phase.READ_ONLY,
    "gbp_list_reviews": Phase.READ_ONLY,
    "pagespeed_check": Phase.READ_ONLY,
    "wp_list": Phase.READ_ONLY,
    "wp_seo_audit": Phase.READ_ONLY,
    "woo_revenue_attribution": Phase.READ_ONLY,
    # draft writes — Phase 1-2
    "wp_create_seo_draft": Phase.DRAFTS,
    "wp_create_product_revision": Phase.DRAFTS,
    "draft_google_ad": Phase.DRAFTS,
    "draft_meta_ad": Phase.DRAFTS,
    "draft_gbp_post": Phase.DRAFTS,
    # (Phase 3 execution tools will be registered later and gated to CONTROLLED_EXECUTION)
}

# Actions that ALWAYS require an explicit human confirmation, regardless of phase.
ALWAYS_ASK = {
    "ad_budget_change",
    "publish_post",
    "create_campaign",
}

# Capabilities that must NEVER exist as automated tools in this system.
FORBIDDEN_CAPABILITIES = {
    "change_price",
    "change_availability",
    "modify_booking_logic",
    "modify_checkout_tracking",
    "delete_campaign",
}


def is_tool_allowed(tool_name: str, phase: Phase) -> bool:
    """True if `tool_name` may be dispatched in the given phase."""
    required = TOOL_MIN_PHASE.get(tool_name)
    if required is None:
        # Unknown tool -> deny by default.
        return False
    return phase >= required


def assert_not_forbidden(capability: str) -> None:
    if capability in FORBIDDEN_CAPABILITIES:
        raise PermissionError(f"Capability '{capability}' is permanently forbidden in this system.")
