"""Seed the store's first real content: the Merchant Center tobacco-spam incident as Case #1.

The narrative already exists as docs/incidents/2026-02-merchant-center-tobacco-spam.md; this reads
it into the `cases` table so the coordinator can consult it (and stop rediscovering the incident
as a "new" threat every week). Idempotent — running twice does not duplicate the case.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..config import ENV_PATH
from .records import create_case, get_case_by_ref

INCIDENT_REF = "INC-2026-02-01"
_INCIDENT_DOC = ENV_PATH.parents[1] / "docs" / "incidents" / "2026-02-merchant-center-tobacco-spam.md"

# Fallback body if the markdown isn't present (e.g. a partial checkout).
_FALLBACK_BODY = (
    "Historical tobacco-spam via a Google Merchant Center feed/access pointing phantom URLs at the "
    "verified domain (not the WordPress filesystem). First seen 2026-02-12, peaked Feb 27-Mar 2, "
    "impressions cliff ~Mar 29, decaying tail since. Merchant Center account confirmed clean "
    "(no rogue products/feed). Contained; exact entry vector unidentified but no longer present. "
    "Recurrence guarded by 2FA on the owning Google account. See docs/incidents/ for the full record."
)


def seed_incident_case(conn: sqlite3.Connection) -> int:
    """Create Case #1 from the incident doc if it doesn't already exist. Returns the case id."""
    existing = get_case_by_ref(conn, INCIDENT_REF)
    if existing:
        return existing.id
    try:
        body = _INCIDENT_DOC.read_text(encoding="utf-8")
    except OSError:
        body = _FALLBACK_BODY
    return create_case(
        conn,
        ref=INCIDENT_REF,
        title="Tobacco-spam listings on tossacycling.com (Merchant Center)",
        category="incident",
        status="resolved",
        priority="medium",
        confidence="medium-high",
        body=body,
    )
