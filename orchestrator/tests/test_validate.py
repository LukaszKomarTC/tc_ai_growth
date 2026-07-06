"""Release 0.3 validation tooling: draft-test launcher + validation-report parser."""

from __future__ import annotations

from tc_growth.core.approval import Phase
from tc_growth.runtime.base import RuntimeResult
from tc_growth.validate import run_draft_test, validation_status

_CHECKLIST = """\
# Validation Checklist

Intro prose, no items.

## Content (drafts)

- [x] SEO draft — Spanish rental page — 2026-07-07, run #5, revision 41022
- [ ] Product revision — Scott Addict 50

## Memory

- [x] Does not reopen a resolved case — 2026-07-06 weekly report
- [x] Links decisions to cases — TRK-20260706-050158 / D#3

## Sign-off

- [ ] All boxes green
"""


def test_validation_status_parses_sections_and_percent(tmp_path):
    doc = tmp_path / "VALIDATION.md"
    doc.write_text(_CHECKLIST)
    st = validation_status(doc)
    names = [s["name"] for s in st["sections"]]
    assert names == ["Content (drafts)", "Memory", "Sign-off"]
    content = st["sections"][0]
    assert content["done"] == 1 and content["total"] == 2 and not content["pass"]
    memory = st["sections"][1]
    assert memory["pass"] is True
    assert st["done"] == 3 and st["total"] == 5 and st["percent"] == 60
    # Evidence text is preserved for display.
    assert "revision 41022" in content["items"][0]["text"]


def test_validation_status_missing_file_is_empty():
    st = validation_status("/nonexistent/VALIDATION.md")
    assert st == {"sections": [], "done": 0, "total": 0, "percent": 0}


class _CapturingRuntime:
    def __init__(self):
        self.phase = None
        self.task = None

    def run(self, *, system, task, tools, phase, model=None, max_iterations=12):
        self.phase = phase
        self.task = task
        return RuntimeResult(text="Draft created: revision 123", model=model,
                             prompt_tokens=1, completion_tokens=1)


def test_run_draft_test_runs_at_drafts_phase_and_frames_the_task():
    rt = _CapturingRuntime()
    out = run_draft_test(rt, "SEO title/meta draft for post 13699", persist=False)
    assert rt.phase == Phase.DRAFTS                    # the whole point of the launcher
    assert "NEVER publish" in rt.task
    assert "post 13699" in rt.task
    assert "Draft Test" in out and "revision 123" in out
    # Validation findings from the first live draft test (2026-07-06), encoded as rules:
    assert "Do NOT change the slug" in rt.task         # scope discipline (slug change was unasked)
    assert "MULTILINGUAL" in rt.task                   # ES/EN twins are one asset


def test_drafting_discipline_is_in_the_always_injected_safety_prompt():
    from tc_growth import prompts

    for text in (prompts.COORDINATOR, prompts.SEO_ROLE):
        assert "Change ONLY what the task asks" in text
        assert "language twin" in text


def test_decision_add_records_human_policy_and_enters_memory(tmp_path, monkeypatch, capsys):
    from tc_growth import store
    from tc_growth.cli import cmd_decision_add
    from tc_growth.memory import known_cases_block

    monkeypatch.setenv("TC_DB_PATH", str(tmp_path / "p.db"))
    s = store.open_store(tmp_path / "p.db")
    s.create_case(title="anchor case", ref="POL-1")   # memory block requires >=1 case
    s.close()

    rc = cmd_decision_add("Multilingual pages are drafted as pairs", "validation finding", "POL-1")
    assert rc == 0 and "approved, human" in capsys.readouterr().out

    s = store.open_store(tmp_path / "p.db")
    d = s.list_decisions()[0]
    assert d.status == "approved" and d.made_by == "human" and d.case_id is not None
    block = known_cases_block(s)
    assert "[approved] Multilingual pages are drafted as pairs (case POL-1)" in block
    s.close()


def test_dashboard_validation_page_renders(tmp_path, monkeypatch):
    import tc_growth.validate as validate
    from tc_growth.dashboard import render_validation

    doc = tmp_path / "VALIDATION.md"
    doc.write_text(_CHECKLIST)
    monkeypatch.setattr(validate, "VALIDATION_DOC", doc)
    page = render_validation()
    assert "Validation Report" in page
    assert "PASS" in page                              # the fully-green Memory section
    assert "1/2" in page                               # the partial Content section
    assert "60%" in page
    assert "NOT ENABLED" in page                       # production writes
