"""Action Registry — named operations as declarative data (Evidence Platform spec §5a).

The catalogue of operations that GENUINELY exist in this platform: what they are, what
phase and environment they require, what approval class governs them, and which code
layers actually enforce those constraints. Definitions are code (versioned by git);
executions become evidence rows only when the 1.1 execution ledger is built (spec §5b).

Two disciplines, both test-enforced:
- Entries describe reality, not roadmap intent: every tool-bound entry must agree with
  the enforcement layer (TOOL_MIN_PHASE / ALWAYS_ASK) and name a registered tool.
- Documentation is not enforcement: `rollback_description` / `verification_description`
  are prose for humans; only `enforced_by` names the code that actually refuses a call.
  A field graduates to `*_handler` ONLY when a machine-executed handler exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .approval import ALWAYS_ASK, TOOL_MIN_PHASE, Phase


class Category(str, Enum):
    ANALYSIS = "analysis"          # read + reason + report
    INTELLIGENCE = "intelligence"  # snapshot/query the platform's own evidence stores
    DIAGNOSTICS = "diagnostics"    # operator-facing health/inspection checks
    DRAFTING = "drafting"          # produce reviewable artifacts, never live changes
    EXECUTION = "execution"        # change external state (always human-confirmed)


class Approval(str, Enum):
    NONE = "none"                            # read-only; no human step required
    HUMAN_REVIEW_OF_OUTPUT = "review_output" # artifact reviewed/approved by a human after creation
    ALWAYS_ASK = "always_ask"                # explicit per-call human confirmation (approval.ALWAYS_ASK)


@dataclass(frozen=True)
class Operation:
    id: str
    name: str
    category: Category
    min_phase: Phase
    environments: tuple[str, ...]      # environments this operation may TARGET
    approval: Approval
    tool: str | None = None            # registered tool this operation is bound to
    command: str | None = None         # CLI entrypoint (python -m tc_growth.cli <command>)
    preconditions: tuple[str, ...] = ()
    enforced_by: tuple[str, ...] = ()  # code layers that actually refuse a bad call
    rollback_description: str = ""     # prose — NOT machine-enforced (see module docstring)
    verification_description: str = "" # prose — NOT machine-enforced
    enabled: bool = True


_READ_ROLLBACK = "not required — read-only; no external state is changed"
_GATE = "phase gate (core.approval.is_tool_allowed)"
_PROFILE_CAP = "profile write cap (TC_ALLOW_WRITES=false blocks all above-READ_ONLY tools)"
_CONNECTOR_AUTH = "connector auth (Application Password + HMAC signature)"

OPERATIONS: tuple[Operation, ...] = (
    Operation(
        id="run_weekly_report",
        name="Run weekly growth report",
        category=Category.ANALYSIS,
        min_phase=Phase.READ_ONLY,
        environments=("staging", "production"),
        approval=Approval.NONE,
        command="weekly-report",
        preconditions=("configured profile (--site)", "GSC/GA4/ads credentials provisioned"),
        enforced_by=(_GATE, "scheduled unit runs the fixed profile only"),
        rollback_description=_READ_ROLLBACK,
        verification_description="report lint warnings appended to output; run logged to the "
                                 "ledger with model/tokens/cost; Monday runs graded per "
                                 "docs/VALIDATION.md criteria",
    ),
    Operation(
        id="run_investigation",
        name="Run forensic investigation",
        category=Category.ANALYSIS,
        min_phase=Phase.READ_ONLY,
        environments=("staging", "production"),
        approval=Approval.NONE,
        command="investigate",
        preconditions=("a specific question or anomaly to investigate",),
        enforced_by=(_GATE,),
        rollback_description=_READ_ROLLBACK,
        verification_description="evidence-graded findings (observation/hypothesis/conclusion "
                                 "labels); run logged to the ledger",
    ),
    Operation(
        id="run_draft_test",
        name="Run supervised drafting session",
        category=Category.DRAFTING,
        min_phase=Phase.DRAFTS,
        environments=("staging",),
        approval=Approval.HUMAN_REVIEW_OF_OUTPUT,
        command="draft-test",
        preconditions=("operator-supervised session", "staging profile with writes enabled"),
        enforced_by=(_GATE, _PROFILE_CAP, _CONNECTOR_AUTH),
        rollback_description="drafts are inert WordPress posts; delete the draft to undo",
        verification_description="human reviews the produced draft in wp-admin (Growth Drafts)",
    ),
    Operation(
        id="run_smoke_test",
        name="Smoke-test a single tool",
        category=Category.DIAGNOSTICS,
        min_phase=Phase.READ_ONLY,
        environments=("staging", "production"),
        approval=Approval.NONE,
        command="smoke",
        preconditions=("operator CLI access (SSH)",),
        # Honest entry: cmd_smoke dispatches DIRECTLY, bypassing the orchestrator-side
        # phase gate and profile cap — only connector-side guards remain. Operator-only
        # by construction; treat like any other privileged shell command.
        enforced_by=(_CONNECTOR_AUTH, "server-side TC_GROWTH_DISABLE_WRITES on production"),
        rollback_description="read tools: none needed; NEVER smoke a write tool against "
                             "an environment you would not change by hand",
        verification_description="tool payload printed for operator inspection; exit code "
                                 "reflects ok flag",
    ),
    Operation(
        id="create_seo_draft",
        name="Create SEO draft",
        category=Category.DRAFTING,
        min_phase=Phase.DRAFTS,
        environments=("staging",),
        approval=Approval.HUMAN_REVIEW_OF_OUTPUT,
        tool="wp_create_seo_draft",
        preconditions=("target post exists", "staging profile with writes enabled"),
        enforced_by=(_GATE, _PROFILE_CAP, _CONNECTOR_AUTH),
        rollback_description="draft is an inert post under Growth Drafts; delete to undo; "
                             "source page untouched until publish_seo_draft",
        verification_description="draft visible in wp-admin with rationale; human approves "
                                 "via the approval metabox before any apply",
    ),
    Operation(
        id="create_product_revision",
        name="Create product description revision",
        category=Category.DRAFTING,
        min_phase=Phase.DRAFTS,
        environments=("staging",),
        approval=Approval.HUMAN_REVIEW_OF_OUTPUT,
        tool="wp_create_product_revision",
        preconditions=("target product exists", "staging profile with writes enabled"),
        enforced_by=(_GATE, _PROFILE_CAP, _CONNECTOR_AUTH),
        rollback_description="native WP revision — restore the prior revision in wp-admin",
        verification_description="revision visible in the product's revision history for "
                                 "human review/restore",
    ),
    Operation(
        id="draft_google_ad",
        name="Draft Google Ads copy",
        category=Category.DRAFTING,
        min_phase=Phase.DRAFTS,
        environments=("staging",),
        approval=Approval.HUMAN_REVIEW_OF_OUTPUT,
        tool="draft_google_ad",
        preconditions=("staging profile with writes enabled",),
        enforced_by=(_GATE, _PROFILE_CAP, _CONNECTOR_AUTH),
        rollback_description="stored as an inert Growth Draft asset; delete to undo; no ad "
                             "platform is ever touched",
        verification_description="asset reviewable under Growth Drafts in wp-admin",
    ),
    Operation(
        id="draft_meta_ad",
        name="Draft Meta ad copy",
        category=Category.DRAFTING,
        min_phase=Phase.DRAFTS,
        environments=("staging",),
        approval=Approval.HUMAN_REVIEW_OF_OUTPUT,
        tool="draft_meta_ad",
        preconditions=("staging profile with writes enabled",),
        enforced_by=(_GATE, _PROFILE_CAP, _CONNECTOR_AUTH),
        rollback_description="stored as an inert Growth Draft asset; delete to undo; no ad "
                             "platform is ever touched",
        verification_description="asset reviewable under Growth Drafts in wp-admin",
    ),
    Operation(
        id="draft_gbp_post",
        name="Draft Google Business Profile post",
        category=Category.DRAFTING,
        min_phase=Phase.DRAFTS,
        environments=("staging",),
        approval=Approval.HUMAN_REVIEW_OF_OUTPUT,
        tool="draft_gbp_post",
        preconditions=("staging profile with writes enabled",),
        enforced_by=(_GATE, _PROFILE_CAP, _CONNECTOR_AUTH),
        rollback_description="stored as an inert Growth Draft asset; delete to undo; "
                             "nothing publishes to GBP",
        verification_description="asset reviewable under Growth Drafts in wp-admin",
    ),
    Operation(
        id="publish_seo_draft",
        name="Apply approved SEO draft to source page",
        category=Category.EXECUTION,
        min_phase=Phase.CONTROLLED_EXECUTION,
        environments=("staging",),
        approval=Approval.ALWAYS_ASK,
        tool="publish_seo_draft",
        preconditions=("draft exists and a human marked it approved in WordPress",
                       "per-call human confirmation available (never in scheduled runs)"),
        enforced_by=(_GATE, _PROFILE_CAP, "ALWAYS_ASK confirmation hook in the runtimes",
                     "connector refuses unapproved drafts (403)", _CONNECTOR_AUTH),
        rollback_description="previous title/slug/meta recoverable from the draft post and "
                             "WP revisions; re-apply by hand. KNOWN GAP (R9): no automated "
                             "compensation if the apply partially fails — closes with the "
                             "1.1 execution ledger",
        verification_description="re-read the source page via wp_seo_audit and compare "
                                 "stored postmeta (raw SQL on staging; rendered output is "
                                 "NOT evidence there — SITE_PROFILE rule #7)",
    ),
    Operation(
        id="refresh_site_snapshot",
        name="Refresh site-structure snapshot",
        category=Category.INTELLIGENCE,
        min_phase=Phase.READ_ONLY,
        environments=("staging", "production"),
        approval=Approval.NONE,
        tool="site_snapshot_refresh",
        preconditions=("connector /site-structure endpoint reachable", "store initialized"),
        enforced_by=(_GATE, _CONNECTOR_AUTH),
        rollback_description="writes only to the platform's own store (append-only with "
                             "retention); prior snapshots remain for diffing",
        verification_description="snapshot totals-consistency checks; diff vs predecessor "
                                 "and approved-expectation violations reported in the digest",
    ),
    Operation(
        id="query_site_map",
        name="Query the site map",
        category=Category.INTELLIGENCE,
        min_phase=Phase.READ_ONLY,
        environments=("staging", "production"),
        approval=Approval.NONE,
        tool="site_map_query",
        preconditions=("at least one stored snapshot",),
        enforced_by=(_GATE,),
        rollback_description=_READ_ROLLBACK,
        verification_description="results carry snapshot id + taken_at for provenance",
    ),
    Operation(
        id="read_source_file",
        name="Read a source file (governed)",
        category=Category.DIAGNOSTICS,
        min_phase=Phase.READ_ONLY,
        environments=("staging", "production"),
        approval=Approval.NONE,
        tool="source_read",
        preconditions=("path inside TC_SOURCE_ROOTS allowlist", "within per-run read budget"),
        enforced_by=(_GATE, "source-reader allowlist/deny-list + TOCTOU-safe open",
                     "per-(run, profile) budgets", "metadata-only audit JSONL"),
        rollback_description=_READ_ROLLBACK,
        verification_description="dual hashes (content_sha256/returned_sha256) bind cited "
                                 "evidence to file content",
    ),
    Operation(
        id="list_source_dir",
        name="List a source directory (governed)",
        category=Category.DIAGNOSTICS,
        min_phase=Phase.READ_ONLY,
        environments=("staging", "production"),
        approval=Approval.NONE,
        tool="source_list",
        preconditions=("path inside TC_SOURCE_ROOTS allowlist",),
        enforced_by=(_GATE, "source-reader allowlist + listing redaction of leak-prone names"),
        rollback_description=_READ_ROLLBACK,
        verification_description="listing is redacted metadata only; audit JSONL records "
                                 "the access",
    ),
)


class RegistryError(ValueError):
    """The action registry contradicts itself or the enforcement layer."""


def validate_registry(ops: tuple[Operation, ...] = OPERATIONS) -> None:
    """Fail loudly if the catalogue drifts from reality. Called by tests and list-operations.

    Checks BOTH internal coherence (unique ids, sane fields) and agreement with the
    enforcement layer — a registry entry whose phase/approval contradicts core.approval
    is a lie about the platform and must not survive CI.
    """
    seen: set[str] = set()
    for op in ops:
        if op.id in seen:
            raise RegistryError(f"duplicate operation id: {op.id}")
        seen.add(op.id)
        if not op.id.replace("_", "").isalnum() or op.id != op.id.lower():
            raise RegistryError(f"operation id must be lower_snake_case: {op.id}")
        if op.tool is None and op.command is None:
            raise RegistryError(f"{op.id}: not callable — needs a tool or command binding")
        if not op.verification_description:
            raise RegistryError(f"{op.id}: verification_description is required")
        if op.min_phase > Phase.READ_ONLY:
            if not op.rollback_description:
                raise RegistryError(f"{op.id}: write-capable operations require a "
                                    "rollback_description")
            if op.environments != ("staging",):
                raise RegistryError(f"{op.id}: write-capable operations may only target "
                                    "staging (profile write cap is the production reality)")
        if op.tool is not None:
            gate_phase = TOOL_MIN_PHASE.get(op.tool)
            if gate_phase is None:
                raise RegistryError(f"{op.id}: tool '{op.tool}' is not in TOOL_MIN_PHASE — "
                                    "entry describes a tool the gate does not know")
            if gate_phase != op.min_phase:
                raise RegistryError(f"{op.id}: min_phase {op.min_phase!r} disagrees with "
                                    f"TOOL_MIN_PHASE[{op.tool!r}] = {gate_phase!r}")
            if (op.approval is Approval.ALWAYS_ASK) != (op.tool in ALWAYS_ASK):
                raise RegistryError(f"{op.id}: approval class disagrees with ALWAYS_ASK "
                                    f"membership of tool '{op.tool}'")


def get_operation(op_id: str) -> Operation:
    for op in OPERATIONS:
        if op.id == op_id:
            return op
    raise KeyError(op_id)
