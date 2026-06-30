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
    try:
        creds = service_account.Credentials.from_service_account_file(
            "secrets/google-service-account.json",
            scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
        )
    except FileNotFoundError as exc:
        raise ToolError("Google service account file not found (secrets/google-service-account.json).") from exc
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def _query(args: dict[str, Any]) -> Any:
    s = get_settings()
    if not s.gsc_site_url:
        raise ToolError("Search Console site URL is not configured (TC_GSC_SITE_URL).")

    dimensions = args.get("dimensions", ["query"])
    row_limit = int(args.get("row_limit", 25))
    request_body = {
        "startDate": _resolve_date(args["start_date"]),
        "endDate": _resolve_date(args["end_date"]),
        "dimensions": dimensions,
        "rowLimit": row_limit,
    }
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
                "position. Group by 'query', 'page', 'country', or 'device'. Use this to find "
                "high-impression/low-CTR pages and position 5-20 ranking opportunities.",
    input_schema={
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "YYYY-MM-DD, or relative: '28daysAgo' / 'today' / 'yesterday'"},
            "end_date": {"type": "string", "description": "YYYY-MM-DD, or relative: '28daysAgo' / 'today' / 'yesterday'"},
            "dimensions": {
                "type": "array",
                "items": {"type": "string", "enum": ["query", "page", "country", "device", "date"]},
                "default": ["query"],
            },
            "row_limit": {"type": "integer", "default": 25, "maximum": 100},
        },
        "required": ["start_date", "end_date"],
    },
    handler=_query,
))
