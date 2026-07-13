"""Weekly opportunity report assembly and delivery (provider-neutral except the runtime call).

Produces a structured digest: SEO opportunities / Ads efficiency / Revenue insights /
recommended actions, and delivers it via email or Telegram.
"""

from __future__ import annotations

import datetime as dt
import time

from .config import get_settings, model_for, site_label
from .core.approval import Phase
from .memory import known_cases_block
from .prompts import COORDINATOR
from .runtime.base import AgentRuntime, RuntimeResult
from .tools.load import load_all


def _mask_transactional_ids(text: str) -> str:
    """Mask order identifiers in report text (rule 7, enforced mechanically).

    The 2026-07-13 manual validation rerun showed the prompt rule alone is not reliable: the
    model printed /order-pay/53385 and /order-received/53717 verbatim. Reports travel by email,
    and an order URL + key pattern is customer-adjacent data with zero analytical value, so the
    platform guarantees the masking instead of hoping the model remembers. Keeps the first digit
    (enough to see the era of the order) and masks the rest: /order-received/53717 -> /order-received/5xxxx.
    """
    import re

    return re.sub(
        r"(order-(?:received|pay)/)(\d)\d+",
        lambda m: f"{m.group(1)}{m.group(2)}xxxx",
        text,
    )


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

def _report_dates() -> tuple[str, str, str]:
    """(run_date, window_start, window_end) computed in code, Europe/Madrid.

    The 2026-07-13 manual validation rerun invented "Week of 2026-07-14" (a future date) — date
    arithmetic must never be delegated to the model. The window end is the run date itself.
    INCLUSIVE range: a 28-day window ending today starts today-27 (rerun #2 shipped a 29-day
    window labelled "28 days" because of a days=28 off-by-one here).
    """
    from zoneinfo import ZoneInfo

    today = dt.datetime.now(ZoneInfo("Europe/Madrid")).date()
    return today.isoformat(), (today - dt.timedelta(days=27)).isoformat(), today.isoformat()


WEEKLY_TASK = """\
Produce this week's growth report for Tossa Cycling.

DATES (computed by the platform — use these verbatim, do NOT derive your own):
- Run date (Europe/Madrid): {run_date}
- Reporting window: {window_start} to {window_end} (28 days inclusive, ending on the run date)
- Sources report in their OWN timezones (GSC: Pacific Time; GA4: property timezone) — treat
  window boundaries as approximate to ±1 day, and never re-derive day counts yourself.

Steps:
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


def _strip_preamble(text: str) -> str:
    """Drop model narration that precedes the report's first heading.

    Manual validation rerun #2 shipped "All data collected. Now I have full context..." as
    chatter before the actual report — the exact phrase rule 6 bans, in text that carries no
    information. The report proper always starts at its first markdown heading; anything before
    it is working-notes, not deliverable. No heading at all -> leave the text untouched.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            return "\n".join(lines[i:]) if i else text
    return text


def _lint_report(text: str) -> str:
    """Deterministic post-generation checks; appends visible warnings, never blocks delivery.

    A full reject-and-regenerate validator is specced post-0.3; during validation-mode the
    platform flags what it can catch mechanically so a defective report can't pass silently.
    """
    import re

    warnings = []
    # robots.txt cannot noindex, and Disallow HIDES a meta-noindex from Google — a report that
    # RECOMMENDS it would make D#6-style fixes worse (caught in the 2026-07-13 rerun). A line
    # that warns AGAINST robots.txt is correct advice and must not be flagged (false positive
    # in manual validation rerun #2 — the model said "not robots.txt" and lint scolded it).
    # Any negative cue exempts the line: rerun #3 phrased correct advice as "robots.txt
    # Disallow is not the correct method", which the previous fixed-phrase list missed. A
    # warning-level lint prefers a rare false negative over recurring false positives.
    _negations = (" not ", "never", "cannot", "can not", "avoid", "would hide", "hides",
                  "instead of robots.txt")
    for line in text.splitlines():
        low = line.lower()
        if "robots.txt" in low and "noindex" in low and not any(n in low for n in _negations):
            warnings.append("mentions robots.txt alongside noindex — robots.txt CANNOT noindex; "
                            "use a meta robots tag or X-Robots-Tag and keep the page crawlable")
            break
    # Comparative 404-vs-410 de-indexing speed claims keep recurring despite the prompt rule
    # (rerun #3 violated it verbatim) — catch the characteristic phrasing deterministically.
    if re.search(r"404[^.\n]{0,80}delays?\s+(?:de-?index|the\s+de-?index)", text, re.IGNORECASE):
        warnings.append("makes a comparative 404-vs-410 de-indexing speed claim — say "
                        "'D#2 specifies 410; current implementation unverified' instead")
    if re.search(r"order-(?:received|pay)/\d{2,}", text):
        warnings.append("unmasked transactional order ID survived masking — inspect the pipeline")
    if not warnings:
        return text
    return text + "\n\n---\n⚠️ **Platform lint:** " + " · ".join(warnings)


def build_weekly_report(
    runtime: AgentRuntime,
    *,
    phase: Phase = Phase.READ_ONLY,
    persist: bool = True,
    validation: bool = False,
) -> str:
    tools = load_all()
    memory = known_cases_block()
    run_date, window_start, window_end = _report_dates()
    task_text = WEEKLY_TASK.format(run_date=run_date, window_start=window_start, window_end=window_end)
    task = f"{task_text}\n\n{memory}" if memory else task_text
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
        # Distinct ledger kind: manual validation runs must be machine-distinguishable from the
        # scheduled runs that count toward the release gate.
        run_kind = "weekly-report-validation" if validation else "weekly-report"
        persist_run(run_kind, result, started_at=started_at, duration_s=round(time.perf_counter() - t0, 2))
    mode_line = ("**Report mode:** MANUAL VALIDATION — does not count toward the acceptance gate\n"
                 if validation else "")
    header = (f"# Tossa Cycling — Growth Report ({run_date})\n"
              f"**Profile:** {site_label()} · **Analytics source:** production GSC/GA4 (read-only) · "
              f"**WP/Woo connector:** staging\n"
              f"{mode_line}\n")
    footer = ""
    if result.blocked_calls:
        names = sorted({c["tool"] for c in result.blocked_calls})
        footer = "\n\n---\n_Blocked (need higher phase / human approval): " + ", ".join(names) + "_"
    return header + _lint_report(_mask_transactional_ids(_strip_preamble(result.text))) + footer


def deliver(report: str, *, validation: bool = False) -> None:
    """Send the report via the configured channel. Both paths are best-effort and never raise
    in a way that would break a scheduled run."""
    s = get_settings()
    if s.report_channel == "telegram":
        _deliver_telegram(report)
    else:
        subject = "Tossa Cycling — Growth Report"
        if validation:
            subject = "[MANUAL VALIDATION] " + subject
        send_email(subject, report, raise_on_error=False)


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
