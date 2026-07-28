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


def _site_structure(args: dict[str, Any]) -> Any:
    page = int(args.get("page", 1))
    per_page = int(args.get("per_page", 100))
    types = str(args.get("types", "")).strip()
    path = f"/site-structure?page={page}&per_page={per_page}"
    if types:
        path += f"&types={types}"
    return _request("GET", path)


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


def _create_product_revision(args: dict[str, Any]) -> Any:
    import json

    body = json.dumps({
        "post_id": int(args["post_id"]),
        "description": args.get("description", ""),
        "rationale": args.get("rationale", ""),
    })
    return _request("POST", "/create-product-revision", body=body)


def _publish_seo_draft(args: dict[str, Any]) -> Any:
    import json

    body = json.dumps({"draft_id": int(args["draft_id"])})
    return _request("POST", "/publish-seo-draft", body=body)


def _create_draft_asset(asset_type: str, args: dict[str, Any]) -> Any:
    import json

    body = json.dumps({
        "asset_type": asset_type,
        "title": args.get("title", ""),
        "body": args.get("body", ""),
        "target_url": args.get("target_url", ""),
        "rationale": args.get("rationale", ""),
        "meta": args.get("meta", {}),
    })
    return _request("POST", "/create-draft-asset", body=body)


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
    name="wp_site_structure",
    description="Site Intelligence: post-type inventory, navigation menus, and a paged list of "
                "all public content with RAW titles (qTranslate tags included), slugs, parents, "
                "templates, and dates. Use to understand what the site IS before recommending "
                "structural or routing changes — menus show the site's own primary paths.",
    input_schema={
        "type": "object",
        "properties": {
            "page": {"type": "integer", "default": 1},
            "per_page": {"type": "integer", "default": 100},
            "types": {"type": "string", "description": "Optional comma-separated post types filter (e.g. 'page,product')"},
        },
    },
    handler=_site_structure,
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

registry.register(Tool(
    name="wp_create_product_revision",
    description="Create a native WordPress revision of a product DESCRIPTION (content only) for "
                "human review/restore. Never touches price, stock, or availability.",
    input_schema={
        "type": "object",
        "properties": {
            "post_id": {"type": "integer"},
            "description": {"type": "string", "description": "Improved product description (HTML allowed)"},
            "rationale": {"type": "string"},
        },
        "required": ["post_id", "description"],
    },
    handler=_create_product_revision,
))

# Phase 2 draft assets — ad copy and GBP posts stored as drafts for human approval. No writes to
# any ad platform; these produce reviewable content under "Growth Drafts" in wp-admin.
_ASSET_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Headline / short label"},
        "body": {"type": "string", "description": "Full copy (HTML allowed)"},
        "target_url": {"type": "string", "description": "Landing page the asset points to"},
        "rationale": {"type": "string"},
        "meta": {"type": "object", "description": "Optional structured fields (e.g. headlines, descriptions, keywords)"},
    },
    "required": ["title", "body"],
}

registry.register(Tool(
    name="draft_google_ad",
    description="Draft Google Ads copy (responsive search ad: headlines + descriptions) for a "
                "landing page, stored as a DRAFT for human approval. Does not create or change "
                "any live campaign.",
    input_schema=_ASSET_SCHEMA,
    handler=lambda args: _create_draft_asset("google_ad", args),
))

registry.register(Tool(
    name="draft_meta_ad",
    description="Draft Meta (Facebook/Instagram) ad copy (primary text, headline, description) "
                "for a campaign idea, stored as a DRAFT for human approval. No live changes.",
    input_schema=_ASSET_SCHEMA,
    handler=lambda args: _create_draft_asset("meta_ad", args),
))

registry.register(Tool(
    name="draft_gbp_post",
    description="Draft a Google Business Profile post (offer/update/event) for Tossa Cycling, "
                "stored as a DRAFT for human approval. Does not publish to GBP.",
    input_schema=_ASSET_SCHEMA,
    handler=lambda args: _create_draft_asset("gbp_post", args),
))

# Phase 3 — controlled execution. Applies a HUMAN-APPROVED SEO draft to the live page. Gated to
# CONTROLLED_EXECUTION phase AND always-ask confirmation in the runtimes; the connector also
# refuses unless a human marked the draft approved. Triple-gated by design.
registry.register(Tool(
    name="publish_seo_draft",
    description="Apply a previously human-APPROVED SEO draft to its live source page (title, slug, "
                "meta description). Fails unless a human approved the draft in WordPress. This is "
                "the only tool that changes the live site.",
    input_schema={
        "type": "object",
        "properties": {"draft_id": {"type": "integer", "description": "ID of an approved SEO draft"}},
        "required": ["draft_id"],
    },
    handler=_publish_seo_draft,
))
