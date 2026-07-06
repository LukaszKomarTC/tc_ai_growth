"""Phase 3A polish: run summaries, decision approvals, decision queue in memory, confidence trail."""

from __future__ import annotations

import pytest

from tc_growth import store
from tc_growth.dashboard import confidence_trail, render_case
from tc_growth.memory import known_cases_block
from tc_growth.report import _first_line


def test_summary_prefers_heading_over_preamble():
    text = ("All data gathered. Now writing the final synthesis.\n\n---\n\n"
            "# Tossa Cycling — Weekly Growth Report\nbody...")
    assert _first_line(text) == "Tossa Cycling — Weekly Growth Report"
    # No heading -> falls back to the first non-empty line.
    assert _first_line("plain text first\nmore") == "plain text first"


def test_decision_approve_reject_round_trip():
    s = store.open_store(":memory:")
    cid = s.create_case(title="c", ref="C-1")
    did = s.record_decision(title="Serve 410 on doorway URLs", status="proposed",
                            made_by="agent", case_id=cid)
    s.update_decision(did, status="approved")
    assert s.get_decision(did).status == "approved"
    with pytest.raises(ValueError):
        s.update_decision(did, made_by="hacker")     # provenance is not rewritable
    s.close()


def test_cli_decision_approve_journals_the_case(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TC_DB_PATH", str(tmp_path / "a.db"))
    s = store.open_store(tmp_path / "a.db")
    cid = s.create_case(title="c", ref="C-2")
    did = s.record_decision(title="Fix tracking", status="proposed", made_by="agent", case_id=cid)
    s.close()

    from tc_growth.cli import cmd_decision_set

    assert cmd_decision_set(str(did), "approved", "go ahead") == 0
    out = capsys.readouterr().out
    assert "proposed -> approved" in out

    s = store.open_store(tmp_path / "a.db")
    assert s.get_decision(did).status == "approved"
    case = s.get_case(cid)
    assert "approved by human" in case.body and "go ahead" in case.body
    assert "(human)" in case.body
    s.close()


def test_memory_block_includes_decision_queue_with_statuses():
    s = store.open_store(":memory:")
    cid = s.create_case(title="Tracking gap", ref="TRK-1", status="open")
    s.record_decision(title="Fix GA4 purchase event", status="proposed", made_by="agent", case_id=cid)
    d2 = s.record_decision(title="Serve 410", status="proposed", made_by="agent", case_id=cid)
    s.update_decision(d2, status="rejected")
    block = known_cases_block(s)
    assert "Decision queue" in block
    assert "[proposed] Fix GA4 purchase event (case TRK-1)" in block
    assert "[rejected] Serve 410" in block
    assert "do not re-propose" in block
    s.close()


def test_confidence_trail_parses_journal_and_renders():
    s = store.open_store(":memory:")
    cid = s.create_case(title="c", ref="C-3", confidence="0.41")
    s.update_case(cid, confidence="0.63")
    s.append_observation(cid, "Confidence 0.41 -> 0.63. Basis: first clean check", author="agent")
    s.update_case(cid, confidence="0.94")
    s.append_observation(cid, "Confidence 0.63 -> 0.94. Basis: Googlebot fetch 404", author="agent")

    case = s.get_case(cid)
    trail = confidence_trail(case.body)
    assert [t["to"] for t in trail] == ["0.63", "0.94"]
    assert trail[0]["basis"] == "first clean check"
    assert trail[1]["author"] == "agent"

    page = render_case(s, "C-3")
    assert "Confidence evolution" in page
    assert "0.41" in page and "0.94" in page and "Googlebot fetch 404" in page
    s.close()


def test_confidence_trail_empty_when_no_journal_lines():
    assert confidence_trail(None) == []
    assert confidence_trail("no confidence lines here") == []


def test_decision_outcome_records_execution_and_journals_case(tmp_path, monkeypatch, capsys):
    from tc_growth.cli import cmd_decision_outcome

    monkeypatch.setenv("TC_DB_PATH", str(tmp_path / "o.db"))
    s = store.open_store(tmp_path / "o.db")
    cid = s.create_case(title="tracking gap", ref="TRK-X")
    did = s.record_decision(title="Fix GA4", status="approved", made_by="agent", case_id=cid)
    s.close()

    assert cmd_decision_outcome(str(did), "banana") == 1          # only worked|failed
    assert cmd_decision_outcome(str(did), "worked", "GA4 DebugView shows purchase") == 0
    assert "outcome = worked" in capsys.readouterr().out

    s = store.open_store(tmp_path / "o.db")
    d = s.get_decision(did)
    assert d.outcome == "worked" and d.status == "approved"       # status untouched
    assert "executed and verified: worked" in s.get_case(cid).body
    assert "GA4 DebugView" in s.get_case(cid).body
    # The memory block now tells future runs it was executed, not merely approved.
    assert "[approved · executed: worked] Fix GA4 (case TRK-X)" in known_cases_block(s)
    s.close()
