"""WP-06 slice 3: lifecycle classifier — the evidence ladder under test with REAL site slugs.

The two historical failures this module exists to prevent:
- run #1: CTR-optimising an expired event (lifecycle blindness -> now tier-3 content dates);
- the reviewer's warning: a page must never be "past" merely because ONE date field is old
  while other evidence disagrees (-> conflict discipline: mixed evidence = unknown).
"""

from __future__ import annotations

import datetime as dt

from tc_growth.core.lifecycle import APPROVED_RULES, classify_lifecycle

TODAY = dt.date(2026, 7, 20)


def _item(slug, type_="page", title="", url=""):
    return {"id": 1, "slug": slug, "type": type_, "title": title,
            "url": url or f"https://x/{slug}/"}


# --- Tier 1: approved rules win over everything -------------------------------------------

def test_tdg_hub_is_evergreen_by_approved_rule_despite_dates_in_content():
    item = _item("tour_de_girona-listado", title="Tour de Girona 2026")
    v = classify_lifecycle(item, today=TODAY)
    assert v["state"] == "evergreen" and v["tier"] == "approved-rule" and v["confidence"] == "high"


# --- Tier 2: structured fields beat content dates -----------------------------------------

def test_structured_status_wins_over_old_slug_date():
    """A future edition can reuse a dated page: explicit status must override the old date."""
    item = _item("tour-de-girona-2025-road-s1", type_="events")
    v = classify_lifecycle(item, today=TODAY, structured={"status": "upcoming"})
    assert v["state"] == "upcoming" and v["tier"] == "structured"


def test_structured_event_date_classifies_with_high_confidence():
    item = _item("some-event", type_="events")
    v = classify_lifecycle(item, today=TODAY, structured={"start_date": dt.date(2026, 9, 1)})
    assert v["state"] == "upcoming" and v["tier"] == "structured" and v["confidence"] == "high"


# --- Tier 3: content dates, on the real slugs from the June/July reports ------------------

def test_real_emtb_slug_full_date_classifies_past():
    item = _item("emtb-tour-salida-guiada-facil-2026-24-06-2026", type_="events")
    v = classify_lifecycle(item, today=TODAY)
    assert v["state"] == "past" and v["tier"] == "content-date"
    assert "verify no future edition" in v["basis"]  # calibrated, not cocksure


def test_future_full_date_classifies_upcoming():
    item = _item("gravel-o2-2026-15-09-2026", type_="events")
    v = classify_lifecycle(item, today=TODAY)
    assert v["state"] == "upcoming" and v["confidence"] == "high"


def test_year_only_slug_is_uncertain_never_confident():
    """tour-de-girona-2026-road-s1 carries only a year: within 2026 we cannot place it."""
    v = classify_lifecycle(_item("tour-de-girona-2026-road-s1", type_="events"), today=TODAY)
    assert v["state"] == "unknown" and v["confidence"] == "low"


def test_conflicting_dates_never_resolve_silently():
    item = _item("event-24-06-2026-and-24-09-2026", type_="events")
    v = classify_lifecycle(item, today=TODAY)
    assert v["state"] == "unknown" and "conflicting" in v["basis"]


def test_impossible_dates_are_ignored_not_guessed():
    v = classify_lifecycle(_item("promo-99-99-2026", type_="events"), today=TODAY)
    # 99-99-2026 parses as nothing; bare year 2026 remains -> uncertain, not a crash or a guess.
    assert v["state"] == "unknown" and v["confidence"] == "low"


# --- Tier 4: fallbacks are explicit about being inferences --------------------------------

def test_undated_page_falls_back_to_likely_evergreen_low_confidence():
    """Reviewer caution adopted: an inference must not wear the same label as an approved
    rule — expired campaigns and abandoned landing pages are also 'undated pages'."""
    v = classify_lifecycle(_item("alquiler_bicicletas"), today=TODAY)
    assert v["state"] == "likely_evergreen" and v["tier"] == "inference" and v["confidence"] == "low"


def test_undated_event_and_product_stay_unknown_not_guessed():
    for t in ("events", "product"):
        v = classify_lifecycle(_item("something", type_=t), today=TODAY)
        assert v["state"] == "unknown" and v["tier"] == "inference" and v["confidence"] == "low"


def test_approved_rules_are_the_only_hardcoded_knowledge():
    """Guard the ladder's shape: every rule row is slug- or type-scoped and carries a why."""
    for rule in APPROVED_RULES:
        assert ("slug" in rule) or ("type" in rule)
        assert "why" in rule
        # Governance provenance (reviewer requirement): who approved it, when, for which site.
        assert rule.get("source") and rule.get("approved") and rule.get("scope")
        assert ("state" in rule) != ("policy" in rule)  # exactly one of the two
