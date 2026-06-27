"""Meta (Facebook/Instagram) Ads Insights tool — read-only in early phases.

Implemented against the Graph API via httpx (no SDK dependency). Access token resolved
host-side. Phase 1-2: analysis only — never changes budgets or creatives.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..config import get_settings
from .base import Tool, ToolError, registry

_GRAPH = "https://graph.facebook.com/v20.0"


def _insights(args: dict[str, Any]) -> Any:
    s = get_settings()
    token = os.environ.get("TC_META_ACCESS_TOKEN", "")
    if not s.meta_ad_account_id or not token:
        raise ToolError("Meta ad account id / access token not configured.")

    params = {
        "access_token": token,
        "level": args.get("level", "campaign"),
        "fields": ",".join(args.get("fields", [
            "campaign_name", "spend", "impressions", "clicks", "ctr", "cpc", "actions",
        ])),
        "date_preset": args.get("date_preset", "last_30d"),
        "limit": int(args.get("row_limit", 50)),
    }
    url = f"{_GRAPH}/{s.meta_ad_account_id}/insights"
    try:
        resp = httpx.get(url, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json().get("data", [])
    except httpx.HTTPError as exc:
        raise ToolError(f"Meta insights request failed: {exc}")


registry.register(Tool(
    name="meta_ads_insights",
    description="Read Meta (Facebook/Instagram) ad performance: spend, impressions, clicks, CTR, "
                "CPC, and conversion actions, by campaign/adset/ad. Read-only. Use to find wasted "
                "spend, best creatives, and cost-per-booking.",
    input_schema={
        "type": "object",
        "properties": {
            "level": {"type": "string", "enum": ["account", "campaign", "adset", "ad"], "default": "campaign"},
            "date_preset": {"type": "string", "default": "last_30d"},
            "fields": {"type": "array", "items": {"type": "string"}},
            "row_limit": {"type": "integer", "default": 50},
        },
    },
    handler=_insights,
))
