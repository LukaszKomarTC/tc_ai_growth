"""Site Intelligence tools (WP-06 slice 2): snapshot refresh + map query.

Both are READ_ONLY-phase tools: the refresh reads the site through the connector and writes
only to the agent's OWN store (same class as case_note — internal memory, no external side
effect). SITE_PROFILE.md is never touched: snapshots are observations; the human file stays
the approved baseline; the diff between snapshots is unexplained drift until accounted for.
"""

from __future__ import annotations

import json
from typing import Any

from ..core.site_intel import build_snapshot, check_expectations, diff_snapshots, query_snapshot
from ..store import open_store
from .base import Tool, ToolError, registry
from .wordpress import _site_structure


def _refresh(args: dict[str, Any]) -> Any:
    def fetch_page(page: int) -> dict[str, Any]:
        return _site_structure({"page": page, "per_page": 200})

    snapshot = build_snapshot(fetch_page)

    store = open_store()
    try:
        prev_row = store.latest_snapshot()
        prev = json.loads(prev_row.payload) if prev_row else None
        drift = diff_snapshots(prev, snapshot)
        # Approved-vs-observed runs against THIS snapshot (not the previous one), so defects
        # already present at the first snapshot surface as violations, never hide as baseline.
        drift["expectation_violations"] = check_expectations(snapshot)
        snap_id = store.save_snapshot(
            payload=json.dumps(snapshot, ensure_ascii=False),
            item_count=len(snapshot["items"]),
            drift=json.dumps(drift, ensure_ascii=False),
        )
    finally:
        store.close()

    summary = {
        "snapshot_id": snap_id,
        "items": len(snapshot["items"]),
        "post_types": snapshot["post_types"],
        "menu_count": len(snapshot["menus"]),
        "drift": drift,
    }
    if drift.get("expectation_violations"):
        summary["note_expectations"] = (
            "Observed state disagrees with owner-approved knowledge — cite the violation's "
            "source and flag it for the owner; do not 'fix' structure autonomously."
        )
    if not drift.get("baseline") and drift.get("has_drift"):
        summary["note"] = (
            "Changes are OBSERVED, not explained. Account for them (deploy, edit, incident) in "
            "the report or flag them for the owner; SITE_PROFILE.md remains the approved baseline."
        )
    return summary


def _query(args: dict[str, Any]) -> Any:
    store = open_store()
    try:
        row = store.latest_snapshot()
    finally:
        store.close()
    if row is None:
        raise ToolError("No site snapshot yet — run site_snapshot_refresh first.")

    snapshot = json.loads(row.payload)
    matches = query_snapshot(
        snapshot,
        slug=str(args.get("slug", "")),
        post_type=str(args.get("type", "")),
        text=str(args.get("text", "")),
        limit=min(50, int(args.get("limit", 20))),
    )

    if args.get("classify"):
        import datetime as dt
        from zoneinfo import ZoneInfo

        from ..core.lifecycle import classify_lifecycle

        today = dt.datetime.now(ZoneInfo("Europe/Madrid")).date()
        matches = [{**m, "lifecycle": classify_lifecycle(m, today=today)} for m in matches]

    return {"snapshot_id": row.id, "taken_at": row.taken_at, "matches": matches,
            "menus": snapshot.get("menus", []) if args.get("include_menus") else []}


registry.register(Tool(
    name="site_snapshot_refresh",
    description="Build a fresh Site Intelligence snapshot (all public content, menus, post-type "
                "inventory) through the connector, store it versioned, and return the drift vs "
                "the previous snapshot. Drift is observation, not explanation — account for it "
                "or flag it. Run before structural reasoning on a site.",
    input_schema={"type": "object", "properties": {}},
    handler=_refresh,
))

registry.register(Tool(
    name="site_map_query",
    description="Query the latest Site Intelligence snapshot: find pages/products by exact slug, "
                "post type, or text match over slug+title (raw, qTranslate tags included). Use "
                "instead of guessing post IDs or URL structure; set include_menus=true to see "
                "the site's navigation paths.",
    input_schema={
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "Exact slug match (wins over other filters)"},
            "type": {"type": "string", "description": "Filter by post type, e.g. 'page', 'product'"},
            "text": {"type": "string", "description": "Case-insensitive substring over slug + raw title"},
            "limit": {"type": "integer", "default": 20, "maximum": 50},
            "include_menus": {"type": "boolean", "default": False},
            "classify": {"type": "boolean", "default": False,
                         "description": "Annotate each match with its commercial lifecycle "
                                        "(state/tier/confidence/basis via the approved evidence ladder)"},
        },
    },
    handler=_query,
))
