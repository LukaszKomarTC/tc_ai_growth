"""Google Search Console tools (SEO — priority lever 1).

Surfaces the queries/pages the SEO agent reasons over: impressions, clicks, CTR, position.
Credentials are loaded host-side (service account or OAuth) so tokens never enter the sandbox.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from ..config import get_settings
from .base import Tool, ToolError, registry

_REL_DAYS = re.compile(r"^(\d+)daysAgo$")
_ABS_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _resolve_date(value: str, *, today: dt.date | None = None) -> str:
    """Normalise a date to YYYY-MM-DD for the Search Console API.

    Search Console only accepts absolute dates, but GA4 accepts relative ones like '28daysAgo'
    and 'today'. To keep both tools consistent (and stop the report agent tripping on the
    difference), accept the GA4-style shorthand here and convert it.
    """
    v = (value or "").strip()
    if _ABS_DATE.match(v):
        return v
    today = today or dt.date.today()
    if v == "today":
        return today.isoformat()
    if v == "yesterday":
        return (today - dt.timedelta(days=1)).isoformat()
    m = _REL_DAYS.match(v)
    if m:
        return (today - dt.timedelta(days=int(m.group(1)))).isoformat()
    raise ToolError(
        f"Invalid date '{value}'. Use YYYY-MM-DD, 'today', 'yesterday', or 'NdaysAgo'."
    )


def _service():
    """Build a Search Console API client. Imported lazily so the package works without the
    Google extras installed (e.g. on a machine that only runs the WordPress tools)."""
    try:
        from google.oauth2 import service_account  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ToolError("Google API client not installed. Install the 'google' extra.") from exc

    # Credentials resolution is intentionally host-side. See docs/SETUP.md for the options
    # (Application Default Credentials, a mounted service-account file, or stored OAuth tokens).
    # The path is anchored to orchestrator/ (not the CWD) so commands work from any directory.
    from ..config import secrets_path

    sa_file = secrets_path("google-service-account.json")
    try:
        creds = service_account.Credentials.from_service_account_file(
            str(sa_file),
            scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
        )
    except FileNotFoundError as exc:
        raise ToolError(f"Google service account file not found ({sa_file}).") from exc
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def _build_body(args: dict[str, Any]) -> dict[str, Any]:
    """Build the searchAnalytics request body (pure function — unit-tested without the API).

    Supports a forensic `page_filter` (URL 'contains' substring) via dimensionFilterGroups, plus
    the 'date' dimension and a long lookback for timeline analysis.
    """
    body: dict[str, Any] = {
        "startDate": _resolve_date(args["start_date"]),
        "endDate": _resolve_date(args["end_date"]),
        "dimensions": args.get("dimensions", ["query"]),
        "rowLimit": int(args.get("row_limit", 25)),
    }
    page_filter = args.get("page_filter")
    if page_filter:
        body["dimensionFilterGroups"] = [{
            "filters": [{"dimension": "page", "operator": "contains", "expression": str(page_filter)}]
        }]
    return body


def _query(args: dict[str, Any]) -> Any:
    s = get_settings()
    if not s.gsc_site_url:
        raise ToolError("Search Console site URL is not configured (TC_GSC_SITE_URL).")

    request_body = _build_body(args)
    service = _service()
    resp = service.searchanalytics().query(siteUrl=s.gsc_site_url, body=request_body).execute()
    rows = resp.get("rows", [])
    return [
        {
            "keys": r.get("keys", []),
            "clicks": r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "ctr": round(r.get("ctr", 0.0), 4),
            "position": round(r.get("position", 0.0), 2),
        }
        for r in rows
    ]


registry.register(Tool(
    name="gsc_search_analytics",
    description="Query Google Search Console performance: clicks, impressions, CTR, average "
                "position. Group by 'query', 'page', 'country', 'device', or 'date'. Find "
                "high-impression/low-CTR pages and position 5-20 opportunities. For forensic "
                "timelines, set page_filter (URL contains) + dimensions=['date'] over a long "
                "lookback (e.g. start '480daysAgo') to see when a URL pattern first/last appeared.",
    input_schema={
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "YYYY-MM-DD, or relative: '28daysAgo' / 'today' / 'yesterday' (GSC max lookback ~16 months)"},
            "end_date": {"type": "string", "description": "YYYY-MM-DD, or relative: '28daysAgo' / 'today' / 'yesterday'"},
            "dimensions": {
                "type": "array",
                "items": {"type": "string", "enum": ["query", "page", "country", "device", "date"]},
                "default": ["query"],
            },
            "page_filter": {"type": "string", "description": "Only rows whose page URL CONTAINS this substring (forensics, e.g. 'Marlboro')"},
            "row_limit": {"type": "integer", "default": 25, "maximum": 1000},
        },
        "required": ["start_date", "end_date"],
    },
    handler=_query,
))
