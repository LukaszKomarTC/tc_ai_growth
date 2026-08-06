"""Action Registry invariants (Evidence Platform spec §5a).

The registry's whole value is that it describes REALITY — these tests are the mechanism
that makes drift from the enforcement layer a CI failure instead of stale documentation.
"""

from __future__ import annotations

import pytest

from tc_growth.core.actions import (
    OPERATIONS,
    Approval,
    Category,
    Operation,
    RegistryError,
    get_operation,
    validate_registry,
)
from tc_growth.core.approval import ALWAYS_ASK, TOOL_MIN_PHASE, Phase
from tc_growth.tools.load import load_all


def test_registry_validates():
    validate_registry()


def test_every_tool_binding_names_a_registered_tool():
    """An entry bound to a tool that isn't registered describes something not callable."""
    registered = {t.name for t in load_all().all()}
    for op in OPERATIONS:
        if op.tool is not None:
            assert op.tool in registered, f"{op.id}: tool '{op.tool}' is not registered"


def test_tool_bound_entries_agree_with_the_phase_gate():
    for op in OPERATIONS:
        if op.tool is not None:
            assert TOOL_MIN_PHASE[op.tool] == op.min_phase, op.id
            assert (op.approval is Approval.ALWAYS_ASK) == (op.tool in ALWAYS_ASK), op.id


def test_write_operations_target_staging_only_and_document_rollback():
    """The staging-only cap is about the CUSTOMER'S SITE. A platform-surface operation (WP-U4d
    deployment) writes this platform's own host and provably never the site, so it is held to
    its own boundary instead — and, being write-capable, it must still document rollback and
    must not be offered until it has been proven (enabled=False)."""
    for op in OPERATIONS:
        if op.min_phase > Phase.READ_ONLY:
            assert op.rollback_description, op.id
            if op.target_surface == "site":
                assert op.environments == ("staging",), op.id
            else:
                assert op.target_surface == "platform", op.id
                assert op.category is Category.PLATFORM, op.id
                # The "staging proof before first production use" rule (#77) binds PRODUCTION-
                # writing operations: they must not be enabled until proven. A disposable-only
                # operation that provably never touches production (deploy_acceptance) is the
                # mechanism of that proof and may be enabled.
                if op.production_write:
                    assert not op.enabled, (
                        f"{op.id}: a production-writing operation must not be enabled before its "
                        "acceptance — see #77")


def test_foundation_lists_only_accepted_operations():
    """Scenario-B foundation invariant: the executable registry describes CURRENT AUTHORITY, not
    a roadmap. It contains exactly the operations implemented and accepted (or riding the current
    increment's acceptance sheet) — and no write/execution operations at all (those arrive with
    their own capability + acceptance). Set extended DELIBERATELY per increment:
    U3b adds redeliver_latest_report (read-only re-send of a stored immutable artifact; accepted
    as part of the U3b in-browser acceptance, like SMTP/scan rode the MVP acceptance)."""
    assert {op.id for op in OPERATIONS if op.enabled} == {
        "smtp_test", "run_integrity_scan", "redeliver_latest_report", "deploy_acceptance"}
    assert [op.id for op in OPERATIONS if op.category is Category.EXECUTION] == []
    # The only enabled operation that is not read-only is deploy_acceptance — a disposable-only,
    # self-attesting op with its own dedicated surface (never on the generic operations page).
    for op in OPERATIONS:
        if op.enabled and op.min_phase is not Phase.READ_ONLY:
            assert op.id == "deploy_acceptance", op.id
            assert not op.production_write and not op.self_service, op.id
    # Anything present but NOT enabled is a reviewable definition, not authority. U4d's
    # deploy_release (production-writing) stays disabled until its on-host acceptance proof.
    assert {op.id for op in OPERATIONS if not op.enabled} == {"deploy_release"}


