"""Persistence layer (Phase 2): the agent's structured memory.

Public surface — import from `tc_growth.store`, not the submodules:

    from tc_growth.store import connect, record_run, create_case, find_open_cases
"""

from __future__ import annotations

from .db import connect, init_db, resolved_db_path
from .records import (
    Case,
    Decision,
    Run,
    create_case,
    find_open_cases,
    get_case,
    get_case_by_ref,
    list_cases,
    list_decisions,
    list_runs,
    record_decision,
    record_run,
    update_case,
)
from .seed import INCIDENT_REF, seed_incident_case

__all__ = [
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
    "record_run",
    "list_runs",
    "record_decision",
    "list_decisions",
    "seed_incident_case",
    "INCIDENT_REF",
]
