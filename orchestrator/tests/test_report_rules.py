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


def test_rule5b_no_implied_transaction_match():
    c = _coordinator()
    assert '"not transaction-matched"' in c
    assert "never imply a match that was not programmatically performed" in c


# --- Rule 8 (2026-07-13 rerun review): noindex method + GA4-attribution-is-not-indexing ---

def test_rule8_noindex_never_via_robots_txt():
    c = _coordinator()
    assert "never recommend robots.txt as a noindex method" in c
    assert "meta robots tag or x-robots-tag" in c
    assert "investigation trigger, not proof the url is indexed" in c


def test_rule8_lint_flags_robots_txt_noindex_advice():
    rt = _FakeRuntime(text="Apply noindex via Yoast SEO or robots.txt to the order pages.")
    out = build_weekly_report(rt, persist=False)
    assert "Platform lint" in out
    assert "robots.txt CANNOT noindex" in out


def test_lint_silent_on_clean_reports():
    rt = _FakeRuntime()
    out = build_weekly_report(rt, persist=False)
    assert "Platform lint" not in out


# --- Deterministic dates (2026-07-13 rerun: model invented a future "Week of" date) ---

def test_dates_are_computed_and_injected_not_model_derived():
    import datetime as dt
    from zoneinfo import ZoneInfo

    from tc_growth.report import _report_dates

    run_date, window_start, window_end = _report_dates()
    today = dt.datetime.now(ZoneInfo("Europe/Madrid")).date()
    assert run_date == today.isoformat()
    assert window_end == run_date                              # window can never end in the future
    assert window_start == (today - dt.timedelta(days=28)).isoformat()
    # And the task the model receives carries them verbatim:
    rt = _FakeRuntime()
    build_weekly_report(rt, persist=False)
    # (task not captured by the fake; the header is) — the report header must use the computed date.
    out = build_weekly_report(rt, persist=False)
    assert run_date in out


# --- Manual-validation separation (ledger kind, header label) ---

def test_validation_run_is_labelled_and_ledgered_separately(monkeypatch):
    recorded = {}
    monkeypatch.setattr(
        "tc_growth.report.persist_run",
        lambda kind, result, *, started_at, duration_s: recorded.setdefault("kind", kind),
    )
    rt = _FakeRuntime()
    out = build_weekly_report(rt, persist=True, validation=True)
    assert recorded["kind"] == "weekly-report-validation"      # machine-distinguishable in the ledger
    assert "MANUAL VALIDATION" in out
    assert "does not count toward the acceptance gate" in out
    # A normal run carries neither the label nor the special kind.
    recorded.clear()
    out2 = build_weekly_report(rt, persist=True, validation=False)
    assert recorded["kind"] == "weekly-report"
    assert "MANUAL VALIDATION" not in out2


def test_header_states_data_provenance():
    rt = _FakeRuntime()
    out = build_weekly_report(rt, persist=False)
    assert "**Analytics source:** production GSC/GA4 (read-only)" in out
    assert "**WP/Woo connector:** staging" in out


def test_rule7_masking_is_enforced_mechanically():
    """The 2026-07-13 manual rerun proved the prompt rule alone is unreliable (the model printed
    order-pay/53385 and order-received/53717 verbatim) — so the pipeline masks, not the model."""
    rt = _FakeRuntime(
        text="Landing pages: /en/pedido/order-received/53717 (5 sessions) and "
             "/en/pedido/order-pay/53385 (6 sessions). Spam URL /Vape-Pod/735473 unaffected."
    )
    out = build_weekly_report(rt, persist=False)
    assert "53717" not in out
    assert "53385" not in out
    assert "/order-received/5xxxx" in out
    assert "/order-pay/5xxxx" in out
    assert "/Vape-Pod/735473" in out            # non-transactional URLs stay intact


# --- Approval gate remains intact around the report path (functional, not textual) ---

class _FakeRuntime:
    """Records the phase the weekly report actually runs with."""

    def __init__(self, text: str = "# Weekly Report\nAll currently available sources collected.") -> None:
        self.phase = None
        self.system = None
        self._text = text

    def run(self, *, system, task, tools, phase, model=None, max_iterations=12):
        self.phase = phase
        self.system = system
        return RuntimeResult(text=self._text)


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
