"""Weekly opportunity report assembly and delivery (provider-neutral except the runtime call).

Produces a structured digest: SEO opportunities / Ads efficiency / Revenue insights /
recommended actions, and delivers it via email or Telegram.
"""

from __future__ import annotations

import datetime as dt

from .config import get_settings
from .core.approval import Phase
from .prompts import COORDINATOR
from .runtime.base import AgentRuntime
from .tools.load import load_all

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


def build_weekly_report(runtime: AgentRuntime, *, phase: Phase = Phase.READ_ONLY) -> str:
    tools = load_all()
    s = get_settings()
    result = runtime.run(
        system=COORDINATOR,
        task=WEEKLY_TASK,
        tools=tools,
        phase=phase,
        model=s.ai_model,
    )
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


def _deliver_email(report: str) -> None:
    """Send via SMTP. Falls back to stdout (and never raises) when SMTP is not configured or a
    send fails, so a scheduled run is never broken by a delivery problem."""
    import smtplib
    from email.message import EmailMessage

    s = get_settings()
    if not s.smtp_host or not s.report_recipient:
        print(f"[email not configured -> {s.report_recipient}]\n{report}")
        return

    msg = EmailMessage()
    msg["Subject"] = "Tossa Cycling — Growth Report"
    msg["From"] = s.report_sender or s.smtp_user or s.report_recipient
    msg["To"] = s.report_recipient
    msg.set_content(report)

    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
    except Exception as exc:  # pragma: no cover - delivery must never break a scheduled run
        print(f"[email delivery failed: {exc}]\n{report}")


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
