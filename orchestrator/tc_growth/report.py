"""Weekly opportunity report assembly and delivery (provider-neutral except the runtime call).

Produces a structured digest: SEO opportunities / Ads efficiency / Revenue insights /
recommended actions, and delivers it via email or Telegram.
"""

from __future__ import annotations

import datetime as dt
import time

from .config import get_settings, model_for
from .core.approval import Phase
from .memory import known_cases_block
from .prompts import COORDINATOR
from .runtime.base import AgentRuntime, RuntimeResult
from .tools.load import load_all


def _first_line(text: str, limit: int = 200) -> str:
    """Summary line for the run ledger. Models often emit preamble ("All data gathered...")
    before the actual report, so prefer the first markdown HEADING; fall back to first text."""
    lines = text.splitlines()
    for line in lines:
        s = line.strip()
        if s.startswith("#"):
            heading = s.lstrip("# ").strip()
            if heading:
                return heading[:limit]
    for line in lines:
        s = line.strip()
        if s:
            return s[:limit]
    return ""


def persist_run(kind: str, result: RuntimeResult, *, started_at: str, duration_s: float) -> None:
    """Log a completed agent run to the store. Best-effort: a persistence problem (missing/RO DB)
    must NEVER break the report or investigation, so every failure is swallowed with a note."""
    try:
        from .store import open_store

        open_store().log_run(
            kind=kind,
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            duration_s=duration_s,
            summary=_first_line(result.text),
            started_at=started_at,
        )
    except Exception as exc:  # noqa: BLE001 - logging must never break the run
        print(f"[run not logged: {exc}]")

WEEKLY_TASK = """\
Produce this week's growth report for Tossa Cycling. Steps:
1. Pull Search Console for the last 28 days (group by query, then by page) and identify the top
   SEO opportunities (high-impression/low-CTR and position 5-20).
2. Pull GA4 for the last 28 days (channel group + landing page) to connect traffic to bookings
   and revenue; flag pages that get traffic but don't convert. Cross-check against
   woo_revenue_attribution (actual WooCommerce bookings/revenue by source) to ground the
   channel ROI in real orders, not just GA4 estimates.
3. Pull Google Ads and Meta Ads performance; flag wasted spend (>=50 EUR, 0 conversions) and
   best performers. Pass the campaign rows to budget_recommendations to get bounded, capped
   budget-change suggestions (dry-run — these are recommendations for human approval, never
   applied).
4. Check PageSpeed on the home page and the road-bike-rental page.
Then output four sections: SEO Opportunities, Ads Efficiency, Revenue Insights, Recommended
Actions (prioritised). For tools that are blocked or not yet provisioned, note them under
"Pending integrations" rather than failing.
"""


def build_weekly_report(runtime: AgentRuntime, *, phase: Phase = Phase.READ_ONLY, persist: bool = True) -> str:
    tools = load_all()
    memory = known_cases_block()
    task = f"{WEEKLY_TASK}\n\n{memory}" if memory else WEEKLY_TASK
    started_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    t0 = time.perf_counter()
    result = runtime.run(
        system=COORDINATOR,
        task=task,
        tools=tools,
        phase=phase,
        model=model_for("weekly-report"),
    )
    if persist:
        persist_run("weekly-report", result, started_at=started_at, duration_s=round(time.perf_counter() - t0, 2))
    header = f"# Tossa Cycling — Growth Report ({dt.date.today().isoformat()})\n\n"
    footer = ""
    if result.blocked_calls:
        names = sorted({c["tool"] for c in result.blocked_calls})
        footer = "\n\n---\n_Blocked (need higher phase / human approval): " + ", ".join(names) + "_"
    return header + result.text + footer


def deliver(report: str) -> None:
    """Send the report via the configured channel. Both paths are best-effort and never raise
    in a way that would break a scheduled run."""
    s = get_settings()
    if s.report_channel == "telegram":
        _deliver_telegram(report)
    else:
        _deliver_email(report)


def send_email(subject: str, body: str, *, raise_on_error: bool = False) -> bool:
    """Send one email via SMTP. Returns True on success, False otherwise.

    Scheduled runs call this with raise_on_error=False so a delivery problem prints and is
    swallowed (a broken SMTP must never break the report pipeline). The `test-email` command
    passes raise_on_error=True so a misconfiguration surfaces loudly instead of silently
    falling back to stdout.
    """
    import smtplib
    from email.message import EmailMessage

    s = get_settings()
    if not s.smtp_host or not s.report_recipient:
        msg = f"[email not configured -> {s.report_recipient}]\n{body}"
        if raise_on_error:
            raise RuntimeError("SMTP not configured (set TC_SMTP_HOST and TC_REPORT_RECIPIENT).")
        print(msg)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = s.report_sender or s.smtp_user or s.report_recipient
    msg["To"] = s.report_recipient
    msg.set_content(body)

    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        return True
    except Exception as exc:  # delivery must never break a scheduled run
        if raise_on_error:
            raise
        print(f"[email delivery failed: {exc}]\n{body}")
        return False


def _deliver_email(report: str) -> None:
    """Send the weekly report via SMTP; falls back to stdout and never raises (scheduled path)."""
    send_email("Tossa Cycling — Growth Report", report, raise_on_error=False)


def _deliver_telegram(report: str) -> None:
    import os

    import httpx

    token = os.environ.get("TC_TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TC_TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("[telegram not configured]\n" + report)
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": report[:4000]},
            timeout=30,
        )
    except httpx.HTTPError as exc:  # pragma: no cover
        print(f"[telegram delivery failed: {exc}]\n{report}")
