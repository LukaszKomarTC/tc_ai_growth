"""Private web dashboard — a thin, READ-ONLY view over the store.

Design constraints (from docs/ROADMAP.md):
- Read-first: this server implements GET only. There are no mutating endpoints AT ALL, so it
  cannot become a write path into anything. Approvals/actions come later, deliberately, behind
  session auth + CSRF + actor audit (Operations Console, post-0.3).
- Isolated: binds to 127.0.0.1 by default. Remote access goes through an SSH tunnel or the
  authenticated reverse proxy.
- Thin: stdlib http.server, server-rendered HTML, zero new dependencies. It is a *view* over the
  memory layer; the store stays the source of truth.
- Request-scoped profiles: `/p/<profile>/...` renders any discovered profile's store READ-ONLY
  in the same process — the selected context travels in the URL, never in a mutable global
  (control-plane rule, 2026-07-13). Unknown profiles 404; a missing store renders a notice and
  is never created as a side effect of a GET.

Run: python -m tc_growth.cli dashboard [port]
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from .config import BASE_DIR, RELEASE, get_settings, site_label
from .store import Store, open_store, resolved_db_path
from .store.sqlite import SqliteStore

# Matches the journal lines case_set_confidence writes:
#   **2026-07-05T22:23:32+00:00 (agent):** Confidence 0.82 -> 0.96. Basis: ...
_CONF_LINE = re.compile(
    r"\*\*(?P<ts>[0-9T:+.\-]+) \((?P<author>\w+)\):\*\* Confidence (?P<frm>\S+) -> "
    r"(?P<to>.+?)\.(?: Basis: (?P<basis>[^\n]*))?$",
    re.MULTILINE,
)


def confidence_trail(body: str | None) -> list[dict]:
    """Extract the confidence-evolution ladder from a case's append-only journal.

    The data already lives in the narrative (every case_set_confidence appends a timestamped
    'Confidence X -> Y. Basis: ...' line); this renders it as structure without any schema change.
    """
    if not body:
        return []
    return [
        {"ts": m.group("ts"), "author": m.group("author"), "from": m.group("frm"),
         "to": m.group("to"), "basis": (m.group("basis") or "").strip()}
        for m in _CONF_LINE.finditer(body)
    ]


# ---------------------------------------------------------------------------
# Profile contexts — read-only, request-scoped, never a mutable global.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfileCtx:
    """Everything a page needs to render one profile's data without touching os.environ."""

    name: str            # "default" (the process profile) or a profiles/*.env stem
    label: str           # e.g. "Tossa Cycling · PRODUCTION"
    env_kind: str        # staging | production
    allow_writes: bool
    db_path: str


# The only keys we ever read from a profile file. Everything else (credentials, SMTP,
# API keys) is deliberately never parsed into this process's page-rendering path.
_PROFILE_KEYS = ("TC_SITE_NAME", "TC_ENV_KIND", "TC_ALLOW_WRITES", "TC_DB_PATH")


def _parse_profile_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in _PROFILE_KEYS:
            out[key] = value.split("#", 1)[0].strip().strip('"').strip("'")
    return out


def list_profiles() -> list[str]:
    """'default' (the running process's profile) plus every profiles/*.env on disk."""
    names = ["default"]
    profiles_dir = BASE_DIR / "profiles"
    if profiles_dir.is_dir():
        names += sorted(p.stem for p in profiles_dir.glob("*.env"))
    return names


def profile_ctx(name: str) -> ProfileCtx | None:
    """Resolve a profile name to a read-only context. Unknown names -> None (the page 404s)."""
    if name == "default":
        s = get_settings()
        return ProfileCtx(
            name="default", label=site_label(s),
            env_kind=(s.env_kind or "staging").strip().lower(),
            allow_writes=bool(s.allow_writes), db_path=str(resolved_db_path()),
        )
    env_file = BASE_DIR / "profiles" / f"{name}.env"
    if not env_file.is_file():
        return None
    vals = _parse_profile_env(env_file)
    kind = (vals.get("TC_ENV_KIND") or "staging").strip().lower()
    site_name = vals.get("TC_SITE_NAME") or name
    db = vals.get("TC_DB_PATH") or str(BASE_DIR / "data" / f"tc_growth-{name}.db")
    if not Path(db).is_absolute():
        db = str(BASE_DIR / db)
    allow = (vals.get("TC_ALLOW_WRITES") or "true").strip().lower() not in ("false", "0", "no")
    return ProfileCtx(name=name, label=f"{site_name} · {kind.upper()}",
                      env_kind=kind, allow_writes=allow, db_path=db)


