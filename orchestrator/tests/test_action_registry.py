"""Action Registry invariants (Evidence Platform spec §5a).

The registry's whole value is that it describes REALITY — these tests are the mechanism
that makes drift from the enforcement layer a CI failure instead of stale documentation.
"""

from __future__ import annotations

import pytest

from tc_growth.core.actions import (
    OPERATIONS,
    Approval,
    Operation,
    Category,
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
    for op in OPERATIONS:
        if op.min_phase > Phase.READ_ONLY:
            assert op.environments == ("staging",), op.id
            assert op.rollback_description, op.id


def test_the_only_execution_category_operation_is_publish_seo_draft():
    """EXECUTION = changes external state. Today exactly one such operation exists; a
    second one appearing here must be a deliberate, reviewed event."""
    execution = [op.id for op in OPERATIONS if op.category is Category.EXECUTION]
    assert execution == ["publish_seo_draft"]


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


def test_get_operation_roundtrip_and_missing():
    assert get_operation("publish_seo_draft").approval is Approval.ALWAYS_ASK
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
