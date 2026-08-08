"""Backend-neutral store interface (the repository seam).

Application code depends on this protocol — `open_store()` hands back *a* Store, and nothing
outside `store/` may know which dialect is underneath. `SqliteStore` is today's implementation;
a future `PostgresStore` implements the same protocol with its own SQL and becomes a drop-in.

Keep this file SQL-free by definition. If a method signature here needs dialect-specific
knowledge to express, the design is wrong.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .records import Case, Decision, DecisionEvent, ReportArtifact, Run, VerifyAttempt


@runtime_checkable
class Store(Protocol):
    """What every persistence backend must implement."""

    # -- cases --
    def create_case(
        self,
        *,
        title: str,
        ref: str | None = None,
        category: str | None = None,
        status: str = "open",
        priority: str = "medium",
        confidence: str | None = None,
        body: str | None = None,
    ) -> int: ...

    def get_case(self, case_id: int) -> Case | None: ...

    def get_case_by_ref(self, ref: str) -> Case | None: ...

    def list_cases(self, *, status: str | None = None, limit: int = 50) -> list[Case]: ...

    def find_cases(
        self, query: str, *, statuses: tuple[str, ...] | None = None, limit: int = 10
    ) -> list[Case]: ...

    def find_open_cases(self, query: str, *, limit: int = 10) -> list[Case]: ...

    def update_case(self, case_id: int, **fields: object) -> None: ...

    def append_observation(self, case_id: int, text: str, *, author: str = "agent") -> None: ...

    # -- runs --
    def log_run(
        self,
        *,
        kind: str,
        model: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        duration_s: float | None = None,
        status: str = "ok",
        summary: str | None = None,
        detail: str | None = None,
        case_id: int | None = None,
        started_at: str | None = None,
    ) -> int: ...

    def list_runs(self, *, kind: str | None = None, limit: int = 20) -> list[Run]: ...

    # -- decisions --
    def record_decision(
        self,
        *,
        title: str,
        rationale: str | None = None,
        status: str = "active",
        outcome: str | None = None,
        case_id: int | None = None,
        made_at: str | None = None,
    ) -> int: ...

    def list_decisions(self, *, case_id: int | None = None, limit: int = 50) -> list[Decision]: ...

    def get_decision(self, decision_id: int) -> Decision | None: ...

    def update_decision(self, decision_id: int, **fields: object) -> None: ...

    # -- decision approval workflow (U4a) --
    # CONSTITUTIONAL INVARIANTS (backend-neutral, same standing as the artifact rule below),
    # stated with their precise enforcement layer (review #71): the STORAGE layer of whatever
    # backend implements this protocol (SQLite: triggers; a PostgresStore must bring an
    # equivalent) enforces — even against raw SQL — that an APPROVED envelope is immutable
    # (only path away: the explicit unapprove transition), that EXECUTED is terminal, that
    # audit events are append-only, and that workflow rows move only along the spec's
    # transition graph. The STORE API additionally guarantees revision-based concurrency,
    # proposal-boundary context checks, and that every successful transition appends its audit
    # event in the same transaction — that coupling is an API guarantee, deliberately not
    # claimed of the database. An implementation without the storage-layer half does not
    # satisfy this protocol, regardless of API discipline.
    def propose_decision(
        self,
        *,
        title: str,
        envelope: dict,
        expected_profile: str,
        allowed_environments: tuple[str, ...],
        allowed_hosts: tuple[str, ...],
        rationale: str | None = None,
        evidence: str | None = None,
        impact: dict | None = None,
        confidence: dict | None = None,
        case_id: int | None = None,
        made_by: str = "agent",
    ) -> int: ...

    def approve_decision(
        self, decision_id: int, *, expected_revision: int, actor: str = "owner"
    ) -> str: ...

    def reject_decision(
        self, decision_id: int, *, expected_revision: int, reason: str, actor: str = "owner"
    ) -> None: ...

    def unapprove_decision(
        self, decision_id: int, *, expected_revision: int, actor: str = "owner"
    ) -> None: ...

    def repropose_decision(
        self, decision_id: int, *, expected_revision: int, envelope: dict | None = None,
        expected_profile: str | None = None,
        allowed_environments: tuple[str, ...] | None = None,
        allowed_hosts: tuple[str, ...] | None = None, actor: str = "owner"
    ) -> None: ...

    def list_decision_events(self, decision_id: int) -> list[DecisionEvent]: ...

    # -- adopt-live idempotence (U4c) --
    # CONSTITUTIONAL: duplicate prevention is a UNIQUE KEY in the backend, never an application
    # scan over recent rows — the guarantee must not decay as the archive grows.
    def adopted_decision_id(self, key: str) -> int | None: ...

    def claim_adoption(self, key: str, *, source_id: int, source_revision: int,
                       envelope_sha256: str, snapshot_digest: str) -> bool: ...

    def complete_adoption(self, key: str, decision_id: int) -> None: ...

    # -- verification (U4b) --
    # CONSTITUTIONAL INVARIANT: verification attempts are APPEND-ONLY at the storage layer
    # (SQLite: triggers) — a success can never rewrite or remove a failure, and
    # execution_evidence only POINTS at the terminal attempt. executed remains terminal.
    def record_verify_attempt(
        self,
        *,
        decision_id: int,
        revision: int,
        envelope_sha256: str,
        read_number: int,
        outcome: str,
        detail: str,
        started_at: str,
        pair_id: int | None = None,
    ) -> int: ...

    def list_verify_attempts(self, decision_id: int) -> list[VerifyAttempt]: ...

    def pending_verify_attempt(
        self, decision_id: int, *, revision: int
    ) -> VerifyAttempt | None: ...

    def execute_decision(
        self, decision_id: int, *, expected_revision: int, evidence_attempt_id: int,
        actor: str = "platform"
    ) -> None: ...

    # -- report artifacts (U3a: immutable, hash-verified) --
    # CONSTITUTIONAL INVARIANT (backend-neutral): the artifact core (body, hash, verdict,
    # provenance) is immutable AT THE STORAGE LAYER of whatever backend implements this
    # protocol — SQLite does it with a trigger; a PostgresStore must bring an equivalent
    # (rule/permission/trigger). Only delivery_status / delivery_attempts / delivered_at may
    # change. An implementation without storage-layer enforcement does not satisfy this
    # protocol, regardless of API discipline. One artifact, many delivery attempts.
    def persist_report_artifact(
        self,
        *,
        kind: str,
        body: str,
        validator_ok: bool,
        validator_reason: str | None,
        validator_version: str,
        run_id: int | None = None,
        profile: str | None = None,
        window: str | None = None,
        model: str | None = None,
        cost_usd: float | None = None,
        format_version: str = "md/1",
        generated_at: str | None = None,
    ) -> int: ...

    def get_report_artifact(self, artifact_id: int) -> ReportArtifact | None: ...

    def latest_report_artifact(self, *, kind: str | None = None) -> ReportArtifact | None: ...

    def list_report_artifacts(
        self, *, kind: str | None = None, limit: int = 20
    ) -> list[ReportArtifact]: ...

    def set_artifact_delivery(self, artifact_id: int, status: str) -> None: ...

    def set_artifact_delivery_by_hash(self, content_sha256: str, status: str) -> bool: ...

    # -- WP-U4d deploys --
    def plan_deploy(self, *, sha: str, plan: dict, plan_digest: str,
                    requested_by: str) -> int: ...

    def get_deploy_run(self, run_id: int) -> dict | None: ...

    def list_deploy_runs(self, *, limit: int = 20) -> list[dict]: ...

    def start_deploy_run(self, run_id: int, *, pid: int) -> bool: ...

    def finish_deploy_run(self, run_id: int, *, status: str, outcome: str) -> None: ...

    def record_deploy_step(self, run_id: int, *, seq: int, name: str, status: str,
                           summary: str, detail: str | None = None) -> int: ...

    def list_deploy_steps(self, run_id: int) -> list[dict]: ...

    # -- WP-U4d.2 acceptance runs --
    # CONSTITUTIONAL INVARIANT: phases are append-only and a 'done' run is terminal (triggers
    # enforce both at the storage layer); begin_acceptance_run resolves the at-most-one-live-run
    # rule in the database, not in application code.
    def begin_acceptance_run(self, *, requested_by: str, root: str) -> int | None: ...

    def set_acceptance_root(self, run_id: int, root: str) -> bool: ...

    def get_acceptance_run(self, run_id: int) -> dict | None: ...

    def list_acceptance_runs(self, *, limit: int = 20) -> list[dict]: ...

    def claim_acceptance_run(self, run_id: int) -> bool: ...

    def finish_acceptance_run(self, run_id: int, *, verdict: str, summary: str) -> None: ...

    def record_acceptance_phase(self, run_id: int, *, seq: int, name: str, status: str,
                                detail: str | None = None) -> int: ...

    def list_acceptance_phases(self, run_id: int) -> list[dict]: ...

    # -- WP-U5.1: inspection runs and observations --
    # CONSTITUTIONAL INVARIANT: observations are append-only, a 'done' inspection run is
    # terminal, and a run's (profile, environment) is immutable — all three enforced by
    # triggers. `profile` and `environment` are REQUIRED on every call: U5 evidence never
    # inherits its subject from process-global state (issue #82 amendment 1).
    def begin_inspection_run(self, *, profile: str, environment: str, trigger: str,
                             collector_set_version: str, repo_commit: str) -> int: ...

    def finish_inspection_run(self, run_id: int, *, summary: str) -> None: ...

    def get_inspection_run(self, run_id: int) -> dict | None: ...

    def latest_inspection_run(self, *, profile: str, environment: str) -> dict | None: ...

    def latest_observation(self, *, profile: str, environment: str,
                           scope: str) -> dict | None: ...

    def record_observation(self, run_id: int, *, collector_id: str, collector_version: str,
                           scope: str, source: str, profile: str, environment: str,
                           captured_at: str, status: str, value_json: str, value_digest: str,
                           evidence: str | None, predecessor_id: int | None, change_class: str,
                           severity: str, confidence: str | None, reason: str | None,
                           material_json: str | None = None,
                           material_digest: str | None = None) -> int: ...

    def list_observations(self, run_id: int) -> list[dict]: ...

    def latest_observations(self, *, profile: str, environment: str) -> list[dict]: ...

    # -- lifecycle --
    def seed_incident_case(self) -> int: ...

    def close(self) -> None: ...