def _u(ctx: ProfileCtx | None, path: str) -> str:
    """Profile-aware URL: the selected context travels in every link."""
    if ctx is None or ctx.name == "default":
        return path or "/"
    return f"/p/{ctx.name}{path or '/'}"


_STYLE = """
body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:60rem;padding:0 1rem;color:#1a1a1a}
h1{font-size:1.4rem} h2{font-size:1.1rem;margin-top:2rem;border-bottom:1px solid #ddd;padding-bottom:.3rem}
table{border-collapse:collapse;width:100%;font-size:.9rem} td,th{padding:.35rem .6rem;text-align:left;border-bottom:1px solid #eee}
th{color:#666;font-weight:600} a{color:#0a5} .muted{color:#888} pre{white-space:pre-wrap;background:#f7f7f7;padding:1rem;border-radius:6px;font-size:.85rem}
.badge{display:inline-block;padding:.1rem .5rem;border-radius:9px;font-size:.75rem;background:#eee}
.badge.open,.badge.monitoring,.badge.proposed{background:#fff3cd}
.badge.resolved,.badge.closed,.badge.approved{background:#d4edda}.badge.rejected{background:#f8d7da}
.trail{font-size:1.05rem;margin:.5rem 0}.trail b{color:#0a5}
nav{margin:.2rem 0 .8rem;font-size:.9rem} nav a{margin-right:1rem}
.tiles{display:flex;gap:.8rem;flex-wrap:wrap;margin:1rem 0}
.tile{flex:1;min-width:9rem;border:1px solid #e3e3e3;border-radius:8px;padding:.6rem .8rem}
.tile .k{font-size:.72rem;color:#888;text-transform:uppercase;letter-spacing:.06em}
.tile .v{font-size:1.25rem;font-weight:650}
.switch{font-size:.8rem;color:#666;margin:-.6rem 0 1rem}.switch b{color:#333}
footer{margin-top:3rem;color:#aaa;font-size:.8rem}
"""


def _e(value) -> str:
    return html.escape(str(value if value is not None else "—"))


def _site_banner(ctx: ProfileCtx | None = None) -> str:
    """Unmistakable STAGING/PRODUCTION marker on every page — profiles must never be confused."""
    if ctx is None:
        ctx = profile_ctx("default")
    color = "#b32d2e" if ctx.env_kind == "production" else "#996b00"
    return (f"<div style='background:{color};color:#fff;padding:.4rem .8rem;border-radius:6px;"
            f"font-weight:600;margin-bottom:1rem'>{_e(ctx.label)}"
            f"{' · READ-ONLY PROFILE' if not ctx.allow_writes else ''}</div>")


def _switcher(ctx: ProfileCtx) -> str:
    links = []
    for name in list_profiles():
        if name == ctx.name:
            links.append(f"<b>{_e(name)}</b>")
        else:
            href = "/today" if name == "default" else f"/p/{name}/today"
            links.append(f"<a href='{_e(href)}'>{_e(name)}</a>")
    return "<div class='switch'>profile (read-only view): " + " · ".join(links) + "</div>"


def _nav(ctx: ProfileCtx) -> str:
    return ("<nav>"
            f"<a href='{_u(ctx, '/today')}'>Today</a>"
            f"<a href='{_u(ctx, '/activity')}'>Activity</a>"
            f"<a href='{_u(ctx, '/')}'>Overview</a>"
            f"<a href='{_u(ctx, '/validation')}'>Validation</a>"
            "</nav>")


