"""WordPress connector client + tools.

Talks to the `tc-growth/v1` REST API exposed by the tc-growth-connector plugin. Every request
is authenticated with the agent user's Application Password AND signed with the shared HMAC key
(timestamp.method.route.body), matching TC_Growth_Auth in the plugin.

Draft-only: the only writes available are create-seo-draft / create-product-revision.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import get_settings
from .base import Tool, ToolError, registry

_NAMESPACE = "/wp-json/tc-growth/v1"


def _sign(method: str, route: str, body: str, signing_key: str) -> tuple[str, str]:
    """Return (timestamp, signature) matching the plugin's verification."""
    ts = str(int(time.time()))
    payload = f"{ts}.{method}.{route}.{body}"
    sig = hmac.new(signing_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return ts, sig


def _request(method: str, path: str, *, body: str = "") -> Any:
    s = get_settings()
    if not s.wp_base_url or not s.wp_signing_key:
        raise ToolError("WordPress connector is not configured (base url / signing key).")

    url = f"{s.wp_base_url.rstrip('/')}{_NAMESPACE}{path}"
    # The plugin signs over the WP REST *route*, i.e. the path after /wp-json.
    route = urlparse(url).path.replace("/wp-json", "", 1)
    ts, sig = _sign(method, route, body, s.wp_signing_key)
    headers = {
        "X-TC-Timestamp": ts,
        "X-TC-Signature": sig,
        "Content-Type": "application/json",
    }
    auth = (s.wp_user, s.wp_app_password)

    try:
        resp = httpx.request(method, url, headers=headers, auth=auth, content=body or None, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise ToolError(f"WordPress {method} {path} failed: {exc.response.status_code} {exc.response.text[:300]}")
    except httpx.HTTPError as exc:
        raise ToolError(f"WordPress request error: {exc}")


# --------------------------------------------------------------------------- handlers ------

def _seo_audit(args: dict[str, Any]) -> Any:
    post_id = int(args["post_id"])
    return _request("GET", f"/seo-audit-data?post_id={post_id}")


def _list(args: dict[str, Any]) -> Any:
    kind = args.get("kind", "pages")
    if kind not in {"pages", "products", "rentals"}:
        raise ToolError("kind must be one of: pages, products, rentals")
    page = int(args.get("page", 1))
    per_page = int(args.get("per_page", 50))
    return _request("GET", f"/{kind}?page={page}&per_page={per_page}")


def _orders_attribution(args: dict[str, Any]) -> Any:
    days = int(args.get("days", 28))
    return _request("GET", f"/orders-attribution?days={days}")


def _create_seo_draft(args: dict[str, Any]) -> Any:
    import json

    body = json.dumps({
        "post_id": int(args["post_id"]),
        "title": args.get("title"),
        "slug": args.get("slug"),
        "meta_description": args.get("meta_description"),
        "rationale": args.get("rationale", ""),
    })
    return _request("POST", "/create-seo-draft", body=body)


# ----------------------------------------------------------------------------- tools -------

registry.register(Tool(
    name="wp_seo_audit",
    description="Fetch SEO audit data for a single WordPress post/page/product: title, meta "
                "description, slug, H1/H2s, word count, internal link count, images missing alt.",
    input_schema={
        "type": "object",
        "properties": {"post_id": {"type": "integer", "description": "WordPress post ID"}},
        "required": ["post_id"],
    },
    handler=_seo_audit,
))

registry.register(Tool(
    name="wp_list",
    description="List published pages, products, or rentals from the site (paginated summaries).",
    input_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["pages", "products", "rentals"]},
            "page": {"type": "integer", "default": 1},
            "per_page": {"type": "integer", "default": 50},
        },
        "required": ["kind"],
    },
    handler=_list,
))

registry.register(Tool(
    name="woo_revenue_attribution",
    description="WooCommerce revenue & bookings for the last N days, aggregated by acquisition "
                "source (WooCommerce Order Attribution). Use to tie SEO/ad channels to actual "
                "bookings and revenue — the end of the keyword->revenue chain.",
    input_schema={
        "type": "object",
        "properties": {"days": {"type": "integer", "default": 28, "minimum": 1, "maximum": 365}},
    },
    handler=_orders_attribution,
))

registry.register(Tool(
    name="wp_create_seo_draft",
    description="Create a DRAFT (never published) with an improved SEO title, slug, and meta "
                "description for a post, plus a rationale. Returns an edit link for human approval.",
    input_schema={
        "type": "object",
        "properties": {
            "post_id": {"type": "integer"},
            "title": {"type": "string"},
            "slug": {"type": "string"},
            "meta_description": {"type": "string"},
            "rationale": {"type": "string"},
        },
        "required": ["post_id", "title"],
    },
    handler=_create_seo_draft,
))
