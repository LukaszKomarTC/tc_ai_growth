"""Slice 5: the agent writes to memory — schema v2, case tools, gating, provenance."""

from __future__ import annotations

import sqlite3

import pytest

from tc_growth import store
from tc_growth.core.approval import Phase, is_tool_allowed, needs_confirmation
from tc_growth.tools.load import load_all

_V1_SCHEMA = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
CREATE TABLE cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE, title TEXT NOT NULL, category TEXT,
    status TEXT NOT NULL DEFAULT 'open', priority TEXT NOT NULL DEFAULT 'medium', confidence TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, body TEXT);
CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
    kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ok', model TEXT, prompt_tokens INTEGER,
    completion_tokens INTEGER, cost_usd REAL, duration_s REAL, summary TEXT, detail TEXT,
    case_id INTEGER REFERENCES cases(id));
CREATE TABLE decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, made_at TEXT NOT NULL, title TEXT NOT NULL,
    rationale TEXT, status TEXT NOT NULL DEFAULT 'active', outcome TEXT,
    case_id INTEGER REFERENCES cases(id));
INSERT INTO schema_version (version) VALUES (1);
INSERT INTO cases (ref, title, status, priority, created_at, updated_at, body)
    VALUES ('INC-2026-02-01', 'v1 row', 'resolved', 'medium', '2026-07-05', '2026-07-05', 'old body');
"""


def test_v1_database_migrates_to_v2_preserving_rows(tmp_path):
    # Build a real v1 database (as it exists on the VPS), then connect() must migrate it.
    path = tmp_path / "v1.db"
    raw = sqlite3.connect(path)
    raw.executescript(_V1_SCHEMA)
    raw.commit()
    raw.close()

    s = store.open_store(path)
    case = s.get_case_by_ref("INC-2026-02-01")
    assert case is not None and case.body == "old body"     # data survived
    assert case.opened_by is None and case.closed_by is None  # new columns present, NULL
    s.update_case(case.id, closed_by="human")                # and writable
    assert s.get_case_by_ref("INC-2026-02-01").closed_by == "human"
    s.close()


def test_case_tools_registered_and_gated():
    names = {t.name for t in load_all().all()}
    case_tools = {"case_search", "case_open", "case_note", "case_set_confidence",
                  "case_set_status", "decision_log"}
    assert case_tools <= names
    # Memory writes are internal state -> allowed in READ_ONLY...
    for name in case_tools:
        assert is_tool_allowed(name, Phase.READ_ONLY)
    # ...but lifecycle transitions always need a human.
    assert needs_confirmation("case_set_status")
    assert not needs_confirmation("case_note")
    assert not needs_confirmation("case_set_confidence")


@pytest.fixture()
def tool_db(tmp_path, monkeypatch):
    """Point the case tools' open_store() at a seeded temp DB."""
    path = tmp_path / "tools.db"
    monkeypatch.setenv("TC_DB_PATH", str(path))
    s = store.open_store(path)
    s.seed_incident_case()
    s.close()
    return path


def test_case_open_refuses_likely_duplicate_then_creates_when_confirmed(tool_db):
    reg = load_all()
    # An open case to collide with.
    s = store.open_store(tool_db)
    s.create_case(title="Tobacco spam recurrence watch", status="monitoring", body="watching GSC")
    s.close()

    out = reg.dispatch("case_open", {"title": "Tobacco spam pages in GSC", "summary": "spam watch"})
    assert out["ok"] and out["result"]["created"] is False
    assert out["result"]["possible_duplicates"]

    out2 = reg.dispatch("case_open", {
        "title": "Tobacco spam pages in GSC", "summary": "genuinely distinct",
        "category": "seo", "confirmed_new": True, "confidence": 0.7,
    })
    assert out2["ok"] and out2["result"]["created"] is True
    ref = out2["result"]["ref"]
    assert ref.startswith("SEO-")
    s = store.open_store(tool_db)
    case = s.get_case_by_ref(ref)
    assert case.opened_by == "agent" and case.confidence == "0.7"
    s.close()