def _page(title: str, body: str, ctx: ProfileCtx | None = None) -> str:
    ctx = ctx or profile_ctx("default")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{_e(title)}</title>"
            f"<style>{_STYLE}</style></head><body><h1>{_e(title)}</h1>{_site_banner(ctx)}"
            f"{_switcher(ctx)}{_nav(ctx)}{body}"
            f"<footer>TC Growth — read-only dashboard · profile: {_e(ctx.name)} · "
            f"store: {_e(ctx.db_path)}</footer>"
            "</body></html>")


def deployment_info() -> dict:
    """Deployment Report: release, current commit, last auto-deploy record, recent log lines.
    Every screenshot of the dashboard tells you exactly what you're looking at."""
    root = BASE_DIR.parent
    sha = ""
    try:
        head = (root / ".git" / "HEAD").read_text().strip()
        if head.startswith("ref:"):
            sha = (root / ".git" / head.split(" ", 1)[1].strip()).read_text().strip()[:9]
        else:
            sha = head[:9]
    except OSError:
        pass
    last = {}
    try:
        last = json.loads((BASE_DIR / "data" / "last_deploy.json").read_text())
    except (OSError, ValueError):
        pass
    try:
        log_lines = (BASE_DIR / "data" / "autodeploy.log").read_text().splitlines()[-4:]
    except OSError:
        log_lines = []
    return {"release": RELEASE, "commit": sha or "—", "last": last, "log": log_lines}


def today_data(s: Store) -> dict:
    """The owner's 8-second morning check, as data (also served as GET /api/today)."""
    cases = s.list_cases(limit=100)
    decisions = s.list_decisions(limit=100)
    runs = s.list_runs(limit=10)
    proposed = [d for d in decisions if d.status == "proposed"]
    awaiting = [d for d in decisions if d.status == "approved" and not (d.outcome or "").strip()]
    return {
        "cases_open": sum(1 for c in cases if c.status == "open"),
        "cases_monitoring": sum(1 for c in cases if c.status == "monitoring"),
        "decisions_proposed": len(proposed),
        "decisions_awaiting_outcome": len(awaiting),
        "last_run": ({"started_at": runs[0].started_at, "kind": runs[0].kind,
                      "summary": runs[0].summary} if runs else None),
        "proposed": [{"id": d.id, "title": d.title} for d in proposed],
        "awaiting": [{"id": d.id, "title": d.title} for d in awaiting],
        "recent_runs": [{"started_at": r.started_at, "kind": r.kind, "summary": r.summary}
                        for r in runs[:5]],
    }


def render_today(s: Store, ctx: ProfileCtx) -> str:
    d = today_data(s)
    last = d["last_run"]
    tiles = (
        "<div class='tiles'>"
        f"<div class='tile'><div class='k'>Needs you</div><div class='v'>{d['decisions_proposed']}</div></div>"
        f"<div class='tile'><div class='k'>Awaiting outcome</div><div class='v'>{d['decisions_awaiting_outcome']}</div></div>"
        f"<div class='tile'><div class='k'>Cases open</div><div class='v'>{d['cases_open']}</div></div>"
        f"<div class='tile'><div class='k'>Monitoring</div><div class='v'>{d['cases_monitoring']}</div></div>"
        f"<div class='tile'><div class='k'>Last run</div><div class='v' style='font-size:.85rem'>"
        f"{_e(last['kind']) + '<br>' + _e(last['started_at']) if last else '—'}</div></div>"
        "</div>"
    )
    attention_rows = "".join(
        f"<tr><td><a href='{_u(ctx, '/decision/' + str(x['id']))}'>D#{_e(x['id'])}</a></td>"
        f"<td><span class='badge proposed'>needs decision</span></td>"
        f"<td>{_e(x['title'])}</td></tr>" for x in d["proposed"]
    ) + "".join(
        f"<tr><td><a href='{_u(ctx, '/decision/' + str(x['id']))}'>D#{_e(x['id'])}</a></td>"
        f"<td><span class='badge approved'>approved · outcome?</span></td>"
        f"<td>{_e(x['title'])}</td></tr>" for x in d["awaiting"]
    )
    attention = (f"<h2>Needs your attention</h2><table><tr><th>id</th><th>state</th><th>title</th></tr>"
                 f"{attention_rows or '<tr><td colspan=3 class=muted>nothing — enjoy the ride 🚴</td></tr>'}</table>")
    runs_rows = "".join(
        f"<tr><td>{_e(r['started_at'])}</td><td>{_e(r['kind'])}</td><td>{_e(r['summary'])}</td></tr>"
        for r in d["recent_runs"]
    ) or "<tr><td colspan='3' class='muted'>no runs logged</td></tr>"
    recent = (f"<h2>Recent activity</h2><table><tr><th>started</th><th>kind</th><th>summary</th></tr>"
              f"{runs_rows}</table>")
    deploy = _deployment_section() if ctx.name == "default" else ""
    return _page("Today", tiles + attention + recent + deploy, ctx)


