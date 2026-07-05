"""Search Console request-body builder — forensic page filter + date dimension."""

from __future__ import annotations

from tc_growth.tools.search_console import _build_body


def test_basic_body_has_no_filter():
    body = _build_body({"start_date": "2026-06-01", "end_date": "2026-06-27"})
    assert body["startDate"] == "2026-06-01"
    assert body["endDate"] == "2026-06-27"
    assert body["dimensions"] == ["query"]
    assert "dimensionFilterGroups" not in body


def test_page_filter_adds_contains_group():
    body = _build_body({
        "start_date": "480daysAgo",
        "end_date": "today",
        "dimensions": ["date"],
        "page_filter": "Marlboro",
        "row_limit": 500,
    })
    assert body["dimensions"] == ["date"]
    assert body["rowLimit"] == 500
    groups = body["dimensionFilterGroups"]
    assert groups == [{"filters": [{"dimension": "page", "operator": "contains", "expression": "Marlboro"}]}]


def test_relative_dates_are_resolved_in_body():
    # 480daysAgo / today are resolved to absolute YYYY-MM-DD (GSC rejects relative).
    body = _build_body({"start_date": "0daysAgo", "end_date": "today"})
    assert body["startDate"].count("-") == 2 and body["endDate"].count("-") == 2
