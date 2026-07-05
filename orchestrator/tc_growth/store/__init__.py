"""Persistence layer (Phase 2): the agent's structured memory.

Application code uses the backend-neutral repository interface:

    from tc_growth.store import open_store
    s = open_store()            # -> Store (today: SqliteStore)
    s.log_run(kind="weekly-report", ...)
    s.find_open_cases("tobacco spam")

`open_store()` is the ONLY place a backend is chosen; swapping SQLite for PostgreSQL means adding
a PostgresStore and extending the factory — no caller changes. The functional layer (connect +
per-table helpers) remains exported for tests and store-internal use, but new app code should go
through the Store object.
"""

from __future__ import annotations

from pathlib import Path

from .base import Store
from .db import connect, init_db, resolved_db_path
from .records import (
    Case,
    Decision,
    Run,
    append_observation,
    create_case,
    find_open_cases,
    get_case,
    get_case_by_ref,
    list_cases,
    list_decisions,
    list_runs,
    log_run,
    record_decision,
    record_run,
    update_case,
)
from .seed import INCIDENT_REF, seed_incident_case
from .sqlite import SqliteStore


def open_store(path: str | Path | None = None) -> Store:
    """Open the configured persistence backend. Today that is always SQLite; this factory is the
    seam where a PostgresStore would be selected (e.g. from a TC_DB_URL setting) later."""
    return SqliteStore(path)


__all__ = [
    "Store",
    "SqliteStore",
    "open_store",
    "connect",
    "init_db",
    "resolved_db_path",
    "Case",
    "Run",
    "Decision",
    "create_case",
    "get_case",
    "get_case_by_ref",
    "list_cases",
    "find_open_cases",
    "update_case",
    "append_observation",
    "record_run",
    "log_run",
    "list_runs",
    "record_decision",
    "list_decisions",
    "seed_incident_case",
    "INCIDENT_REF",
]
