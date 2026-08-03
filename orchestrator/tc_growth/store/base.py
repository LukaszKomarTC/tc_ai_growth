"""Backend-neutral store interface (the repository seam).

Application code depends on this protocol — `open_store()` hands back *a* Store, and nothing
outside `store/` may know which dialect is underneath. `SqliteStore` is today's implementation;
a future `PostgresStore` implements the same protocol with its own SQL and becomes a drop-in.

Keep this file SQL-free by definition. If a method signature here needs dialect-specific
knowledge to express, the design is wrong.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .records import Case, Decision, ReportArtifact, Run


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

    # -- report artifacts (U3a: immutable, hash-verified) --
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

    # -- lifecycle --
    def seed_incident_case(self) -> int: ...

    def close(self) -> None: ...