def render_overview(s: Store, ctx: ProfileCtx | None = None) -> str:
    ctx = ctx or profile_ctx("default")
    cases = s.list_cases(limit=50)
    runs = s.list_runs(limit=15)
    decisions = s.list_decisions(limit=15)

    case_rows = "".join(
        f"<tr><td><a href='{_u(ctx, f'/case/{_e(c.ref or c.id)}')}'>{_e(c.ref or f'#{c.id}')}</a></td>"
        f"<td><span class='badge {_e(c.status)}'>{_e(c.status)}</span></td>"
        f"<td>{_e(c.priority)}</td><td>{_e(c.confidence)}</td><td>{_e(c.title)}</td>"
        f"<td class='muted'>{_e(c.updated_at)}</td></tr>"
        for c in cases
    ) or "<tr><td colspan='6' class='muted'>no cases</td></tr>"

    total_cost = sum(r.cost_usd or 0 for r in runs)
    run_rows = "".join(
        f"<tr><td>{_e(r.started_at)}</td><td>{_e(r.kind)}</td><td>{_e(r.status)}</td>"
        f"<td>{_e(r.model)}</td><td>{'$%.4f' % r.cost_usd if r.cost_usd is not None else '—'}</td>"
        f"<td>{_e(r.summary)}</td></tr>"
        for r in runs
    ) or "<tr><td colspan='6' class='muted'>no runs logged</td></tr>"

    case_ref = {c.id: (c.ref or f"#{c.id}") for c in cases}

    def _case_cell(d) -> str:
        if d.case_id in case_ref:
            ref = _e(case_ref[d.case_id])
            return f"<a href='{_u(ctx, '/case/' + ref)}'>{ref}</a>"
        return _e(d.case_id)

    dec_rows = "".join(
        f"<tr><td><a href='{_u(ctx, '/decision/' + str(d.id))}'>D#{_e(d.id)}</a></td><td>{_e(d.made_at)}</td>"
        f"<td><span class='badge {_e(d.status)}'>{_e(d.status)}</span></td><td>{_e(d.made_by)}</td>"
        f"<td>{_e(d.title)}</td><td>{_case_cell(d)}</td></tr>"
        for d in decisions
    ) or "<tr><td colspan='6' class='muted'>no decisions logged</td></tr>"

    body = (
        "<h2>Cases</h2><table><tr><th>ref</th><th>status</th><th>priority</th><th>confidence</th>"
        f"<th>title</th><th>updated</th></tr>{case_rows}</table>"
        f"<h2>Recent runs <span class='muted'>(shown: ${total_cost:.4f})</span></h2>"
        "<table><tr><th>started</th><th>kind</th><th>status</th><th>model</th><th>cost</th>"
        f"<th>summary</th></tr>{run_rows}</table>"
        "<h2>Decision log <span class='muted'>(approve/reject via CLI: decision-approve &lt;id&gt;)</span></h2>"
        "<table><tr><th>id</th><th>made</th><th>status</th><th>by</th><th>title</th>"
        f"<th>case</th></tr>{dec_rows}</table>"
        f"{_deployment_section() if ctx.name == 'default' else ''}"
    )
    return _page("TC Growth — operations", body, ctx)


