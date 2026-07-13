"""Regression fixtures for the seven report rules (scheduled run #1 external review, 2026-07-13).

Run #1 passed the operational gate but recommended CTR-optimising an EXPIRED Tour de Girona
edition, presented CTR heuristics as quantified facts, wrote "all data collected" while four
sources were unavailable, exposed order IDs, and (in follow-up analysis by both reviewers)
findings were promoted to causes without evidence. The rules live in the prompt text the weekly
report runs with, so each fixture pins its rule's key phrases — reword a rule only together with
its fixture: these phrases are encoded lessons, not decoration. The final tests prove the
approval gate around the report path functionally, not textually.
"""

from __future__ import annotations

from tc_growth import prompts
from tc_growth.core.approval import Phase, is_tool_allowed
from tc_growth.report import build_weekly_report
from tc_growth.runtime.base import RuntimeResult


def _norm(text: str) -> str:
    """Whitespace-normalized lowercase — prompt line-wrapping must not break a fixture."""
    return " ".join(text.split()).lower()


def _coordinator() -> str:
    return _norm(prompts.COORDINATOR)


# --- Rule 1: past event with high impressions -> no CTR optimisation; route to current hub ---

def test_rule1_past_events_are_historical_assets_not_ctr_targets():
    c = _coordinator()
    assert "commercial state before optimisation" in c
    assert "historical asset" in c
    assert "date has passed" in c
    assert "never recommend ctr/title optimisation" in c
    assert "current hub" in c                      # the required alternative recommendation
    assert "discontinued products follow the same rule" in c


# --- Rule 2: every content recommendation names its conversion destination ---

def test_rule2_recommendations_must_name_conversion_destination():
    c = _coordinator()
    assert "name the conversion destination" in c
    assert "booking, registration, or enquiry path" in c
    assert "only increases clicks is incomplete" in c


# --- Rule 3 (finding vs causation): missing hreflang is a finding, not a ranking cause ---

def test_rule3_findings_are_not_causes_in_both_prompts():
    cal = _norm(prompts.CALIBRATION)
    assert "findings are not causes" in cal
    assert "hreflang" in cal                       # the concrete example that produced the rule
    assert "ranking/revenue effect unproven" in cal
    # The rule must reach BOTH runners: growth coordinator and forensic investigator.
    assert "findings are not causes" in _coordinator()
    assert "findings are not causes" in _norm(prompts.INVESTIGATION)


# --- Rule 4: CTR benchmarks labelled as screening heuristics only ---

def test_rule4_ctr_benchmarks_are_screening_heuristics():
    c = _coordinator()
    assert "screening heuristics, not evidence" in c
    assert "inspect the query mix and serp" in c
    # The two overclaims from run #1, pinned as negative examples:
    assert "lost 15-25 clicks" in c
    assert "3x traffic" in c


# --- Rule 5: purchase reporting names event, count, transaction IDs, Woo matching ---

def test_rule5_purchase_reporting_specificity():
    c = _coordinator()
    assert "purchase reporting must be specific" in c
    assert "event name (purchase)" in c
    assert "unique transaction ids" in c
    assert "match woocommerce orders" in c
    assert 'bare word "conversions"' in c


# --- Rule 6: "all available sources" wording when integrations fail ---

def test_rule6_completeness_wording():
    c = _coordinator()
    assert 'never say "all data collected"' in c
    assert "all currently available sources collected" in c
    assert "enumerate the unavailable" in c


# --- Rule 7: masked order IDs and transactional URLs ---

def test_rule7_transactional_identifiers_masked():
    c = _coordinator()
    assert "mask transactional identifiers" in c
    assert "/order-received/5xxxx" in c


# --- Approval gate remains intact around the report path (functional, not textual) ---

class _FakeRuntime:
    """Records the phase the weekly report actually runs with."""

    def __init__(self) -> None:
        self.phase = None
        self.system = None

    def run(self, *, system, task, tools, phase, model=None, max_iterations=12):
        self.phase = phase
        self.system = system
        return RuntimeResult(text="# Weekly Report\nAll currently available sources collected.")


def test_weekly_report_runs_read_only_and_draft_tools_stay_gated(monkeypatch):
    # Pin the profile write cap open: this test isolates the PHASE gate specifically
    # (test_profiles covers the TC_ALLOW_WRITES cap, and its env-file loader leaks state).
    monkeypatch.setenv("TC_ALLOW_WRITES", "true")
    rt = _FakeRuntime()
    out = build_weekly_report(rt, persist=False)
    assert rt.phase == Phase.READ_ONLY                      # scheduled reports never gain write phase
    assert rt.system == prompts.COORDINATOR                 # the rules above are the prompt in force
    assert "Weekly Report" in out
    # The gate itself: draft tools are refused at the report's phase, admitted only at DRAFTS.
    for tool in ("wp_create_seo_draft", "wp_create_product_revision"):
        assert not is_tool_allowed(tool, Phase.READ_ONLY)
        assert is_tool_allowed(tool, Phase.DRAFTS)
