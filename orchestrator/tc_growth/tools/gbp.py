"""Google Business Profile tool — local SEO (reviews, posts).

Read-only in early phases (list reviews, read profile). Post creation stays draft-only and is
surfaced for human approval. The Business Profile APIs require per-account allow-listing; until
granted, this returns a clear error.
"""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolError, registry


def _reviews(args: dict[str, Any]) -> Any:
    # The Business Profile API requires OAuth + account/location IDs and is access-gated.
    # Wire the real call once access is granted (see docs/SETUP.md).
    raise ToolError(
        "Google Business Profile API access not yet provisioned. Request access and add the "
        "account/location IDs + OAuth credentials (docs/SETUP.md). This tool stays read-only "
        "in Phase 1-2; GBP posts are draft-only and require human approval."
    )


registry.register(Tool(
    name="gbp_list_reviews",
    description="List recent Google Business Profile reviews for monitoring and suggested "
                "replies (read-only). Local SEO lever for Tossa de Mar / Costa Brava.",
    input_schema={
        "type": "object",
        "properties": {"location_id": {"type": "string"}, "limit": {"type": "integer", "default": 20}},
    },
    handler=_reviews,
))