def _deployment_section() -> str:
    info = deployment_info()
    last = info["last"]
    if last:
        result = last.get("result", "—")
        badge_cls = "approved" if result == "deployed" else "rejected"
        last_html = (f"<p><span class='badge {badge_cls}'>{_e(result)}</span> "
                     f"commit <b>{_e(str(last.get('commit', ''))[:9])}</b> · {_e(last.get('time'))} · "
                     f"tests: {_e(last.get('tests'))} · rollback to {_e(str(last.get('rollback_to', ''))[:9])} available</p>")
    else:
        last_html = "<p class='muted'>(no auto-deploy record yet — manual deploys so far)</p>"
    log_html = "".join(f"<div class='muted'>{_e(line)}</div>" for line in info["log"])
    return (f"<h2>Deployment</h2>"
            f"<p>Release <b>{_e(info['release'])}</b> · running commit <b>{_e(info['commit'])}</b></p>"
            f"{last_html}{log_html}")


def render_validation(ctx: ProfileCtx | None = None) -> str:
    """Release 0.3 Validation Report — the acceptance record, rendered from docs/VALIDATION.md
    (the single source of truth; humans tick boxes there with dated evidence)."""
    from .validate import validation_status

    ctx = ctx or profile_ctx("default")
    st = validation_status()
    if not st["total"]:
        return _page("Validation Report", "<p class='muted'>docs/VALIDATION.md not found.</p>", ctx)
    section_html = ""
    for s in st["sections"]:
        badge = ("<span class='badge approved'>PASS</span>" if s["pass"]
                 else f"<span class='badge proposed'>{s['done']}/{s['total']}</span>")
        items = "".join(
            f"<tr><td>{'✔' if i['done'] else '·'}</td><td>{_e(i['text'])}</td></tr>"
            for i in s["items"]
        )
        section_html += (f"<h2>{_e(s['name'])} {badge}</h2>"
                         f"<table><tr><th></th><th>item · evidence</th></tr>{items}</table>")
    body = (
        f"<p class='trail'>Overall: <b>{st['done']}/{st['total']}</b> ({st['percent']}%) · "
        "production writes: <b>NOT ENABLED</b> · the checklist decides, not enthusiasm.</p>"
        + section_html
    )
    return _page("Release 0.3 — Validation Report", body, ctx)


def render_case(s: Store, key: str, ctx: ProfileCtx | None = None) -> str | None:
    ctx = ctx or profile_ctx("default")
    case = s.get_case_by_ref(key)
    if case is None and key.lstrip("#").isdigit():
        case = s.get_case(int(key.lstrip("#")))
    if case is None:
        return None
    decisions = s.list_decisions(case_id=case.id)
    dec_html = "".join(
        f"<tr><td><a href='{_u(ctx, '/decision/' + str(d.id))}'>D#{_e(d.id)}</a></td><td>{_e(d.made_at)}</td>"
        f"<td><span class='badge {_e(d.status)}'>{_e(d.status)}</span></td>"
        f"<td>{_e(d.made_by)}</td><td>{_e(d.title)}</td></tr>"
        for d in decisions
    ) or "<tr><td colspan='5' class='muted'>none</td></tr>"

    # Confidence evolution — how certainty moved as evidence arrived.
    trail = confidence_trail(case.body)
    if trail:
        ladder = " &rarr; ".join(f"<b>{_e(t['to'])}</b>" for t in trail)
        start = _e(trail[0]["from"])
        steps = "".join(
            f"<li>{_e(t['from'])} &rarr; <b>{_e(t['to'])}</b> "
            f"<span class='muted'>({_e(t['ts'])}, {_e(t['author'])})</span>"
            f"{' — ' + _e(t['basis']) if t['basis'] else ''}</li>"
            for t in trail
        )
        trail_html = (f"<h2>Confidence evolution</h2><p class='trail'>{start} &rarr; {ladder}</p>"
                      f"<ul>{steps}</ul>")
    else:
        trail_html = ""

    body = (
        f"<p><span class='badge {_e(case.status)}'>{_e(case.status)}</span> "
        f"priority {_e(case.priority)} · confidence {_e(case.confidence)} · "
        f"opened by {_e(case.opened_by)} · updated {_e(case.updated_at)}</p>"
        f"{trail_html}"
        f"<h2>Narrative</h2><pre>{_e(case.body or '(empty)')}</pre>"
        f"<h2>Linked decisions</h2><table><tr><th>id</th><th>made</th><th>status</th><th>by</th><th>title</th></tr>{dec_html}</table>"
    )
    return _page(f"{case.ref or f'#{case.id}'} — {case.title}", body, ctx)


