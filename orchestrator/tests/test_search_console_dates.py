"""Search Console date normalisation — accepts GA4-style relative dates and absolute dates."""

from __future__ import annotations

import datetime as dt

import pytest

from tc_growth.tools.base import ToolError
from tc_growth.tools.search_console import _resolve_date

_REF = dt.date(2026, 6, 30)  # fixed "today" for deterministic assertions


def test_absolute_date_passes_through():
    assert _resolve_date("2026-06-01", today=_REF) == "2026-06-01"


def test_today_and_yesterday():
    assert _resolve_date("today", today=_REF) == "2026-06-30"
    assert _resolve_date("yesterday", today=_REF) == "2026-06-29"


def test_relative_days_ago():
    assert _resolve_date("28daysAgo", today=_REF) == "2026-06-02"
    assert _resolve_date("0daysAgo", today=_REF) == "2026-06-30"


def test_invalid_date_raises_toolerror():
    with pytest.raises(ToolError):
        _resolve_date("last week", today=_REF)