def test_case_note_and_confidence_journal_the_case(tool_db):
    reg = load_all()
    out = reg.dispatch("case_note", {"ref": store.INCIDENT_REF, "observation": "No recurrence this week."})
    assert out["ok"] and out["result"]["noted"]
    out = reg.dispatch("case_set_confidence", {"ref": store.INCIDENT_REF, "confidence": 0.96,
                                               "basis": "4th clean weekly check"})
    assert out["ok"] and out["result"]["confidence"]["to"] == "0.96"

    s = store.open_store(tool_db)
    case = s.get_case_by_ref(store.INCIDENT_REF)
    assert "No recurrence this week." in case.body
    assert "-> 0.96" in case.body and "4th clean weekly check" in case.body
    assert "(agent):" in case.body
    assert case.confidence == "0.96"
    s.close()


def test_case_set_status_records_agent_closure_and_reason(tool_db):
    # The tool itself works when dispatched (i.e. when a human confirmed the call).
    reg = load_all()
    out = reg.dispatch("case_set_status", {"ref": store.INCIDENT_REF, "status": "closed",
                                           "reason": "4 clean weeks"})
    assert out["ok"] and out["result"]["status"]["to"] == "closed"
    s = store.open_store(tool_db)
    case = s.get_case_by_ref(store.INCIDENT_REF)
    assert case.status == "closed" and case.closed_by == "agent"
    s.close()


def test_decision_log_records_proposal_linked_to_case(tool_db):
    reg = load_all()
    out = reg.dispatch("decision_log", {"title": "Keep spam URLs at 410",
                                        "rationale": "never 301", "case_ref": store.INCIDENT_REF})
    assert out["ok"] and out["result"]["status"] == "proposed"
    s = store.open_store(tool_db)
    d = s.list_decisions()[0]
    assert d.made_by == "agent" and d.status == "proposed" and d.case_id is not None
    s.close()


def test_unknown_ref_is_a_clean_tool_error(tool_db):
    out = load_all().dispatch("case_note", {"ref": "NOPE-1", "observation": "x"})
    assert out["ok"] is False and "No case matching" in out["error"]


def test_case_open_surfaces_resolved_matches_as_possible_recurrence(tool_db):
    # The seeded incident is RESOLVED. Opening a case about the same phenomenon must surface it —
    # a resolved match means "possible recurrence, read it first", not an invisible duplicate.
    # (This is the exact failure of the 2026-07-05 investigate run, encoded as a regression test.)
    out = load_all().dispatch("case_open", {
        "title": "Tobacco doorway pages in organic search",
        "summary": "tobacco spam URLs on tossacycling.com Merchant Center pattern",
    })
    assert out["ok"] and out["result"]["created"] is False
    refs = [d["ref"] for d in out["result"]["possible_duplicates"]]
    assert store.INCIDENT_REF in refs
    assert "case_read" in out["result"]["instruction"]


def test_case_read_returns_full_narrative_and_decisions(tool_db):
    reg = load_all()
    reg.dispatch("decision_log", {"title": "Keep 410", "case_ref": store.INCIDENT_REF})
    out = reg.dispatch("case_read", {"ref": store.INCIDENT_REF})
    assert out["ok"]
    r = out["result"]
    assert r["ref"] == store.INCIDENT_REF
    assert "Merchant Center" in r["narrative"]          # the full body, not a one-liner
    assert "Timeline" in r["narrative"]                 # depth the summary line omits
    assert r["decisions"] and r["decisions"][0]["title"] == "Keep 410"
    assert is_tool_allowed("case_read", Phase.READ_ONLY)


def test_find_cases_statuses_filter_and_default_all():
    s = store.open_store(":memory:")
    s.create_case(ref="R-9", title="tobacco resolved thing", status="resolved")
    s.create_case(ref="O-9", title="tobacco open thing", status="open")
    all_hits = {c.ref for c in s.find_cases("tobacco")}
    assert all_hits == {"R-9", "O-9"}                   # default: every status
    open_hits = {c.ref for c in s.find_open_cases("tobacco")}
    assert open_hits == {"O-9"}                         # restricted view still available
    s.close()
