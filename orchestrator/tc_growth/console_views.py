"""Operator homepage + read panels (WP-CONSOLE-USABILITY U3b).

One screen answering the owner's five Monday questions, in order: did the report run · what
needs attention · what decisions wait · any infrastructure problems · what ran recently. Content
is EXACTLY the spec list — no charts, no KPIs, no navigation tree. The purpose is to shorten the
owner's Monday workflow, not demonstrate frontend capability.

Design rules honored here:
- Environment truth is a PANEL of separate source lines, never one label (the mixed
  staging/production reality must be unmistakable).
- The report view displays the U3a immutable artifact with its trust-chain metadata; the body is
  redacted at DISPLAY time only (the stored artifact stays byte-identical to the email).
- Every store-sourced string is HTML-escaped — case titles and report bodies are
  attacker-influenceable content.
- Functions take the store and helpers as parameters (no hidden globals) so tests inject fakes.
"""

from __future__ import annotations

import datetime as dt
import html
import json
from collections.abc import Callable


def _e(x: object) -> str:
    return html.escape(str(x), quote=True)


def _age(iso: str | None) -> str:
    """Compact 'how long ago' for ISO timestamps; unknown stays honest."""
    if not iso:
        return "—"
    try:
        then = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        delta = dt.datetime.now(dt.timezone.utc) - then
        mins = int(delta.total_seconds() // 60)
        if mins < 60:
            return f"{mins}m ago"
        if mins < 48 * 60:
            return f"{mins // 60}h ago"
        return f"{mins // (24 * 60)}d ago"
    except Exception:  # noqa: BLE001 - a bad timestamp must not break the page
        return "—"


def _section(title: str, inner: str) -> str:
    return f"<section class='card'><h2 style='font-size:15px'>{_e(title)}</h2>{inner}</section>"


def env_truth_panel(*, profile: str, env_kind: str, wp_host: str, allow_writes: bool) -> str:
    """Source truth as separate lines — a single badge would hide the mixed-source reality and
    invite trusting staging WooCommerce data as production evidence (spec, reviewer-set)."""
    rows = (
        ("Profile", profile or "—"),
        ("Operating environment", (env_kind or "staging").capitalize()),
        ("Analytics", "Production GSC/GA4 (read-only)"),
        ("WordPress", wp_host or "not configured"),
        ("WooCommerce orders", "Staging — not production truth (D#7)"),
        ("Production writes", "Enabled (capped by phase gate)" if allow_writes else "Disabled"),
    )
    cells = "".join(f"<div><span class='tag'>{_e(k)}</span> {_e(v)}</div>" for k, v in rows)
    return f"<section class='card' id='envtruth'>{cells}</section>"


def home_body(store, *, profile: str, env_kind: str, wp_host: str, allow_writes: bool,
              redact: Callable[[str], str]) -> str:
    """The five questions, in order. Every block renders an honest empty state."""
    parts: list[str] = [env_truth_panel(profile=profile, env_kind=env_kind, wp_host=wp_host,
                                        allow_writes=allow_writes)]

    # 1 — Did the scheduled report run successfully?
    runs = store.list_runs(kind="weekly-report", limit=1)
    art = store.latest_report_artifact(kind="weekly-report")
    if runs:
        r = runs[0]
        ok = str(r.status) == "ok"
        mark = "<span class='ok'>✓</span>" if ok else "<span class='err'>✗</span>"
        line = (f"{mark} Last scheduled report: run#{r.id} · {_e(r.started_at)} "
                f"({_e(_age(r.started_at))}) · status {_e(r.status)}")
    else:
        line = "No scheduled report run recorded yet."
    if art is not None:
        verdict = "validated" if art.validator_ok else f"REJECTED ({_e(art.validator_reason)})"
        line += (f"<div><a href='/report/{art.id}'>Read the latest report</a> — artifact "
                 f"#{art.id}, {verdict}, delivery {_e(art.delivery_status)}"
                 f" (attempt {art.delivery_attempts})</div>")
    else:
        line += ("<div class='muted'>No stored report artifact yet — the first one is created "
                 "by the next scheduled run.</div>")
    parts.append(_section("Weekly report", line))

    # 2 — What requires my attention? (open + monitoring cases)
    attention = [c for status in ("open", "monitoring")
                 for c in store.list_cases(status=status, limit=10)]
    if attention:
        items = "".join(
            f"<div><span class='tag'>{_e(c.status)}</span> <b>{_e(c.ref or c.id)}</b> "
            f"{_e(c.title)} · {_e(c.priority)} · updated {_e(_age(c.updated_at))}</div>"
            for c in attention)
    else:
        items = "<div class='ok'>Nothing requires attention.</div>"
    parts.append(_section(f"Attention ({len(attention)})", items))

    # 3 — What decisions are waiting? (the owner queue; empty == don't disturb)
    waiting = [d for d in store.list_decisions(limit=50) if str(d.status) == "proposed"]
    if waiting:
        items = "".join(
            f"<div><b>D#{d.id}</b> {_e(d.title)} · proposed {_e(_age(d.made_at))}</div>"
            for d in waiting)
    else:
        items = "<div class='ok'>🟢 Nothing waiting — no decisions need you.</div>"
    parts.append(_section(f"Decisions waiting ({len(waiting)})", items))

    # 4 — Any infrastructure or data problems? (recent non-ok runs)
    recent = store.list_runs(limit=20)
    problems = [r for r in recent if str(r.status) not in ("ok", "completed")]
    if problems:
        items = "".join(
            f"<div><span class='err'>✗</span> run#{r.id} {_e(r.kind)} · {_e(r.status)} · "
            f"{_e(_age(r.started_at))}"
            + (f" · {_e(redact(str(r.detail))[:160])}" if r.detail else "") + "</div>"
            for r in problems)
    else:
        items = "<div class='ok'>None detected in the recent run history.</div>"
    parts.append(_section(f"Problems ({len(problems)})", items))

    # 5 — What was executed recently? (Console operations; full log lives in Evidence)
    ops = [r for r in recent if str(r.kind).startswith("op:")][:5]
    if ops:
        def _outcome(r) -> str:
            try:
                return json.loads(r.detail or "{}").get("outcome", r.status)
            except Exception:  # noqa: BLE001
                return str(r.status)
        items = "".join(
            f"<div>run#{r.id} {_e(str(r.kind)[3:])} · {_e(_outcome(r))} · "
            f"{_e(_age(r.started_at))}</div>" for r in ops)
        items += "<div class='muted'><a href='/logs'>Full operation log → Evidence</a></div>"
    else:
        items = "<div class='muted'>No operations run through the Console yet.</div>"
    parts.append(_section("Recent operations", items))

    return "".join(parts)


def report_body(artifact, *, redact: Callable[[str], str]) -> str:
    """One immutable artifact with its trust-chain metadata. The body is shown redacted
    (display-time only) and escaped; the stored bytes stay byte-identical to the email."""
    a = artifact
    verdict = ("<span class='ok'>validated</span>" if a.validator_ok
               else f"<span class='err'>REJECTED — {_e(a.validator_reason)}</span>")
    meta = (
        f"<div><span class='tag'>artifact</span> #{a.id} · {_e(a.kind)} · run#{_e(a.run_id)}</div>"
        f"<div><span class='tag'>window</span> {_e(a.window or '—')} · generated {_e(a.generated_at)}</div>"
        f"<div><span class='tag'>validator</span> v{_e(a.validator_version)}: {verdict}</div>"
        f"<div><span class='tag'>delivery</span> {_e(a.delivery_status)} · attempt "
        f"{a.delivery_attempts} · {_e(a.delivered_at or '—')}</div>"
        f"<div><span class='tag'>sha256</span> <code>{_e(a.content_sha256)}</code></div>"
        f"<div class='muted'>Re-send: Operations → “Re-send latest weekly report”.</div>"
    )
    body = f"<pre style='white-space:pre-wrap;font:13px/1.5 inherit'>{_e(redact(a.body))}</pre>"
    return (f"<section class='card'>{meta}</section>"
            f"<section class='card'>{body}</section>"
            "<p><a href='/'>&larr; Home</a></p>")


def cases_body(store) -> str:
    """All cases, read-only — replaces the U1 placeholder tab. Detail beyond this stays in the
    weekly reports and the store CLI until a later slice."""
    cases = store.list_cases(limit=50)
    if not cases:
        return "<p class='muted'>No cases recorded yet.</p>"
    rows = "".join(
        f"<div><span class='tag'>{_e(c.status)}</span> <b>{_e(c.ref or c.id)}</b> {_e(c.title)}"
        f" · {_e(c.priority)} · opened {_e(_age(c.created_at))} · updated {_e(_age(c.updated_at))}"
        "</div>"
        for c in cases)
    return _section(f"Cases ({len(cases)})", rows)
