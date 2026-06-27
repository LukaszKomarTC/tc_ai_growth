"""PageSpeed Insights tool — performance/SEO health of money pages.

Fully implemented: a keyed HTTP GET against the public PageSpeed Insights API.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import get_settings
from .base import Tool, ToolError, registry

_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def _run(args: dict[str, Any]) -> Any:
    s = get_settings()
    params = {
        "url": args["url"],
        "strategy": args.get("strategy", "mobile"),
        "category": args.get("categories", ["performance", "seo", "accessibility"]),
    }
    if s.pagespeed_api_key:
        params["key"] = s.pagespeed_api_key
    try:
        resp = httpx.get(_ENDPOINT, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise ToolError(f"PageSpeed request failed: {exc}")

    lighthouse = data.get("lighthouseResult", {})
    categories = lighthouse.get("categories", {})
    return {
        "url": args["url"],
        "strategy": params["strategy"],
        "scores": {k: round((v.get("score") or 0) * 100) for k, v in categories.items()},
        "metrics": {
            m: lighthouse.get("audits", {}).get(m, {}).get("displayValue")
            for m in ["largest-contentful-paint", "cumulative-layout-shift", "total-blocking-time", "speed-index"]
        },
    }


registry.register(Tool(
    name="pagespeed_check",
    description="Run PageSpeed Insights on a URL and return performance/SEO/accessibility scores "
                "and Core Web Vitals. Use on money pages (home, road bike rental, eMTB, tours, "
                "Tour de Girona, checkout) to flag speed regressions.",
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "strategy": {"type": "string", "enum": ["mobile", "desktop"], "default": "mobile"},
        },
        "required": ["url"],
    },
    handler=_run,
))