_JOURNAL_LINE = re.compile(r"^\*\*(?P<ts>[0-9T:+.\-]+) \((?P<author>\w+)\):\*\* (?P<text>.+)$",
                           re.MULTILINE)


def activity_feed(s: Store, limit: int = 60) -> list[dict]:
    """One chronological stream over what the store already knows: decisions, runs, and case
    journal entries. No new schema — the feed is a read-only merge, newest first."""
    events: list[dict] = []
    cases = s.list_cases(limit=100)
    for c in cases:
        ref = c.ref or f"#{c.id}"
        for m in _JOURNAL_LINE.finditer(c.body or ""):
            events.append({"ts": m.group("ts"), "who": m.group("author"),
                           "what": f"[{ref}] {m.group('text')[:180]}",
                           "link": f"/case/{ref}"})
    for d in s.list_decisions(limit=100):
        events.append({"ts": d.made_at, "who": d.made_by or "—",
                       "what": f"D#{d.id} {d.status}: {d.title}",
                       "link": f"/decision/{d.id}"})
        if (d.outcome or "").strip():
            events.append({"ts": d.made_at, "who": d.made_by or "—",
                           "what": f"D#{d.id} outcome recorded: {d.outcome[:120]}",
                           "link": f"/decision/{d.id}"})
    for r in s.list_runs(limit=50):
        events.append({"ts": r.started_at, "who": "agent",
                       "what": f"run {r.kind}: {(r.summary or '')[:140]}", "link": None})
    events.sort(key=lambda e: e["ts"] or "", reverse=True)
    return events[:limit]


def render_activity(s: Store, ctx: ProfileCtx) -> str:
    parts = []
    for ev in activity_feed(s):
        what = _e(ev["what"])
        if ev["link"]:
            what = "<a href='" + _u(ctx, ev["link"]) + "'>" + what + "</a>"
        parts.append(f"<tr><td class='muted'>{_e(ev['ts'])}</td><td>{_e(ev['who'])}</td>"
                     f"<td>{what}</td></tr>")
    rows = "".join(parts) or "<tr><td colspan='3' class='muted'>no activity yet</td></tr>"
    body = ("<p class='muted'>Everything the platform did or decided, newest first — decisions, "
            "outcomes, case journal entries, runs.</p>"
            f"<table><tr><th>when</th><th>who</th><th>what</th></tr>{rows}</table>")
    return _page("Activity", body, ctx)


