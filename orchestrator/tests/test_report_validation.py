"""Weekly-report artifact validation (born from VPS manual run #19, 2026-07-31).

Run #19 finished 'ok' having emailed only "Good — all the data I need is in. Now I'll file the
weekly case notes… before writing the report." — the agent ended its turn with a planning
sentence and the pipeline accepted narration as a finished report. `validate_report_artifact`
fail-closes that: a run may EXECUTE and still be judged an invalid artifact.

Corpus note: the platform does not persist report bodies (only summaries), so the ACCEPT fixtures
below are realistic reconstructions of the four-section structure the coordinator produces, with
deliberate heading-format variation. When a real Monday report lands, capture 1–2 verbatim into
this corpus — a durable regression set beats reconstructions.
"""

from __future__ import annotations

from tc_growth.report import validate_report_artifact

# The exact artifact run #19 emailed (the whole "report").
RUN_19 = ("Good — all the data I need is in. Now I'll file the weekly case notes for both "
          "monitoring cases before writing the report.")

_HEADER = ("# Tossa Cycling — Growth Report (2026-07-31)\n"
           "**Profile:** Tossa Cycling · PRODUCTION · **Analytics source:** production GSC/GA4 "
           "(read-only) · **WP/Woo connector:** staging\n\n")

# ACCEPT corpus — genuine-shaped reports with format variation.
_GOOD_STANDARD = _HEADER + (
    "## SEO Opportunities\n"
    "- /road-bike-rental: 1,240 impressions, CTR 1.1%, position 8.3 — title test to the booking hub.\n"
    "- /es/alquiler-bicicletas: position 12, rising; add internal links from the blog.\n\n"
    "## Ads Efficiency\n"
    "- Google 'bike rental girona': €142 spend, 6 conversions (€23.7 CPA) — best performer.\n"
    "- Meta prospecting: €58 spend, 0 conversions — pause, reallocate to retargeting.\n\n"
    "## Revenue Insights\n"
    "- WooCommerce: 11 bookings / €1,940 in the window; organic drove 5, paid 4.\n"
    "- /tour-de-girona gets traffic but 0 bookings — check the enquiry path.\n\n"
    "## Recommended Actions\n"
    "1. Pause the Meta prospecting set (names the wasted-spend destination).\n"
    "2. Title test on /road-bike-rental pointing at the booking form.\n"
)
_GOOD_NUMBERED = _HEADER + (
    "## 1. SEO Opportunities\nImpressions up 8% w/w; three pages in position 5–10 to test.\n\n"
    "## 2. Ads Efficiency\nGoogle Ads spend €210, 9 conversions; one campaign at €0 conversions "
    "flagged.\n\n"
    "## 3. Revenue Insights\n14 WooCommerce orders; booking conversion 2.1%.\n\n"
    "## 4. Recommended Actions\nPrioritise the enquiry-path fix on the tour landing page.\n"
)
_GOOD_TERSE_BLOCKED = _HEADER + (
    "## SEO Opportunities\nSearch Console: 3 pages at position 5–20; details below.\n\n"
    "## Ads Efficiency\nPending integrations — Google Ads and Meta connectors unavailable this run.\n\n"
    "## Revenue Insights\nWooCommerce: 4 bookings this week; conversion path healthy.\n\n"
    "## Recommended Actions\nNo urgent action; revisit ads once connectors are restored.\n"
)


def test_run19_preamble_is_rejected():
    ok, reason = validate_report_artifact(RUN_19)
    assert ok is False
    assert reason.startswith("incomplete_report_artifact")
    # …and still rejected once the platform header is prepended (the emailed body form).
    ok2, _ = validate_report_artifact(_HEADER + RUN_19)
    assert ok2 is False


def test_narration_that_mentions_sections_is_still_rejected():
    # Mentions SEO/Ads/Revenue/Recommend but is planning, not a report (no structure).
    narration = (_HEADER + "I have all the data I need. Next, I'll write the SEO Opportunities, "
                 "Ads Efficiency, Revenue Insights and Recommended Actions sections now.")
    ok, reason = validate_report_artifact(narration)
    assert ok is False
    assert "narration" in reason or "missing" in reason


def test_empty_and_tiny_outputs_are_rejected():
    for bad in ("", "   ", "# Weekly Report\nAll currently available sources collected."):
        ok, _ = validate_report_artifact(bad)
        assert ok is False


def test_genuine_reports_are_accepted_across_heading_formats():
    for good in (_GOOD_STANDARD, _GOOD_NUMBERED, _GOOD_TERSE_BLOCKED):
        ok, reason = validate_report_artifact(good)
        assert ok is True, f"valid report rejected ({reason}): {good[:60]!r}"


def test_a_report_missing_most_sections_is_rejected():
    # Only an SEO section, long enough to clear the length floor — a real report covers most of
    # the four concepts, so one section alone must be rejected on coverage, not just length.
    partial = _HEADER + (
        "## SEO Opportunities\n"
        "- /road-bike-rental: impressions up 8% week on week, three pages sitting in position "
        "five to ten that would repay a title and meta test pointed at the booking hub.\n"
        "- Internal-linking gaps on the Spanish-language pages are suppressing organic reach.\n"
    )
    assert len(partial) > 250
    ok, reason = validate_report_artifact(partial)
    assert ok is False
    assert "missing_sections" in reason


def test_genuine_run20_report_is_accepted():
    """The first captured REAL report body (accelerated validation run #20, 2026-08-01, graded
    PASS by the owner) — the verbatim-structure fixture the review required before the validator
    may deploy. Whitespace reconstructed from the email paste; content unaltered.

    Recorded lint debt (not this validator): run #20's platform lint flagged robots.txt advice
    that was CORRECT — the negation exemption matches the literal " not " with surrounding
    spaces, so the table row's "(NOT robots.txt)" slipped past it. Fix is a word-boundary match
    (\\bnot\\b) in report._lint_report's negation check, to be made alongside this branch's
    deployment round, never mid-validation."""
    import pathlib

    body = (pathlib.Path(__file__).parent / "fixtures" / "weekly_report_run20.md").read_text(
        encoding="utf-8")
    assert len(body) > 5000              # a real report, not a stub
    ok, reason = validate_report_artifact(body)
    assert ok is True, f"validator rejected the owner-graded PASS report: {reason}"
