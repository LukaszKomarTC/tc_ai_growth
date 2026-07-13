"""Report delivery: routes to the configured channel and never raises when unconfigured."""

from __future__ import annotations

import tc_growth.report as report
from tc_growth.config import Settings


def test_deliver_routes_to_telegram(monkeypatch):
    called = {}
    monkeypatch.setattr(report, "get_settings", lambda: Settings(report_channel="telegram"))
    monkeypatch.setattr(report, "_deliver_telegram", lambda r: called.setdefault("telegram", r))
    monkeypatch.setattr(report, "send_email", lambda s, b, **k: called.setdefault("email", (s, b)))
    report.deliver("hello")
    assert called == {"telegram": "hello"}


def test_deliver_routes_to_email_by_default(monkeypatch):
    called = {}
    monkeypatch.setattr(report, "get_settings", lambda: Settings(report_channel="email"))
    monkeypatch.setattr(report, "_deliver_telegram", lambda r: called.setdefault("telegram", r))
    monkeypatch.setattr(report, "send_email", lambda s, b, **k: called.setdefault("email", (s, b)))
    report.deliver("hi")
    assert called == {"email": ("Tossa Cycling — Growth Report", "hi")}


def test_deliver_validation_prefixes_subject(monkeypatch):
    # Manual validation runs must be unmistakable in the inbox (review 2026-07-13).
    called = {}
    monkeypatch.setattr(report, "get_settings", lambda: Settings(report_channel="email"))
    monkeypatch.setattr(report, "send_email", lambda s, b, **k: called.setdefault("email", (s, b)))
    report.deliver("hi", validation=True)
    assert called["email"][0] == "[MANUAL VALIDATION] Tossa Cycling — Growth Report"


def test_email_unconfigured_does_not_raise(monkeypatch, capsys):
    # No SMTP host -> stdout fallback, no exception.
    monkeypatch.setattr(report, "get_settings", lambda: Settings(smtp_host="", report_recipient="x@y.z"))
    report.send_email("subj", "the report", raise_on_error=False)
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
    report.send_email("subj", "the report", raise_on_error=False)  # must not raise
    assert "delivery failed" in capsys.readouterr().out


def test_send_email_raise_on_error_surfaces_misconfig(monkeypatch):
    # The test-email path must fail loudly, not silently fall back to stdout.
    import pytest

    monkeypatch.setattr(report, "get_settings", lambda: Settings(smtp_host="", report_recipient="x@y.z"))
    with pytest.raises(RuntimeError):
        report.send_email("subj", "body", raise_on_error=True)


def test_persist_run_swallows_store_errors(monkeypatch, capsys):
    # Run-logging must never break a report: a broken/read-only store is caught and noted.
    from tc_growth.runtime.base import RuntimeResult

    def boom(*a, **k):
        raise RuntimeError("no db")

    monkeypatch.setattr("tc_growth.store.open_store", boom)
    report.persist_run(
        "weekly-report",
        RuntimeResult(text="Line one\nmore", model="claude-opus-4-8", prompt_tokens=10, completion_tokens=5),
        started_at="2026-07-05T00:00:00+00:00",
        duration_s=1.0,
    )  # must not raise
    assert "run not logged" in capsys.readouterr().out


def test_send_email_success_returns_true(monkeypatch):
    # A working SMTP path returns True (fake transport, no network).
    monkeypatch.setattr(
        report, "get_settings",
        lambda: Settings(smtp_host="smtp.example.com", report_recipient="x@y.z", smtp_starttls=False),
    )

    class _FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            pass

    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    assert report.send_email("subj", "body", raise_on_error=True) is True
