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
    # U4c: the card leads with the business headline and carries the estimate-labelled
    # impact/confidence the schema now holds — enough to decide whether to open it at all.
    numbers = ""
    if top.impact or top.confidence:
        numbers = (f"<div class='why' style='margin-top:6px'>"
                   f"<span class='tag'>impact</span> {_provenance(top.impact)} · "
                   f"<span class='tag'>confidence</span> {_provenance(top.confidence)}</div>")
    return (f"<div class='statuscard act'><p class='lead'>🔴 Action required — "
            f"{_e(top.title)}</p>"
            f"<div class='why'>D#{top.id} · waiting {_e(_age(top.made_at))}"
            + (f" · {len(waiting)} decisions in the queue" if len(waiting) > 1 else "")
            + f" · {_e(why)}</div>{numbers}"
            f"<div style='margin-top:8px'><a href='/decision/{top.id}'>Review →</a></div>"
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
        def _label(c) -> tuple[str, str]:
            urgent = str(c.status) == "open" and str(c.priority) in ("high", "critical")
            return ("sev-err", "🔴 Action required") if urgent else ("sev-warn",
                                                                    "🟡 Keep an eye on")
        items = "".join(
            (lambda cls_label: f"<div class='{cls_label[0]}'><b>{_e(cls_label[1])}</b> "
                               f"<b>{_e(c.ref or c.id)}</b> {_e(c.title)} · {_e(c.status)} · "
                               f"updated {_e(_age(c.updated_at))}</div>")(_label(c))
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
    parts.append("<details class='card' style='padding:14px 16px'>"
                 "<summary style='cursor:pointer;font-weight:700;font-size:15px'>"
                 f"Recent operations ({len(ops)})</summary>"
                 f"<div style='margin-top:10px'>{items}</div></details>")

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
             "reads the LIVE pages and compares them with the approved envelope. It takes "
             "TWO reads at least a minute apart, both matching: a cached or mid-edit page "
             "cannot pass by accident. Nothing is written to the site.</div>")
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


def comparison_section(decision, *, csrf: str, comparison=None, snapshot=None,
                       adoptable: bool = False, snapshot_token: str | None = None) -> str:
    """Current-vs-proposed, read-only (U4c item 2). Loaded ON DEMAND (`?live=1`) rather than on
    every page view: it performs real fetches, and a detail page must not silently hammer the
    site each time it is opened. Values carry the fetch timestamp; a page that could not be read
    says so and shows NO value — a previous read is never substituted for current truth."""
    d = decision
    if not d.envelope_sha256:
        return ""
    if comparison is None:
        return _section(
            "Compare with the live pages",
            "<div class='muted'>Not fetched yet — the comparison reads the live pages through "
            "the same parser the verifier uses.</div>"
            f"<div style='margin-top:8px'><a href='/decision/{d.id}?live=1'>"
            "Compare with the live pages now →</a></div>")
    rows = []
    for r in comparison:
        if r["error"]:
            body = (f"<div class='err'>could not read this page: {_e(r['error'])} — no current "
                    "value shown</div>")
        elif r["same"]:
            body = (f"<div class='ok'>matches</div>"
                    f"<div class='tag'>{_e(r['current'])}</div>")
        else:
            body = (f"<div><span class='tag'>now live</span> {_e(r['current'] or '(missing)')}</div>"
                    f"<div class='sev-warn'><span class='tag'>proposed</span> "
                    f"{_e(r['proposed'])}</div>")
        rows.append(f"<div style='margin:6px 0'><b>{_e(r['label'])} ({_e(r['lang'].upper())})</b>"
                    f"{body}</div>")
    differing = [r for r in comparison if not r["same"] and not r["error"]]
    unreadable = [r for r in comparison if r["error"]]
    if unreadable:
        head = ("<div class='err'>Some pages could not be read — the comparison below is "
                "incomplete.</div>")
    elif differing:
        head = (f"<div class='sev-warn'>{len(differing)} field(s) differ from the live pages."
                "</div>")
    else:
        head = "<div class='ok'>Every field matches what is live right now.</div>"
    stamp = (f"<div class='muted' style='margin-top:8px'>Live values read at "
             f"{_e((snapshot or {}).get('fetched_at', '—'))} · "
             f"<a href='/decision/{d.id}?live=1'>re-read</a></div>")
    adopt = ""
    if adoptable and differing and not unreadable and snapshot_token:
        adopt = (
            f"<form method='post' action='/decision/{d.id}/adopt-live' style='margin-top:10px'>"
            f"<input type='hidden' name='csrf' value='{_e(csrf)}'>"
            f"<input type='hidden' name='revision' value='{d.revision}'>"
            f"<input type='hidden' name='snapshot' value='{_e(snapshot_token)}'>"
            "<button class='ghost' type='submit'>Adopt live content as a new proposal</button>"
            "<div class='muted' style='margin-top:4px'>Creates a NEW decision in "
            "<b>proposed</b>, carrying exactly the values shown above and their provenance. "
            "If the pages change before you click, the adopt is refused and you compare again. "
            "This decision is not changed, approved, or closed.</div></form>")
    return _section("Compare with the live pages", head + "".join(rows) + stamp + adopt)


def last_verify_failure_callout(decision, attempts) -> str:
    """Plain language FIRST, raw evidence after (review #74): when the latest read failed, the
    owner sees which language and what was wrong — URL, canonical, title or meta — in one
    sentence per language, before any JSON-shaped evidence. Store-derived text only."""
    if decision.status != "approved" or not attempts:
        return ""
    last = attempts[-1]
    if str(last.outcome) == "match":
        return ""
    lines = []
    try:
        urls = json.loads(last.detail or "{}")
    except (ValueError, TypeError):
        urls = {}
    for lang, u in urls.items():
        problems = u.get("problems") or []
        if problems:
            lines.append(f"<div><b>{_e(lang.upper())}</b>: {_e(problems[0])}</div>")
    if not lines:
        lines = ["<div>The read could not be completed — see the attempts below.</div>"]
    label = ("The pages could not be fetched" if str(last.outcome) == "error"
             else "The live pages do not match the approved content yet")
    return (f"<div class='statuscard act'><p class='lead'>{_e(label)}</p>"
            f"<div class='why'>Latest read (attempt #{last.id}, {_e(last.finished_at)}):"
            f"</div>{''.join(lines)}"
            "<div class='why'>Fix the page in WordPress (or wait for the cache), then verify "
            "again. Every attempt stays recorded below.</div></div>")


def execution_record_section(decision, attempts) -> str:
    """The permanent business record (review #74): months later, Decision History must explain
    WHY this decision is executed without anyone inspecting the database. One plain paragraph
    naming both reads and what they checked; the raw attempt rows stay below as evidence."""
    d = decision
    if d.status != "executed":
        return ""
    terminal = None
    if (d.execution_evidence or "").startswith("verify_attempt:"):
        try:
            tid = int(d.execution_evidence.split(":", 1)[1])
            terminal = next((a for a in attempts if a.id == tid), None)
        except ValueError:
            terminal = None
    if terminal is None:
        return _section("Execution record",
                        f"<div>Executed at {_e(d.executed_at or '—')} · evidence "
                        f"<code>{_e(d.execution_evidence or '—')}</code>.</div>")
    first = next((a for a in attempts if a.id == terminal.pair_id), None)
    langs = []
    try:
        langs = sorted(json.loads(terminal.detail or "{}").keys())
    except (ValueError, TypeError):
        pass
    checked = (f"On each page ({', '.join(_e(x) for x in langs)}) the final URL, the canonical "
               "link, the title and the meta description all matched the approved envelope "
               "exactly." if langs else "")
    reads = ((f"read #1 at {_e(first.finished_at)} (attempt #{first.id}) and " if first else "")
             + f"read #2 at {_e(terminal.finished_at)} (attempt #{terminal.id})")
    return _section(
        "Execution record",
        f"<div>Executed at <b>{_e(d.executed_at or '—')}</b>: the platform verified the LIVE "
        f"pages against the approved envelope twice — {reads} — both full matches. {checked} "
        f"Envelope <code>{_e(str(terminal.envelope_sha256)[:12])}</code>, revision "
        f"{terminal.revision}. Nothing was written to the site; the owner applied the change, "
        "the platform verified it.</div>")


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
    return ("<details class='card' style='padding:14px 16px'>"
            f"<summary style='cursor:pointer;font-weight:700;font-size:15px'>"
            f"Verification attempts ({len(attempts)})</summary>"
            f"<div style='margin-top:10px'>{''.join(rows)}</div></details>")


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
        elif str(d.status) == "executed" and d.executed_at:
            extra = (f" · executed {_e(_age(d.executed_at))} · verified live "
                     f"({_e(d.execution_evidence or '—')})")
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
                  attempts=(), comparison=None, snapshot=None,
                  snapshot_token: str | None = None) -> str:
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
    # Progressive disclosure (U4c item 3): the technical trail is available, not imposed —
    # routine approvals stay short, auditors lose nothing.
    tech = ("<details class='card' style='padding:14px 16px'>"
            "<summary style='cursor:pointer;font-weight:700;font-size:15px'>"
            "History &amp; integrity</summary>"
            f"<div style='margin-top:10px'>{''.join(tech_rows)}</div></details>")

    compare = comparison_section(d, csrf=csrf, comparison=comparison, snapshot=snapshot,
                                 adoptable=verifiable and d.status in ("proposed", "approved",
                                                                      "rejected", "executed"),
                                 snapshot_token=snapshot_token)
    verify = verification_section(d, csrf=csrf, verifiable=verifiable, pending=pending,
                                  wait_s=wait_s)
    failure = last_verify_failure_callout(d, attempts)
    execution = execution_record_section(d, attempts)
    attempts_html = verify_attempts_section(attempts)

    return (banner + head + why + evidence + numbers + change + compare + controls + execution
            + failure + verify + attempts_html + tech
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


# --- WP-U4d: the deployment surface (issue #77 Decision 2) --------------------------------

def deploy_body(runs: list[dict], *, csrf: str, offered: bool, disabled_reason: str,
                notice: str = "", error: str = "") -> str:
    """The deployment list. The Console can always SHOW deployments — reading history is never
    dangerous — but the control to authorize one appears only when the operation is enabled."""
    head = ""
    if notice:
        head += f"<div class='ok'>{_e(notice)}</div>"
    if error:
        head += f"<div class='sev-warn'>{_e(error)}</div>"

    if offered:
        form = (
            "<form method='post' action='/deploy/plan' style='margin-top:10px'>"
            f"<input type='hidden' name='csrf' value='{_e(csrf)}'>"
            "<label class='muted'>Reviewed commit to deploy (exact 40-character SHA)</label><br>"
            "<input name='sha' size='46' autocomplete='off' spellcheck='false'>"
            "<button type='submit'>Show me the plan</button>"
            "<div class='muted' style='margin-top:4px'>You will review the full plan — including "
            "every step that cannot be undone — before anything runs.</div></form>")
    else:
        form = (f"<div class='muted' style='margin-top:10px'>{_e(disabled_reason)}</div>")

    rows = []
    for r in runs:
        badge = {"succeeded": "ok", "failed": "sev-warn", "refused": "sev-warn",
                 "running": "muted", "planned": "muted"}.get(r["status"], "muted")
        rows.append(
            f"<div class='card'><div><b>Deploy #{r['id']}</b> — "
            f"<span class='{badge}'>{_e(r['status'])}</span></div>"
            f"<div class='muted'>{_e(r['sha'][:12])} · requested {_e(r['requested_at'])} "
            f"by {_e(r['requested_by'])}</div>"
            f"<div>{_e(r['outcome'] or '')}</div>"
            f"<div><a href='/deploy/{r['id']}'>Open →</a></div></div>")
    body = head + _section("Deploy a reviewed release", form)
    body += _section("Deployment history", "".join(rows) or
                     "<div class='muted'>No deployments recorded yet.</div>")
    return body


def deploy_plan_body(run: dict, plan: dict, plan_text: str, *, csrf: str,
                     offered: bool, notice: str = "", error: str = "") -> str:
    """What the owner reads BEFORE authorizing. Irreversible steps are called out separately and
    prominently — they are never discovered during execution."""
    head = (f"<div class='ok'>{_e(notice)}</div>" if notice else "")
    head += (f"<div class='sev-warn'>{_e(error)}</div>" if error else "")
    irreversible = plan.get("irreversible_steps") or []
    warn = ("<div class='sev-warn'><b>These steps cannot be undone:</b> "
            + _e(", ".join(irreversible)) +
            ". Before any of them run, the evidence store is copied and the copy is proven two "
            "ways — SQLite's own integrity check, and a digest of every row in every table "
            "compared against the original. Matching row counts are not accepted as proof. "
            "If the copy cannot be proven faithful, the deployment stops.</div>")
    start = ""
    if offered and run["status"] == "planned":
        start = (
            f"<form method='post' action='/deploy/{run['id']}/start' style='margin-top:12px'>"
            f"<input type='hidden' name='csrf' value='{_e(csrf)}'>"
            f"<input type='hidden' name='digest' value='{_e(run['plan_digest'])}'>"
            "<button type='submit'>Authorize and run this deployment</button>"
            "<div class='muted' style='margin-top:4px'>Authorization binds to the plan above. "
            "It runs in its own process, so it survives the Console restart it performs.</div>"
            "</form>")
    return head + _section(f"Deployment plan — {_e(plan['target_sha'][:12])}",
                           warn + f"<pre class='plan'>{_e(plan_text)}</pre>" + start)


def deploy_run_body(run: dict, steps: list[dict]) -> str:
    """The observation view. Reconnection is by durable id: a restarted Console shows the same
    run and its terminal result rather than orphaning it."""
    terminal = run["status"] in ("succeeded", "failed", "refused")
    head = (f"<div class='{'ok' if run['status'] == 'succeeded' else 'sev-warn'}'>"
            f"{_e(run['status'].upper())} — {_e(run['outcome'] or 'in progress')}</div>"
            if terminal else
            "<div class='muted'>Running. This page refreshes itself; the deployment continues "
            "even while the Console restarts.</div>")
    rows = []
    for st in steps:
        mark = {"ok": "✅", "failed": "❌", "running": "…", "skipped": "—"}.get(st["status"], "·")
        detail = (f"<details><summary class='muted'>detail</summary>"
                  f"<pre>{_e(st['detail'])}</pre></details>") if st.get("detail") else ""
        rows.append(f"<div class='card'><div>{mark} <b>{_e(st['name'])}</b> — "
                    f"{_e(st['summary'])}</div><div class='muted'>{_e(st['at'])}</div>"
                    f"{detail}</div>")
    refresh = "" if terminal else "<script>setTimeout(()=>location.reload(), 4000)</script>"
    return (_section(f"Deploy #{run['id']} — {_e(run['sha'][:12])}", head + "".join(rows))
            + refresh)


# --- WP-U4d.2: the Console-driven acceptance (Acceptance B) -------------------------------

def acceptance_body(runs: list[dict], *, csrf: str, offered: bool, disabled_reason: str,
                    notice: str = "", error: str = "") -> str:
    """The acceptance list. History always renders; the control that LAUNCHES a run appears
    only when the operation is enabled — and the form carries no input the run could use:
    the browser selects the closed operation, nothing else."""
    head = ""
    if notice:
        head += f"<div class='ok'>{_e(notice)}</div>"
    if error:
        head += f"<div class='sev-warn'>{_e(error)}</div>"

    preview = (
        "<div class='muted'>Runs the bounded disposable deployment acceptance on this host: a "
        "throwaway target under <code>/srv/tc-u4d-acceptance</code> with its own repository, "
        "store, service unit and port. The run installs nothing into production, refuses every "
        "production value before its first mutation, deploys, injects a failure, rolls back, "
        "and records every phase here as append-only evidence. The verdict is PASS, FAILED "
        "SAFELY or BLOCKED — a phase that did not run is never reported as success.</div>")
    if offered:
        form = (
            "<form method='post' action='/acceptance/run' style='margin-top:10px'>"
            f"<input type='hidden' name='csrf' value='{_e(csrf)}'>"
            "<button type='submit'>Run deployment acceptance</button>"
            "<div class='muted' style='margin-top:4px'>You will confirm on the next page before "
            "anything runs. The browser supplies nothing but this click — every path, service "
            "and port is derived on the server and refused if it is production's.</div>"
            "</form>")
    else:
        form = f"<div class='muted' style='margin-top:10px'>{_e(disabled_reason)}</div>"

    rows = []
    for r in runs:
        verdict = r.get("verdict") or ""
        badge = {"PASS": "ok"}.get(verdict, "sev-warn" if verdict else "muted")
        state = verdict or r["status"]
        rows.append(
            f"<div class='card'><div><b>Acceptance #{r['id']}</b> — "
            f"<span class='{badge}'>{_e(state)}</span></div>"
            f"<div class='muted'>requested {_e(r['requested_at'])} by {_e(r['requested_by'])}"
            f" · {_e(r['root'])}</div>"
            f"<div>{_e(r.get('summary') or '')}</div>"
            f"<div><a href='/acceptance/{r['id']}'>Open →</a></div></div>")
    body = head + _section("Run deployment acceptance", preview + form)
    body += _section("Acceptance history", "".join(rows) or
                     "<div class='muted'>No acceptance runs recorded yet.</div>")
    return body


def acceptance_confirm_body(*, csrf: str) -> str:
    """The explicit approval step. The first POST rendered this page and mutated NOTHING; only
    the confirmed POST below creates the run row and launches the detached runner."""
    return _section(
        "Confirm: run deployment acceptance",
        "<div class='sev-warn'><b>This runs real host mutations</b> — against a disposable "
        "target only. It creates a throwaway tree under <code>/srv/tc-u4d-acceptance</code>, "
        "deploys to it through the privileged boundary, injects a failure and rolls back. "
        "Production paths, the production service, store and sudoers are refused by value "
        "before anything is created.</div>"
        "<div class='muted' style='margin-top:8px'>At most one acceptance runs at a time. The "
        "run continues in its own process whatever happens to the Console, and every phase is "
        "recorded as append-only evidence.</div>"
        "<form method='post' action='/acceptance/run' style='margin-top:12px'>"
        f"<input type='hidden' name='csrf' value='{_e(csrf)}'>"
        "<input type='hidden' name='confirmed' value='1'>"
        "<button type='submit'>Yes — run the acceptance</button> "
        "<a href='/acceptance'>Cancel</a></form>")


def acceptance_run_body(run: dict, phases: list[dict]) -> str:
    """The observation view. Everything on this page is a read of the durable record, which is
    why a restarted Console reconnects to the same run instead of orphaning it. The verdict
    banner renders ONLY a terminal verdict — a live run shows RUNNING, never a provisional
    success."""
    terminal = run["status"] == "done"
    if terminal:
        verdict = run.get("verdict") or "BLOCKED"
        cls = "ok" if verdict == "PASS" else "sev-warn"
        head = (f"<div class='{cls}'><b>{_e(verdict)}</b> — "
                f"{_e(run.get('summary') or '')}</div>")
    else:
        head = ("<div class='muted'>RUNNING. This page refreshes itself from the durable "
                "record; the run continues even while the Console restarts.</div>")
    rows = []
    for ph in phases:
        mark = {"ok": "✅", "deferred": "⏸", "failed": "❌", "refused": "❌"}.get(ph["status"], "·")
        detail = (f"<details><summary class='muted'>detail</summary>"
                  f"<pre>{_e(ph['detail'])}</pre></details>") if ph.get("detail") else ""
        rows.append(f"<div class='card'><div>{mark} <b>{_e(ph['name'])}</b> — "
                    f"{_e(ph['status'])}</div><div class='muted'>{_e(ph['at'])}</div>"
                    f"{detail}</div>")
    if not rows:
        rows.append("<div class='muted'>No phases recorded yet.</div>")
    refresh = "" if terminal else "<script>setTimeout(()=>location.reload(), 4000)</script>"
    return (_section(f"Acceptance #{run['id']} — {_e(run['root'])}", head + "".join(rows))
            + refresh)
