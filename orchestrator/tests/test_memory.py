"""Slice 3: the coordinator consults case memory before writing."""

from __future__ import annotations

from tc_growth import store
from tc_growth.core.approval import Phase
from tc_growth.memory import known_cases_block
from tc_growth.runtime.base import RuntimeResult


def test_known_cases_block_lists_cases_with_ref_and_status():
    s = store.open_store(":memory:")
    s.seed_incident_case()
    block = known_cases_block(s)
    assert "Known cases" in block
    assert store.INCIDENT_REF in block          # INC-2026-02-01 is referenceable
    assert "resolved" in block
    assert "Merchant Center" in block


def test_known_cases_block_empty_when_no_cases():
    assert known_cases_block(store.open_store(":memory:")) == ""


def test_known_cases_block_orders_open_before_resolved():
    s = store.open_store(":memory:")
    s.create_case(ref="R-1", title="resolved one", status="resolved")
    s.create_case(ref="O-1", title="open one", status="open")
    block = known_cases_block(s)
    assert block.index("O-1") < block.index("R-1")


def test_known_cases_block_is_resilient_when_store_unavailable(monkeypatch):
    # If the store can't be opened, memory degrades to empty — never raises.
    monkeypatch.setattr("tc_growth.store.open_store", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no db")))
    assert known_cases_block() == ""


class _CapturingRuntime:
    """Captures the task it was handed, returns a trivial result."""

    def __init__(self):
        self.task = None

    def run(self, *, system, task, tools, phase, model=None, max_iterations=12):
        self.task = task
        return RuntimeResult(text="ok", model=model, prompt_tokens=1, completion_tokens=1)


def test_weekly_report_injects_memory_into_task(monkeypatch):
    from tc_growth import report

    monkeypatch.setattr(report, "known_cases_block", lambda: "## Known cases\n- INC-2026-02-01 …")
    rt = _CapturingRuntime()
    report.build_weekly_report(rt, phase=Phase.READ_ONLY, persist=False)
    assert "Known cases" in rt.task
    assert "INC-2026-02-01" in rt.task
    # The original task instructions are still present.
    assert "SEO opportunities" in rt.task or "Search Console" in rt.task
