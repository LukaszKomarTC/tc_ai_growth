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


def status_card(waiting: list) -> str:
    """The first thing the owner sees (U3b.1): either the green all-clear or the top waiting
    decision — SIMPLE surfacing of existing data (title, rationale, age). The smart card
    (impact/confidence/evidence) is U4's, once the decision schema can carry it."""
    if not waiting:
        return ("<div class='statuscard calm'><p class='lead'>🟢 Nothing blocking you</p>"
                "<div class='why'>No decisions are waiting for your approval.</div></div>")
    top = min(waiting, key=lambda d: str(d.made_at or ""))  # waited longest = first in line
    why = top.rationale or "Proposed by the platform — details in the latest weekly report."
    return (f"<div class='statuscard act'><p class='lead'>🔴 "
            f"{len(waiting)} decision{'s' if len(waiting) != 1 else ''} waiting — "
            f"top: {_e(top.title)}</p>"
            f"<div class='why'>D#{top.id} · proposed {_e(_age(top.made_at))} · {_e(why)}</div>"
            "</div>")


def home_body(store, *, profile: str, env_kind: str, wp_host: str, allow_writes: bool,
              redact: Callable[[str], str]) -> str:
    """The five questions, in order — after the status card, which answers the reviewer's third
    question ('what should I do next?') before any scanning. Truth panel moved LAST (reference,
    not action; it keeps its authority, not the prime screen space). Honest empty states
    everywhere."""
    all_decisions = store.list_decisions(limit=50)
    waiting_now = [d for d in all_decisions if str(d.status) == "proposed"]
    parts: list[str] = [status_card(waiting_now)]

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
        def _sev(c) -> str:
            urgent = str(c.status) == "open" and str(c.priority) in ("high", "critical")
            return "sev-err" if urgent else "sev-warn"
        items = "".join(
            f"<div class='{_sev(c)}'><span class='tag'>{_e(c.status)}</span> "
            f"<b>{_e(c.ref or c.id)}</b> {_e(c.title)} · {_e(c.priority)} · "
            f"updated {_e(_age(c.updated_at))}</div>"
            for c in attention)
    else:
        items = "<div class='ok'>Nothing requires attention.</div>"
    parts.append(_section(f"Attention ({len(attention)})", items))

    # 3 — What decisions are waiting? (the owner queue; empty == don't disturb)
    waiting = waiting_now
    if waiting:
        items = "".join(
            f"<div><a href='/decision/{d.id}'><b>D#{d.id}</b></a> {_e(d.title)} · "
            f"proposed {_e(_age(d.made_at))} · <a href='/decision/{d.id}'>Review →</a></div>"
            for d in waiting)
    else:
        items = "<div class='ok'>🟢 Nothing waiting — no decisions need you.</div>"
    # The queue shows only what needs the owner NOW; everything that left it stays
    # discoverable in the history (U4a.1 — approved decisions must never seem to vanish).
    items += "<div class='muted'><a href='/decisions'>Decision history →</a></div>"
    parts.append(_section(f"Decisions waiting ({len(waiting)})", items))

    # 4 — Any infrastructure or data problems? (recent non-ok runs)
    recent = store.list_runs(limit=20)
    problems = [r for r in recent if str(r.status) not in ("ok", "completed")]
    if problems:
        items = "".join(
            f"<div class='sev-err'><span class='err'>✗</span> run#{r.id} {_e(r.kind)} · {_e(r.status)} · "
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

    parts.append(env_truth_panel(profile=profile, env_kind=env_kind, wp_host=wp_host,
                                 allow_writes=allow_writes))
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


# -- decision detail + approval workflow (WP-U4a) -------------------------------------------------
#
# Reading order is the spec's, owner-first: recommendation → evidence → impact/confidence →
# the exact proposed change → controls — and only THEN the technical trail (hash, revision,
# history). U4a adds approve/reject only; no Apply, Execute, or Verify control exists yet, and
# none may appear here before its capability has its own acceptance (no control overstates
# authority).


def _provenance(raw: str | None) -> str:
    """Impact/confidence render with their provenance, never as a bare number. A missing or
    unparseable value renders 'unknown' — unknown beats invented precision (spec pt 6)."""
    if not raw:
        return "<span class='muted'>unknown</span>"
    try:
        p = json.loads(raw)
    except (ValueError, TypeError):
        return "<span class='muted'>unknown</span>"
    if not isinstance(p, dict) or not p.get("value"):
        return "<span class='muted'>unknown</span>"
    label = p.get("label") or "estimate"
    trail = " · ".join(_e(p[k]) for k in ("method", "source", "as_of") if p.get(k))
    return (f"<b>{_e(p['value'])}</b> <span class='badge warn'>{_e(label)}</span>"
            + (f" <span class='tag'>{trail}</span>" if trail else ""))


def _envelope_dict(decision) -> dict | None:
    try:
        env = json.loads(decision.envelope or "")
        return env if isinstance(env, dict) else None
    except (ValueError, TypeError):
        return None


def _proposed_change(env: dict) -> str:
    """The exact change, field by field — what the owner is actually approving. Escaped
    verbatim; no summarization that could hide a wrong value."""
    target = env.get("target") or {}
    urls = target.get("expected_urls") or {}
    env_kind = str(env.get("environment", ""))
    env_cls = "err" if env_kind == "production" else "warn"
    rows = [
        f"<div><span class='tag'>environment</span> "
        f"<span class='badge {env_cls}'>{_e(env_kind.upper())}</span> · "
        f"profile {_e(env.get('profile', '—'))} · kind {_e(env.get('kind', '—'))}</div>",
        f"<div><span class='tag'>target</span> {_e(target.get('object_type', '—'))}"
        + (f" · post {_e(target['post_id'])}" if target.get("post_id") is not None else "")
        + "</div>",
    ]
    rows += [f"<div><span class='tag'>url ({_e(lang)})</span> {_e(url)}</div>"
             for lang, url in urls.items()]
    payload = env.get("payload") or {}
    rows += [f"<div><span class='tag'>{_e(field)}</span> {_e(value)}</div>"
             for field, value in payload.items()]
    return "".join(rows)


def decision_controls(decision, *, csrf: str) -> str:
    """Approve / Reject / Unapprove per current state — or the plain-English reason there are
    no controls. Approve POSTs WITHOUT `confirmed`, which renders the confirmation step (two
    genuine clicks, stateless server-side)."""
    d = decision
    if not d.envelope_sha256:
        return ("<p class='muted'>This decision predates the approval workflow — it has no "
                "bound envelope, so there is nothing for an approval to bind to. It stays "
                "visible for the record; to act on it, record a new decision.</p>")
    hidden = (f"<input type='hidden' name='csrf' value='{_e(csrf)}'>"
              f"<input type='hidden' name='revision' value='{d.revision}'>")
    if d.status == "proposed":
        return (
            f"<form method='post' action='/decision/{d.id}/approve' style='display:inline'>"
            f"{hidden}<button type='submit'>Approve…</button></form> "
            f"<form method='post' action='/decision/{d.id}/reject' "
            "style='display:inline-flex;gap:8px;margin-left:12px'>"
            f"{hidden}<input type='text' name='reason' placeholder='Rejection reason (required)'"
            " style='font:inherit;padding:7px 10px;border-radius:6px;"
            "border:1px solid var(--line);background:var(--bg);color:var(--fg);width:260px'>"
            "<button class='ghost' type='submit'>Reject</button></form>")
    if d.status == "approved":
        return (
            f"<p><span class='badge ok'>approved</span> by {_e(d.approved_by or '—')} at "
            f"{_e(d.approved_at or '—')}. The envelope is now immutable; the only way to "
            "change it is to unapprove first.</p>"
            f"<form method='post' action='/decision/{d.id}/unapprove'>{hidden}"
            "<button class='ghost' type='submit'>Unapprove (back to proposed)</button></form>")
    if d.status == "executed":
        return (f"<p><span class='badge ok'>executed</span> at {_e(d.executed_at or '—')} · "
                f"evidence <code>{_e(d.execution_evidence or '—')}</code>. Terminal — "
                "corrections are new decisions.</p>")
    return (f"<p class='muted'>No actions: this decision is <b>{_e(d.status)}</b>.</p>")


def verification_section(decision, *, csrf: str, verifiable: bool, pending=None,
                         wait_s: int = 0) -> str:
    """The U4b 'Verify live change' control (spec §Verification): the platform never writes to
    production — the owner applies in WP, the platform verifies the live pages against the
    approved envelope in TWO owner-triggered steps and marks the decision executed. Rendered
    ONLY for approved decisions; the control may never overstate authority, so kinds without a
    registered verify path get the plain reason instead."""
    d = decision
    if d.status != "approved":
        return ""
    if not verifiable:
        return _section("Verify live change",
                        f"<div class='muted'>Not available: kind {_e(d.kind or '—')} has no "
                        "registered verification path yet.</div>")
    hidden = (f"<input type='hidden' name='csrf' value='{_e(csrf)}'>"
              f"<input type='hidden' name='revision' value='{d.revision}'>")
    intro = ("<div class='muted'>Apply the approved change in WordPress first — verification "
             "reads the LIVE pages and compares them with the approved envelope. Two reads, "
             "both matching, mark this decision executed. Nothing is written to the site."
             "</div>")
    if pending is None:
        body = (intro +
                f"<form method='post' action='/decision/{d.id}/verify' style='margin-top:8px'>"
                f"{hidden}<button type='submit'>Verify live change</button></form>")
    elif wait_s > 0:
        body = (intro +
                f"<div style='margin-top:8px'>Read #1 matched at {_e(pending.finished_at)} "
                f"(attempt #{pending.id}). Confirm arms in <b>{wait_s}s</b> — two reads "
                "separated in time, so a transient state cannot self-confirm. Reload this "
                "page to refresh.</div>"
                "<button disabled title='minimum interval not reached'>Confirm verification"
                "</button>")
    else:
        body = (intro +
                f"<div style='margin-top:8px'>Read #1 matched at {_e(pending.finished_at)} "
                f"(attempt #{pending.id}). Ready to confirm.</div>"
                f"<form method='post' action='/decision/{d.id}/verify-confirm' "
                f"style='margin-top:8px'>{hidden}"
                "<button type='submit'>Confirm verification</button></form>")
    return _section("Verify live change", body)


def verify_attempts_section(attempts) -> str:
    """Every verification read, newest last, individually inspectable — failures accumulate
    and success never erases them (append-only evidence)."""
    if not attempts:
        return ""
    rows = []
    for a in attempts:
        cls = {"match": "ok", "mismatch": "err", "error": "warn"}.get(str(a.outcome), "")
        summary = ""
        try:
            urls = json.loads(a.detail or "{}")
            problems = [f"{lang}: {p}" for lang, u in urls.items()
                        for p in (u.get("problems") or [])]
            if problems:
                summary = " · " + _e("; ".join(problems)[:220])
        except (ValueError, TypeError):
            pass
        rows.append(
            f"<div><span class='tag'>{_e(a.finished_at)}</span> read #{a.read_number} · "
            f"<span class='badge {cls}'>{_e(a.outcome)}</span> · attempt #{a.id} · "
            f"rev {a.revision}{summary}</div>")
    return _section(f"Verification attempts ({len(attempts)})", "".join(rows))


_DECISION_FILTERS = ("all", "proposed", "approved", "rejected", "executed")


def decisions_body(store, *, status: str = "all") -> str:
    """The Decisions destination (U4a.1, review #71 post-merge finding): EVERY decision stays
    discoverable after it leaves the homepage queue. The queue answers 'what needs me NOW';
    this page is the history — approved, rejected and executed decisions remain visible,
    linked, and (where the state machine permits) manageable. Without it, Unapprove is
    unreachable the moment approval succeeds."""
    decisions = store.list_decisions(limit=200)
    shown = [d for d in decisions if status == "all" or str(d.status) == status]

    filters = " · ".join(
        (f"<b>{_e(f.capitalize())}</b>" if f == status
         else f"<a href='/decisions{'' if f == 'all' else '?status=' + f}'>{_e(f.capitalize())}</a>")
        for f in _DECISION_FILTERS)

    _badge = {"proposed": "warn", "approved": "ok", "executed": "ok", "rejected": "err"}
    rows = []
    for d in decisions:
        if status != "all" and str(d.status) != status:
            continue
        cls = _badge.get(str(d.status), "")
        kind = _e(d.kind) if d.kind else "<span class='muted'>legacy</span>"
        extra = ""
        if str(d.status) == "approved" and d.approved_at:
            extra = f" · approved {_e(_age(d.approved_at))} by {_e(d.approved_by or '—')}"
        rows.append(
            f"<div><a href='/decision/{d.id}'><b>D#{d.id}</b></a> "
            f"<span class='badge {cls}'>{_e(d.status)}</span> {_e(d.title)} · {kind} · "
            f"proposed {_e(_age(d.made_at))}{extra}</div>")
    if not rows:
        body = f"<div class='muted'>No {'' if status == 'all' else status + ' '}decisions.</div>"
    else:
        body = "".join(rows)
    return (f"<div class='muted' style='margin-bottom:10px'>{filters}</div>"
            + _section(f"Decisions ({len(shown)})", body))


def decision_body(decision, events, *, csrf: str, notice: str = "", error: str = "",
                  verifiable: bool = False, pending=None, wait_s: int = 0,
                  attempts=()) -> str:
    """The decision detail page (/decision/<id>) — why approve, what exactly changes, then the
    technical trail. U4b adds the Verify-live-change section (approved decisions) and the
    append-only verification-attempt evidence."""
    d = decision
    banner = ""
    if error:
        banner = f"<div class='statuscard act'><p class='lead'>{_e(error)}</p></div>"
    elif notice:
        banner = f"<div class='statuscard calm'><p class='lead'>{_e(notice)}</p></div>"

    head = (f"<h2 style='margin:0 0 2px;font-size:18px'>D#{d.id} · {_e(d.title)}</h2>"
            f"<div class='muted'>status <b>{_e(d.status)}</b> · proposed {_e(_age(d.made_at))}"
            f" by {_e(d.made_by or '—')}</div>")

    why = _section("Recommendation",
                   f"<div>{_e(d.rationale)}</div>" if d.rationale
                   else "<div class='muted'>No rationale recorded.</div>")
    evidence = _section("Evidence",
                        f"<div>{_e(d.evidence)}</div>" if d.evidence
                        else "<div class='muted'>No evidence pointer recorded.</div>")
    numbers = _section("Expected impact / confidence",
                       f"<div><span class='tag'>impact</span> {_provenance(d.impact)}</div>"
                       f"<div><span class='tag'>confidence</span> {_provenance(d.confidence)}</div>")

    env = _envelope_dict(d)
    if env is not None:
        change = _section("The exact proposed change", _proposed_change(env))
    elif d.envelope_sha256:
        change = _section("The exact proposed change",
                          "<div class='err'>Envelope unreadable — refusing to summarize. "
                          "Inspect via CLI before acting.</div>")
    else:
        change = _section("The exact proposed change",
                          "<div class='muted'>None bound (legacy decision).</div>")

    controls = _section("Actions", decision_controls(d, csrf=csrf))

    tech_rows = [
        f"<div><span class='tag'>envelope sha256</span> <code>{_e(d.envelope_sha256 or '—')}</code></div>",
        f"<div><span class='tag'>revision</span> {d.revision}</div>",
    ]
    for ev in events:
        arrow = f"{_e(ev.from_status or '∅')} → {_e(ev.to_status)}"
        extra = f" · {_e(ev.detail)}" if ev.detail else ""
        tech_rows.append(
            f"<div><span class='tag'>{_e(ev.at)}</span> {_e(ev.action)} by {_e(ev.actor)} · "
            f"{arrow} · rev {ev.revision}"
            + (f" · <code>{_e(str(ev.envelope_sha256)[:12])}</code>" if ev.envelope_sha256 else "")
            + extra + "</div>")
    tech = _section("History & integrity", "".join(tech_rows))

    verify = verification_section(d, csrf=csrf, verifiable=verifiable, pending=pending,
                                  wait_s=wait_s)
    attempts_html = verify_attempts_section(attempts)

    return (banner + head + why + evidence + numbers + change + controls + verify
            + attempts_html + tech
            + "<p><a href='/'>&larr; Home</a> · <a href='/decisions'>All decisions</a></p>")


def decision_confirm_body(decision, *, csrf: str) -> str:
    """The second approval step — a page, not a JS dialog: stateless, survives reload, and
    shows one more time exactly what is being bound before anything mutates."""
    d = decision
    env = _envelope_dict(d) or {}
    env_kind = str(env.get("environment", ""))
    warn = (f"<div class='statuscard act'><p class='lead'>You are approving this for "
            f"{_e(env_kind.upper() or 'UNKNOWN ENVIRONMENT')}</p>"
            "<div class='why'>Approval binds the exact envelope below (content + target + "
            "environment). Nothing is executed by approving.</div></div>")
    change = _section("Binding envelope", _proposed_change(env) if env else
                      "<div class='err'>Envelope unreadable.</div>")
    forms = (
        f"<form method='post' action='/decision/{d.id}/approve' style='display:inline'>"
        f"<input type='hidden' name='csrf' value='{_e(csrf)}'>"
        f"<input type='hidden' name='revision' value='{d.revision}'>"
        "<input type='hidden' name='confirmed' value='1'>"
        "<button type='submit'>Confirm approval</button></form> "
        f"<a href='/decision/{d.id}' style='margin-left:12px'>Cancel</a>")
    return (warn + f"<h2 style='font-size:17px'>D#{d.id} · {_e(d.title)}</h2>" + change
            + _section("Confirm", forms))


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