def test_the_two_platform_operations_are_distinguished_and_release_stays_disabled():
    """Criterion 2 of the head-76a9fd3 review: the distinction between the production deployer and
    the disposable acceptance is pinned, and enabling a production-writing op is refused."""
    rel = get_operation("deploy_release")
    acc = get_operation("deploy_acceptance")
    assert rel.production_write and not rel.enabled and not rel.self_service
    assert not acc.production_write and acc.enabled and not acc.self_service
    # validate_registry machine-enforces "a production-writing op must stay disabled".
    tampered = tuple(
        Operation(**{**op.__dict__, "enabled": True}) if op.id == "deploy_release" else op
        for op in OPERATIONS)
    with pytest.raises(RegistryError, match="production-writing"):
        validate_registry(tampered)


def test_duplicate_ids_rejected():
    dup = (OPERATIONS[0], OPERATIONS[0])
    with pytest.raises(RegistryError, match="duplicate"):
        validate_registry(dup)


def test_unbound_operation_rejected():
    orphan = Operation(
        id="floats_free",
        name="Not callable",
        category=Category.DIAGNOSTICS,
        min_phase=Phase.READ_ONLY,
        environments=("staging",),
        approval=Approval.NONE,
        verification_description="n/a",
    )
    with pytest.raises(RegistryError, match="not callable"):
        validate_registry((orphan,))


def test_phase_mismatch_rejected():
    liar = Operation(
        id="lying_entry",
        name="Claims wrong phase",
        category=Category.EXECUTION,
        min_phase=Phase.DRAFTS,  # gate says CONTROLLED_EXECUTION
        environments=("staging",),
        approval=Approval.ALWAYS_ASK,
        tool="publish_seo_draft",
        rollback_description="x",
        verification_description="x",
    )
    with pytest.raises(RegistryError, match="disagrees with"):
        validate_registry((liar,))


def test_result_policy_outcomes_must_be_known_vocabulary():
    """A result_policy that maps an exit code to an unknown outcome label is a lie the platform
    can't interpret — CI must reject it."""
    from tc_growth.core.actions import OUTCOME_SEVERITY

    bad = Operation(
        id="bad_policy", name="x", category=Category.DIAGNOSTICS, min_phase=Phase.READ_ONLY,
        environments=("staging",), approval=Approval.NONE, command="noop",
        result_policy=((0, "clean"), (2, "kaboom")),  # 'kaboom' is not a known outcome
        verification_description="x",
    )
    with pytest.raises(RegistryError, match="not one of"):
        validate_registry((bad,))
    assert "findings" in OUTCOME_SEVERITY  # the real integrity outcome is in the vocabulary


def test_result_policy_rejects_duplicate_exit_codes():
    dup = Operation(
        id="dup_codes", name="x", category=Category.DIAGNOSTICS, min_phase=Phase.READ_ONLY,
        environments=("staging",), approval=Approval.NONE, command="noop",
        result_policy=((0, "clean"), (0, "findings")),
        verification_description="x",
    )
    with pytest.raises(RegistryError, match="duplicate exit code"):
        validate_registry((dup,))


def test_integrity_scan_declares_findings_semantics():
    """The whole point of op #2's fix: exit 2 is a declared 'findings' outcome, not a failure."""
    op = get_operation("run_integrity_scan")
    assert dict(op.result_policy) == {0: "clean", 2: "findings"}


def test_get_operation_roundtrip_and_missing():
    assert get_operation("smtp_test").approval is Approval.NONE
    with pytest.raises(KeyError):
        get_operation("no_such_operation")


def test_registry_definitions_do_not_execute_anything():
    """Skeleton discipline: core/actions.py is declarative data + validation ONLY — no
    dispatch, no I/O, no store access. (Executions arrive with the 1.1 ledger.)"""
    import pathlib

    text = (pathlib.Path(__file__).resolve().parents[1]
            / "tc_growth" / "core" / "actions.py").read_text(encoding="utf-8")
    banned = ("dispatch(", "httpx", "open_store", "subprocess", "requests.")
    hits = [token for token in banned if token in text]
    assert not hits, f"action registry must stay declarative; found: {hits}"
