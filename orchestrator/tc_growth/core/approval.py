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
    "budget_recommendations": Phase.READ_ONLY,  # dry-run analysis, changes nothing
    # case memory — writes to the agent's OWN store, never to an external system, so the phase
    # gate (which governs external side effects) admits them in READ_ONLY. Lifecycle transitions
    # are the exception: case_set_status is in ALWAYS_ASK below.
    "case_search": Phase.READ_ONLY,
    "case_read": Phase.READ_ONLY,
    "case_open": Phase.READ_ONLY,
    "case_note": Phase.READ_ONLY,
    "case_set_confidence": Phase.READ_ONLY,
    "case_set_status": Phase.READ_ONLY,
    "decision_log": Phase.READ_ONLY,  # records PROPOSED decisions only; humans activate them
    # draft writes — Phase 1-2
    "wp_create_seo_draft": Phase.DRAFTS,
    "wp_create_product_revision": Phase.DRAFTS,
    "draft_google_ad": Phase.DRAFTS,
    "draft_meta_ad": Phase.DRAFTS,
    "draft_gbp_post": Phase.DRAFTS,
    # Phase 3 — controlled execution (live changes). Also require human confirmation (ALWAYS_ASK).
    "publish_seo_draft": Phase.CONTROLLED_EXECUTION,
    # Declared but intentionally NOT registered as a tool yet — awaits ad-platform write access.
    # Listed here so the gate is explicit; until a handler exists it cannot be dispatched.
    "ad_budget_change": Phase.CONTROLLED_EXECUTION,
}

# Tools that ALWAYS require an explicit human confirmation, regardless of phase. In an autonomous
# / scheduled run (no confirmation hook) these are refused by the runtimes — they can only execute
# when a human is in the loop to approve the specific call.
ALWAYS_ASK = {
    "publish_seo_draft",
    # case lifecycle transitions are consequential judgments — human approves each one; in a
    # scheduled run the agent proposes the change in its report instead.
    "case_set_status",
    # future Phase 3 execution tools:
    "ad_budget_change",
    "publish_post",
    "create_campaign",
}


def needs_confirmation(tool_name: str) -> bool:
    """True if the tool may only run with an explicit per-call human confirmation."""
    return tool_name in ALWAYS_ASK

# Capabilities that must NEVER exist as automated tools in this system.
FORBIDDEN_CAPABILITIES = {
    "change_price",
    "change_availability",
    "modify_booking_logic",
    "modify_checkout_tracking",
    "delete_campaign",
}


def is_tool_allowed(tool_name: str, phase: Phase) -> bool:
    """True if `tool_name` may be dispatched in the given phase.

    Two layers, both enforced here (the single choke point both runtimes call):
    1. The phase gate — the tool's minimum phase vs. the run's requested phase.
    2. The SITE-PROFILE write cap — a profile with allow_writes=false (production default)
       blocks every above-READ_ONLY tool regardless of the requested phase, so no command,
       config mistake, or prompt can produce a write against a read-only site.
    """
    required = TOOL_MIN_PHASE.get(tool_name)
    if required is None:
        # Unknown tool -> deny by default.
        return False
    if required > Phase.READ_ONLY:
        from ..config import writes_allowed  # local import: core stays cycle-free

        if not writes_allowed():
            return False
    return phase >= required


def assert_not_forbidden(capability: str) -> None:
    if capability in FORBIDDEN_CAPABILITIES:
        raise PermissionError(f"Capability '{capability}' is permanently forbidden in this system.")
