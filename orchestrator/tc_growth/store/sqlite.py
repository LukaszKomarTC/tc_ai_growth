"""SQLite implementation of the Store protocol.

A thin object wrapper over the functional layer (db.py + records.py + seed.py), which is where
ALL SQLite-dialect SQL lives. A future PostgresStore mirrors this class with its own SQL modules;
nothing outside store/ changes.
"""

from __future__ import annotations

from pathlib import Path

from . import records, seed
from .db import connect
from .records import Case, Decision, DecisionEvent, ReportArtifact, Run, VerifyAttempt


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

    # -- decision approval workflow (U4a) --
    def propose_decision(self, **kw) -> int:
        return records.propose_decision(self._conn, **kw)

    def approve_decision(self, decision_id: int, *, expected_revision: int,
                         actor: str = "owner") -> str:
        return records.approve_decision(self._conn, decision_id,
                                        expected_revision=expected_revision, actor=actor)

    def reject_decision(self, decision_id: int, *, expected_revision: int, reason: str,
                        actor: str = "owner") -> None:
        records.reject_decision(self._conn, decision_id, expected_revision=expected_revision,
                                reason=reason, actor=actor)

    def unapprove_decision(self, decision_id: int, *, expected_revision: int,
                           actor: str = "owner") -> None:
        records.unapprove_decision(self._conn, decision_id,
                                   expected_revision=expected_revision, actor=actor)

    def repropose_decision(self, decision_id: int, *, expected_revision: int,
                           envelope: dict | None = None,
                           expected_profile: str | None = None,
                           allowed_environments: tuple[str, ...] | None = None,
                           allowed_hosts: tuple[str, ...] | None = None,
                           actor: str = "owner") -> None:
        records.repropose_decision(self._conn, decision_id,
                                   expected_revision=expected_revision, envelope=envelope,
                                   expected_profile=expected_profile,
                                   allowed_environments=allowed_environments,
                                   allowed_hosts=allowed_hosts, actor=actor)

    def list_decision_events(self, decision_id: int) -> list[DecisionEvent]:
        return records.list_decision_events(self._conn, decision_id)

    # -- adopt-live idempotence (U4c) --
    def adopted_decision_id(self, key: str) -> int | None:
        return records.adopted_decision_id(self._conn, key)

    def claim_adoption(self, key: str, **kw) -> bool:
        return records.claim_adoption(self._conn, key, **kw)

    def complete_adoption(self, key: str, decision_id: int) -> None:
        records.complete_adoption(self._conn, key, decision_id)

    # -- verification (U4b) --
    def record_verify_attempt(self, **kw) -> int:
        return records.record_verify_attempt(self._conn, **kw)

    def list_verify_attempts(self, decision_id: int) -> list[VerifyAttempt]:
        return records.list_verify_attempts(self._conn, decision_id)

    def pending_verify_attempt(self, decision_id: int, *, revision: int) -> VerifyAttempt | None:
        return records.pending_verify_attempt(self._conn, decision_id, revision=revision)

    def execute_decision(self, decision_id: int, *, expected_revision: int,
                         evidence_attempt_id: int, actor: str = "platform") -> None:
        records.execute_decision(self._conn, decision_id, expected_revision=expected_revision,
                                 evidence_attempt_id=evidence_attempt_id, actor=actor)

    # -- report artifacts --
    def persist_report_artifact(self, **kw) -> int:
        return records.persist_report_artifact(self._conn, **kw)

    def get_report_artifact(self, artifact_id: int) -> ReportArtifact | None:
        return records.get_report_artifact(self._conn, artifact_id)

    def latest_report_artifact(self, *, kind: str | None = None) -> ReportArtifact | None:
        return records.latest_report_artifact(self._conn, kind=kind)

    def list_report_artifacts(self, *, kind: str | None = None, limit: int = 20) -> list[ReportArtifact]:
        return records.list_report_artifacts(self._conn, kind=kind, limit=limit)

    def set_artifact_delivery(self, artifact_id: int, status: str) -> None:
        records.set_artifact_delivery(self._conn, artifact_id, status)

    def set_artifact_delivery_by_hash(self, content_sha256: str, status: str) -> bool:
        return records.set_artifact_delivery_by_hash(self._conn, content_sha256, status)

    # -- WP-U4d deploys --
    def plan_deploy(self, *, sha: str, plan: dict, plan_digest: str, requested_by: str) -> int:
        return records.plan_deploy(self._conn, sha=sha, plan=plan, plan_digest=plan_digest,
                                   requested_by=requested_by)

    def get_deploy_run(self, run_id: int) -> dict | None:
        return records.get_deploy_run(self._conn, run_id)

    def list_deploy_runs(self, *, limit: int = 20) -> list[dict]:
        return records.list_deploy_runs(self._conn, limit=limit)

    def start_deploy_run(self, run_id: int, *, pid: int) -> bool:
        return records.start_deploy_run(self._conn, run_id, pid=pid)

    def finish_deploy_run(self, run_id: int, *, status: str, outcome: str) -> None:
        records.finish_deploy_run(self._conn, run_id, status=status, outcome=outcome)

    def record_deploy_step(self, run_id: int, *, seq: int, name: str, status: str,
                           summary: str, detail: str | None = None) -> int:
        return records.record_deploy_step(self._conn, run_id, seq=seq, name=name, status=status,
                                          summary=summary, detail=detail)

    def list_deploy_steps(self, run_id: int) -> list[dict]:
        return records.list_deploy_steps(self._conn, run_id)

    # -- lifecycle --
    def seed_incident_case(self) -> int:
        return seed.seed_incident_case(self._conn)

    def close(self) -> None:
        self._conn.close()
