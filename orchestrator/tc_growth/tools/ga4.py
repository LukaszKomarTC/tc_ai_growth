"""GA4 Data API tool — connects traffic to bookings & revenue.

Implemented against google-analytics-data. Credentials resolved host-side (service account).
"""

from __future__ import annotations

from typing import Any

from ..config import get_settings
from .base import Tool, ToolError, registry


def _client():
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient  # type: ignore
        from google.oauth2 import service_account  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ToolError("google-analytics-data not installed. Install the 'google' extra.") from exc
    try:
        creds = service_account.Credentials.from_service_account_file(
            "secrets/google-service-account.json",
            scopes=["https://www.googleapis.com/auth/analytics.readonly"],
        )
    except FileNotFoundError as exc:
        raise ToolError("Google service account file not found (secrets/google-service-account.json).") from exc
    return BetaAnalyticsDataClient(credentials=creds)


def _report(args: dict[str, Any]) -> Any:
    from google.analytics.data_v1beta.types import (  # type: ignore
        DateRange, Dimension, Metric, RunReportRequest,
    )

    s = get_settings()
    if not s.ga4_property_id:
        raise ToolError("GA4 property id is not configured (TC_GA4_PROPERTY_ID).")

    request = RunReportRequest(
        property=f"properties/{s.ga4_property_id}",
        date_ranges=[DateRange(start_date=args["start_date"], end_date=args["end_date"])],
        dimensions=[Dimension(name=d) for d in args.get("dimensions", ["sessionDefaultChannelGroup"])],
        metrics=[Metric(name=m) for m in args.get("metrics", ["sessions", "conversions", "totalRevenue"])],
        limit=int(args.get("row_limit", 25)),
    )
    resp = _client().run_report(request)
    dim_names = [h.name for h in resp.dimension_headers]
    met_names = [h.name for h in resp.metric_headers]
    rows = []
    for r in resp.rows:
        row = {dim_names[i]: v.value for i, v in enumerate(r.dimension_values)}
        row.update({met_names[i]: v.value for i, v in enumerate(r.metric_values)})
        rows.append(row)
    return rows


registry.register(Tool(
    name="ga4_report",
    description="Run a GA4 report. Connects channel/landing-page traffic to conversions and "
                "revenue. Default dimension is channel group; default metrics are sessions, "
                "conversions, totalRevenue. Use to find pages that get traffic but don't convert.",
    input_schema={
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "YYYY-MM-DD or e.g. '28daysAgo'"},
            "end_date": {"type": "string", "description": "YYYY-MM-DD or 'today'"},
            "dimensions": {"type": "array", "items": {"type": "string"}},
            "metrics": {"type": "array", "items": {"type": "string"}},
            "row_limit": {"type": "integer", "default": 25},
        },
        "required": ["start_date", "end_date"],
    },
    handler=_report,
))