def render_decision(s: Store, key: str, ctx: ProfileCtx | None = None) -> str | None:
    """Decision detail — the 'why am I seeing this?' page: what was decided, on what basis,
    by whom, with what outcome, linked to its case. Read-only; acting stays in the CLI until
    the authenticated write layer lands (post-0.3)."""
    ctx = ctx or profile_ctx("default")
    if not key.isdigit():
        return None
    d = s.get_decision(int(key))
    if d is None:
        return None
    case_html = "<span class='muted'>—</span>"
    if d.case_id:
        case = s.get_case(d.case_id)
        if case is not None:
            ref = _e(case.ref or f"#{case.id}")
            case_html = f"<a href='{_u(ctx, '/case/' + ref)}'>{ref}</a> — {_e(case.title)}"
    outcome_html = (f"<p><b>Outcome:</b> {_e(d.outcome)}</p>" if (d.outcome or "").strip()
                    else "<p class='muted'>No execution outcome recorded yet.</p>")
    act_hint = ""
    if d.status == "proposed":
        act_hint = (f"<p class='muted'>Act via CLI: <code>decision-approve {d.id} \"basis\"</code> · "
                    f"<code>decision-reject {d.id} \"basis\"</code> — dashboard buttons arrive with "
                    "the authenticated write layer (post-0.3).</p>")
    elif d.status == "approved" and not (d.outcome or "").strip():
        act_hint = (f"<p class='muted'>Approved, awaiting execution — record with CLI: "
                    f"<code>decision-outcome {d.id} worked \"evidence\"</code>.</p>")
    body = (
        f"<p><span class='badge {_e(d.status)}'>{_e(d.status)}</span> "
        f"made by {_e(d.made_by)} · {_e(d.made_at)}</p>"
        f"<h2>Basis / rationale</h2><pre>{_e(d.rationale or '(none recorded)')}</pre>"
        f"<h2>Linked case</h2><p>{case_html}</p>"
        f"<h2>Outcome</h2>{outcome_html}{act_hint}"
    )
    return _page(f"D#{d.id} — {d.title}", body, ctx)


def _open_ctx_store(ctx: ProfileCtx) -> Store | None:
    """Open a profile's store read-only-by-usage. NEVER create a database from a GET: a missing
    store renders a notice instead of silently materialising an empty file."""
    if ctx.name == "default":
        return open_store()
    if not Path(ctx.db_path).is_file():
        return None
    return SqliteStore(ctx.db_path)


class _Handler(BaseHTTPRequestHandler):
    """GET-only by construction — the class defines no other HTTP method handlers."""

    def _send(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802 (http.server API)
        path = unquote(self.path.split("?", 1)[0])

        # Request-scoped profile prefix: /p/<name>/...
        ctx_name = "default"
        m = re.match(r"^/p/([A-Za-z0-9._-]+)(/.*)?$", path)
        if m:
            ctx_name, path = m.group(1), (m.group(2) or "/")
        ctx = profile_ctx(ctx_name)
        if ctx is None:
            self._send(404, b"unknown profile", "text/plain; charset=utf-8")
            return

        if path == "/api/profiles":
            payload = json.dumps({"profiles": list_profiles(), "active": ctx.name}).encode()
            self._send(200, payload, "application/json; charset=utf-8")
            return

        s = _open_ctx_store(ctx)
        if s is None:
            doc = _page("Today", f"<p class='muted'>store not found at {_e(ctx.db_path)} — "
                                 "this profile has no database on this machine.</p>", ctx)
            self._send(200, doc.encode("utf-8"), "text/html; charset=utf-8")
            return
        try:
            if path == "/api/today":
                payload = json.dumps({"profile": ctx.name, "label": ctx.label,
                                      **today_data(s)}).encode()
                self._send(200, payload, "application/json; charset=utf-8")
                return
            if path in ("/", ""):
                doc = render_overview(s, ctx)
            elif path == "/today":
                doc = render_today(s, ctx)
            elif path == "/activity":
                doc = render_activity(s, ctx)
            elif path == "/validation":
                doc = render_validation(ctx)
            elif path.startswith("/case/"):
                doc = render_case(s, path[len("/case/"):].strip("/"), ctx)
            elif path.startswith("/decision/"):
                doc = render_decision(s, path[len("/decision/"):].strip("/"), ctx)
            else:
                doc = None
            if doc is None:
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            self._send(200, doc.encode("utf-8"), "text/html; charset=utf-8")
        finally:
            s.close()

    def log_message(self, fmt, *args):  # quiet by default; systemd/journal not needed for v1
        pass


def serve(host: str = "127.0.0.1", port: int = 8383) -> None:
    """Blocking server. host is loopback by default on purpose — see module docstring."""
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"TC Growth dashboard (read-only) on http://{host}:{port}  — Ctrl+C to stop")
    print(f"Remote access: ssh -L {port}:127.0.0.1:{port} <user>@<vps>  then open http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
