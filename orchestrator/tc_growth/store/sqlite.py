"""SQLite implementation of the Store protocol.

A thin object wrapper over the functional layer (db.py + records.py + seed.py), which is where
ALL SQLite-dialect SQL lives. A future PostgresStore mirrors this class with its own SQL modules;
nothing outside store/ changes.
"""

from __future__ import annotations

from pathlib import Path

from . import records, seed
from .db import connect
from .records import Case, Decision, Run, Snapshot


class SqliteStore:
    """Store backed by a single SQLite connection. Pass ':memory:' in tests."""

    def __init__(self, path: str | Path | None = None):
        self._conn = connect(path)

    # -- cases --
    def create_case(self, **kw) -> int:
        return records.create_case(self._conn, **kw)

    def get_case(self, case_id: int) -> Case | None:
        return records.get_case(self._conn, case_id)

    def get_case_by_ref(self, ref: str) -> Case | None:
        return records.get_case_by_ref(self._conn, ref)

    def list_cases(self, *, status: str | None = None, limit: int = 50) -> list[Case]:
        return records.list_cases(self._conn, status=status, limit=limit)

    def find_cases(self, query: str, *, statuses: tuple[str, ...] | None = None, limit: int = 10) -> list[Case]:
        return records.find_cases(self._conn, query, statuses=statuses, limit=limit)

    def find_open_cases(self, query: str, *, limit: int = 10) -> list[Case]:
        return records.find_open_cases(self._conn, query, limit=limit)

    def update_case(self, case_id: int, **fields) -> None:
        records.update_case(self._conn, case_id, **fields)

    def append_observation(self, case_id: int, text: str, *, author: str = "agent") -> None:
        records.append_observation(self._conn, case_id, text, author=author)

    # -- runs --
    def log_run(self, **kw) -> int:
        return records.log_run(self._conn, **kw)

    def list_runs(self, *, kind: str | None = None, limit: int = 20) -> list[Run]:
        return records.list_runs(self._conn, kind=kind, limit=limit)

    # -- decisions --
    def record_decision(self, **kw) -> int:
        return records.record_decision(self._conn, **kw)

    def get_decision(self, decision_id: int) -> Decision | None:
        return records.get_decision(self._conn, decision_id)

    def update_decision(self, decision_id: int, **fields) -> None:
        records.update_decision(self._conn, decision_id, **fields)

    def list_decisions(self, *, case_id: int | None = None, limit: int = 50) -> list[Decision]:
        return records.list_decisions(self._conn, case_id=case_id, limit=limit)

    # -- lifecycle --
    def save_snapshot(self, *, payload: str, item_count: int, drift: str | None = None,
                      source: str = "wp_site_structure", keep: int = 30) -> int:
        return records.save_snapshot(self._conn, payload=payload, item_count=item_count,
                                     drift=drift, source=source, keep=keep)

    def latest_snapshot(self) -> Snapshot | None:
        return records.latest_snapshot(self._conn)

    def list_snapshots(self, *, limit: int = 20) -> list[Snapshot]:
        return records.list_snapshots(self._conn, limit=limit)

    def seed_incident_case(self) -> int:
        return seed.seed_incident_case(self._conn)

    def close(self) -> None:
        self._conn.close()
