"""Site Intelligence core (WP-06 slice 2): snapshot assembly + drift detection. Pure functions —
no network, no store, no provider SDK (portability invariant).

Three-state discipline (owner + reviewer, 2026-07-20):
- OBSERVED current state  -> the snapshot built here from connector reads.
- APPROVED site knowledge -> docs/SITE_PROFILE.md, human-maintained. NEVER written by code;
  snapshots are diffed against it by the MODEL in report context, and discrepancies become
  findings for the owner to arbitrate.
- UNEXPLAINED DRIFT       -> the mechanical diff between consecutive snapshots computed here.
  Drift is an observation queue, not truth: it stays "unexplained" until a report or human
  accounts for it (a deploy, an edit, an incident).
"""

from __future__ import annotations

from typing import Any, Callable

# Fields whose change is meaningful drift (order matters only for display).
_TRACKED_FIELDS = ("title", "slug", "parent", "template", "url", "type")


def build_snapshot(fetch_page: Callable[[int], dict[str, Any]], *, max_pages: int = 50) -> dict[str, Any]:
    """Assemble a full-site snapshot by draining the paged /site-structure endpoint.

    `fetch_page(page)` returns one connector response. Menus and post-type inventory ride on
    page 1 (the endpoint sends them once). `max_pages` is a runaway guard, not a truncation
    target — hitting it raises so a silent partial snapshot can never masquerade as complete.
    """
    first = fetch_page(1)
    items: dict[str, dict[str, Any]] = {}
    for it in first.get("items", []):
        items[str(it["id"])] = it

    total_pages = int(first.get("total_pages", 1))
    if total_pages > max_pages:
        raise ValueError(f"site too large for snapshot guard: {total_pages} pages > max_pages={max_pages}")
    for page in range(2, total_pages + 1):
        for it in fetch_page(page).get("items", []):
            items[str(it["id"])] = it

    return {
        "post_types": first.get("post_types", []),
        "menus": first.get("menus", []),
        "items": items,
        "total_reported": int(first.get("total", len(items))),
    }


def diff_snapshots(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """Mechanical drift between two snapshots. With no prior snapshot, everything is baseline
    (not drift): returns {"baseline": true} plus counts, and no added/removed noise."""
    if old is None:
        return {"baseline": True, "items": len(new.get("items", {}))}

    old_items: dict[str, dict[str, Any]] = old.get("items", {})
    new_items: dict[str, dict[str, Any]] = new.get("items", {})

    added = [new_items[k] for k in new_items.keys() - old_items.keys()]
    removed = [old_items[k] for k in old_items.keys() - new_items.keys()]

    changed = []
    for k in new_items.keys() & old_items.keys():
        deltas = {}
        for field in _TRACKED_FIELDS:
            before, after = old_items[k].get(field), new_items[k].get(field)
            if before != after:
                deltas[field] = {"before": before, "after": after}
        if deltas:
            changed.append({"id": new_items[k]["id"], "slug": new_items[k].get("slug"), "changes": deltas})

    def _menu_shape(snap: dict[str, Any]) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
        return [
            (m.get("name", ""), tuple((e.get("title", ""), e.get("url", "")) for e in m.get("items", [])))
            for m in snap.get("menus", [])
        ]

    menus_changed = _menu_shape(old) != _menu_shape(new)

    type_changes = {}
    old_types = {t["type"]: t for t in old.get("post_types", [])}
    for t in new.get("post_types", []):
        prev = old_types.get(t["type"])
        if prev and prev.get("published") != t.get("published"):
            type_changes[t["type"]] = {"before": prev.get("published"), "after": t.get("published")}
        elif prev is None:
            type_changes[t["type"]] = {"before": None, "after": t.get("published")}

    return {
        "baseline": False,
        "added": sorted(added, key=lambda i: i["id"]),
        "removed": sorted(removed, key=lambda i: i["id"]),
        "changed": sorted(changed, key=lambda i: i["id"]),
        "menus_changed": menus_changed,
        "type_changes": type_changes,
        "has_drift": bool(added or removed or changed or menus_changed or type_changes),
    }


def query_snapshot(
    snapshot: dict[str, Any], *, slug: str = "", post_type: str = "", text: str = "", limit: int = 50
) -> list[dict[str, Any]]:
    """Filter a snapshot's items. Exact slug wins; otherwise type and/or case-insensitive
    substring over slug+title. Empty filters return the first `limit` items by id."""
    items = sorted(snapshot.get("items", {}).values(), key=lambda i: i["id"])
    if slug:
        return [i for i in items if i.get("slug") == slug][:limit]
    needle = text.lower()
    out = []
    for i in items:
        if post_type and i.get("type") != post_type:
            continue
        if needle and needle not in f"{i.get('slug', '')} {i.get('title', '')}".lower():
            continue
        out.append(i)
        if len(out) >= limit:
            break
    return out


def format_digest(taken_at: str, snapshot: dict[str, Any], drift: dict[str, Any] | None,
                  *, max_items: int = 10) -> str:
    """Compact SITE INTELLIGENCE block for task injection. Deliberately small: structure
    summary + drift that needs interpretation + a pointer to the query tool — never the whole
    snapshot (reports reason from the digest and query for detail on demand)."""
    lines = [f"SITE INTELLIGENCE (snapshot {taken_at}, {len(snapshot.get('items', {}))} items):"]

    types = snapshot.get("post_types", [])
    if types:
        lines.append("- Content: " + ", ".join(
            f"{t['type']} ({t.get('published', '?')})" for t in types))
    menus = snapshot.get("menus", [])
    if menus:
        lines.append("- Menus (the site's own primary paths): " + "; ".join(
            f"{m.get('name', '?')} [{len(m.get('items', []))} entries]" for m in menus))

    if drift is None or drift.get("baseline"):
        lines.append("- Drift: first snapshot — baseline established, nothing to compare yet.")
    elif not drift.get("has_drift"):
        lines.append("- Drift: none since the previous snapshot.")
    else:
        lines.append("- UNEXPLAINED DRIFT since the previous snapshot (observed, not explained — "
                     "account for it or flag it for the owner):")
        for key, label in (("added", "added"), ("removed", "removed")):
            rows = drift.get(key, [])
            if rows:
                shown = ", ".join(f"{i.get('slug', i.get('id'))} ({i.get('type', '?')})"
                                  for i in rows[:max_items])
                more = f" +{len(rows) - max_items} more" if len(rows) > max_items else ""
                lines.append(f"  - {label}: {shown}{more}")
        changed = drift.get("changed", [])
        if changed:
            shown = ", ".join(
                f"{c.get('slug', c.get('id'))} [{'/'.join(c.get('changes', {}).keys())}]"
                for c in changed[:max_items])
            more = f" +{len(changed) - max_items} more" if len(changed) > max_items else ""
            lines.append(f"  - changed: {shown}{more}")
        if drift.get("menus_changed"):
            lines.append("  - navigation menus changed — hubs/primary paths may have moved")
        if drift.get("type_changes"):
            lines.append("  - published counts changed: " + ", ".join(
                f"{k} {v.get('before')}→{v.get('after')}"
                for k, v in drift["type_changes"].items()))

    lines.append("- Detail on demand: site_map_query (slug/type/text; classify=true adds "
                 "lifecycle state/tier/confidence/basis).")
    return "\n".join(lines)
