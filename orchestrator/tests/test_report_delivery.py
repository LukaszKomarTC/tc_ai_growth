"""Report delivery: routes to the configured channel and never raises when unconfigured."""

from __future__ import annotations

import tc_growth.report as report
from tc_growth.config import Settings


def test_deliver_routes_to_telegram(monkeypatch):
    called = {}
    monkeypatch.setattr(report, "get_settings", lambda: Settings(report_channel="telegram"))
    monkeypatch.setattr(report, "_deliver_telegram", lambda r: called.setdefault("telegram", r))
    monkeypatch.setattr(report, "_deliver_email", lambda r: called.setdefault("email", r))
    report.deliver("hello")
    assert called == {"telegram": "hello"}


def test_deliver_routes_to_email_by_default(monkeypatch):
    called = {}
    monkeypatch.setattr(report, "get_settings", lambda: Settings(report_channel="email"))
    monkeypatch.setattr(report, "_deliver_telegram", lambda r: called.setdefault("telegram", r))
    monkeypatch.setattr(report, "_deliver_email", lambda r: called.setdefault("email", r))
    report.deliver("hi")
    assert called == {"email": "hi"}


def test_email_unconfigured_does_not_raise(monkeypatch, capsys):
    # No SMTP host -> stdout fallback, no exception.
    monkeypatch.setattr(report, "get_settings", lambda: Settings(smtp_host="", report_recipient="x@y.z"))
    report._deliver_email("the report")
    assert "the report" in capsys.readouterr().out


def test_email_send_failure_does_not_raise(monkeypatch, capsys):
    # Configured host but SMTP raises -> caught, printed, never propagated.
    monkeypatch.setattr(
        report, "get_settings",
        lambda: Settings(smtp_host="smtp.invalid", report_recipient="x@y.z"),
    )

    def boom(*a, **k):
        raise OSError("connection refused")

    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", boom)
    report._deliver_email("the report")  # must not raise
    assert "delivery failed" in capsys.readouterr().out
