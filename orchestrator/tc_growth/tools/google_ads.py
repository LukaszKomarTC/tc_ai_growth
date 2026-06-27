"""Google Ads tool — read-only campaign performance via GAQL.

NOTE: Google Ads API access requires a developer token and an access-level review (Basic ~5
business days, Standard ~10). Start that process in Phase 0 — it is the critical-path bottleneck.
Until the token is granted, this tool returns a clear, actionable error rather than failing oddly.
"""

from __future__ import annotations

from typing import Any

from ..config import get_settings
from .base import Tool, ToolError, registry

# Default GAQL: campaign-level spend/clicks/impressions/conversions for the last 30 days.
_DEFAULT_GAQL = """
SELECT campaign.name, metrics.cost_micros, metrics.clicks, metrics.impressions,
       metrics.conversions, metrics.conversions_value
FROM campaign
WHERE segments.date DURING LAST_30_DAYS
ORDER BY metrics.cost_micros DESC
""".strip()


def _client():
    try:
        from google.ads.googleads.client import GoogleAdsClient  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ToolError("google-ads not installed. Install the 'google' extra and configure a "
                        "developer token (see docs/SETUP.md).") from exc
    # GoogleAdsClient.load_from_storage reads google-ads.yaml (developer token, OAuth creds).
    try:
        return GoogleAdsClient.load_from_storage("secrets/google-ads.yaml")
    except FileNotFoundError as exc:
        raise ToolError("secrets/google-ads.yaml not found. Provision the Google Ads developer "
                        "token and OAuth credentials first (Phase 0 critical path).") from exc


def _query(args: dict[str, Any]) -> Any:
    s = get_settings()
    if not s.google_ads_customer_id:
        raise ToolError("Google Ads customer id is not configured (TC_GOOGLE_ADS_CUSTOMER_ID).")
    client = _client()
    gaql = args.get("gaql", _DEFAULT_GAQL)
    service = client.get_service("GoogleAdsService")
    rows = []
    for batch in service.search_stream(customer_id=s.google_ads_customer_id, query=gaql):
        for row in batch.results:
            rows.append({
                "campaign": row.campaign.name,
                "cost": row.metrics.cost_micros / 1_000_000,
                "clicks": row.metrics.clicks,
                "impressions": row.metrics.impressions,
                "conversions": row.metrics.conversions,
                "conversions_value": row.metrics.conversions_value,
            })
    return rows


registry.register(Tool(
    name="google_ads_query",
    description="Run a read-only GAQL query against Google Ads (default: campaign spend, clicks, "
                "impressions, conversions, conversion value, last 30 days). Use to find expensive "
                "keywords with no conversions, suggest negatives, and compare campaign ROI.",
    input_schema={
        "type": "object",
        "properties": {
            "gaql": {"type": "string", "description": "Optional GAQL query; omit for the default."},
        },
    },
    handler=_query,
))
