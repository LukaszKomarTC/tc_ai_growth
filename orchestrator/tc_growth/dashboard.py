"""Private web dashboard (Phase 2, slice 8) — a thin, READ-ONLY view over the store.

Design constraints (from docs/ROADMAP.md):
- Read-first: this server implements GET only. There are no mutating endpoints AT ALL, so it
  cannot become a write path into anything. Approvals/actions come later, deliberately.
- Isolated: binds to 127.0.0.1 by default. Remote access goes through an SSH tunnel
  (`ssh -L 8383:127.0.0.1:8383 user@vps`), so authentication is your SSH key — no hand-rolled
  login to get wrong, nothing new exposed on the box.
- Thin: stdlib http.server, server-rendered HTML, zero new dependencies. It is a *view* over the
  memory layer; the store stays the source of truth.

Run: python -m tc_growth.cli dashboard [port]
"""

from __future__ import annotations

import html
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from .config import BASE_DIR, get_settings, site_label
from .store import Store, open_store, resolved_db_path

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

_STYLE = """
body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:60rem;padding:0 1rem;color:#1a1a1a}
h1{font-size:1.4rem} h2{font-size:1.1rem;margin-top:2rem;border-bottom:1px solid #ddd;padding-bottom:.3rem}
table{border-collapse:collapse;width:100%;font-size:.9rem} td,th{padding:.35rem .6rem;text-align:left;border-bottom:1px solid #eee}
th{color:#666;font-weight:600} a{color:#0a5} .muted{color:#888} pre{white-space:pre-wrap;background:#f7f7f7;padding:1rem;border-radius:6px;font-size:.85rem}
.badge{display:inline-block;padding:.1rem .5rem;border-radius:9px;font-size:.75rem;background:#eee}
.badge.open,.badge.monitoring,.badge.proposed{background:#fff3cd}
.badge.resolved,.badge.closed,.badge.approved{background:#d4edda}.badge.rejected{background:#f8d7da}
.trail{font-size:1.05rem;margin:.5rem 0}.trail b{color:#0a5}
footer{margin-top:3rem;color:#aaa;font-size:.8rem}
"""


def _e(value) -> str:
    return html.escape(str(value if value is not None else "—"))


def _site_banner() -> str:
    """Unmistakable STAGING/PRODUCTION marker on every page — profiles must never be confused."""
    s = get_settings()
    kind = (s.env_kind or "staging").strip().lower()
    color = "#b32d2e" if kind == "production" else "#996b00"
    return (f"<div style='background:{color};color:#fff;padding:.4rem .8rem;border-radius:6px;"
            f"font-weight:600;margin-bottom:1rem'>{_e(site_label(s))}"
            f"{' · READ-ONLY PROFILE' if not s.allow_writes else ''}</div>")


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{_e(title)}</title>"
            f"<style>{_STYLE}</style></head><body><h1>{_e(title)}</h1>{_site_banner()}{body}"
            f"<footer>TC Growth — read-only dashboard · store: {_e(resolved_db_path())}</footer>"
            "</body></html>")


def deployment_info() -> dict:
    """Current commit + recent auto-deploy log lines (GitOps observability, read-only)."""
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
    try:
        log_lines = (BASE_DIR / "data" / "autodeploy.log").read_text().splitlines()[-4:]
    except OSError:
        log_lines = []
    return {"commit": sha or "—", "log": log_lines}


def render_overview(s: Store) -> str:
    cases = s.list_cases(limit=50)
    runs = s.list_runs(limit=15)
    decisions = s.list_decisions(limit=15)

    case_rows = "".join(
        f"<tr><td><a href='/case/{_e(c.ref or c.id)}'>{_e(c.ref or f'#{c.id}')}</a></td>"
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
    dec_rows = "".join(
        f"<tr><td>D#{_e(d.id)}</td><td>{_e(d.made_at)}</td>"
        f"<td><span class='badge {_e(d.status)}'>{_e(d.status)}</span></td><td>{_e(d.made_by)}</td>"
        f"<td>{_e(d.title)}</td>"
        f"<td>{f'<a href=/case/{_e(case_ref[d.case_id])}>{_e(case_ref[d.case_id])}</a>' if d.case_id in case_ref else _e(d.case_id)}</td></tr>"
        for d in decisions
    ) or "<tr><td colspan='6' class='muted'>no decisions logged</td></tr>"

    body = (
        "<p><a href='/validation'>Release 0.3 Validation Report</a></p>"
        "<h2>Cases</h2><table><tr><th>ref</th><th>status</th><th>priority</th><th>confidence</th>"
        f"<th>title</th><th>updated</th></tr>{case_rows}</table>"
        f"<h2>Recent runs <span class='muted'>(shown: ${total_cost:.4f})</span></h2>"
        "<table><tr><th>started</th><th>kind</th><th>status</th><th>model</th><th>cost</th>"
        f"<th>summary</th></tr>{run_rows}</table>"
        "<h2>Decision log <span class='muted'>(approve/reject via CLI: decision-approve &lt;id&gt;)</span></h2>"
        "<table><tr><th>id</th><th>made</th><th>status</th><th>by</th><th>title</th>"
        f"<th>case</th></tr>{dec_rows}</table>"
        f"{_deployment_section()}"
    )
    return _page("TC Growth — operations", body)


def _deployment_section() -> str:
    info = deployment_info()
    log_html = "".join(f"<div class='muted'>{_e(line)}</div>" for line in info["log"]) or \
               "<div class='muted'>(no auto-deploy log yet)</div>"
    return (f"<h2>Deployment</h2><p>Current commit: <b>{_e(info['commit'])}</b></p>{log_html}")


def render_validation() -> str:
    """Release 0.3 Validation Report — the acceptance record, rendered from docs/VALIDATION.md
    (the single source of truth; humans tick boxes there with dated evidence)."""
    from .validate import validation_status

    st = validation_status()
    if not st["total"]:
        return _page("Validation Report", "<p class='muted'>docs/VALIDATION.md not found.</p>")
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
        f"<p><a href='/'>&larr; overview</a></p>"
        f"<p class='trail'>Overall: <b>{st['done']}/{st['total']}</b> ({st['percent']}%) · "
        "production writes: <b>NOT ENABLED</b> · the checklist decides, not enthusiasm.</p>"
        + section_html
    )
    return _page("Release 0.3 — Validation Report", body)


def render_case(s: Store, key: str) -> str | None:
    case = s.get_case_by_ref(key)
    if case is None and key.lstrip("#").isdigit():
        case = s.get_case(int(key.lstrip("#")))
    if case is None:
        return None
    decisions = s.list_decisions(case_id=case.id)
    dec_html = "".join(
        f"<tr><td>D#{_e(d.id)}</td><td>{_e(d.made_at)}</td>"
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
        f"<p><a href='/'>&larr; overview</a></p>"
        f"<p><span class='badge {_e(case.status)}'>{_e(case.status)}</span> "
        f"priority {_e(case.priority)} · confidence {_e(case.confidence)} · "
        f"opened by {_e(case.opened_by)} · updated {_e(case.updated_at)}</p>"
        f"{trail_html}"
        f"<h2>Narrative</h2><pre>{_e(case.body or '(empty)')}</pre>"
        f"<h2>Linked decisions</h2><table><tr><th>id</th><th>made</th><th>status</th><th>by</th><th>title</th></tr>{dec_html}</table>"
    )
    return _page(f"{case.ref or f'#{case.id}'} — {case.title}", body)


class _Handler(BaseHTTPRequestHandler):
    """GET-only by construction — the class defines no other HTTP method handlers."""

    def do_GET(self):  # noqa: N802 (http.server API)
        s = open_store()
        try:
            path = unquote(self.path.split("?", 1)[0])
            if path == "/" or path == "":
                doc = render_overview(s)
            elif path == "/validation":
                doc = render_validation()
            elif path.startswith("/case/"):
                doc = render_case(s, path[len("/case/"):].strip("/"))
            else:
                doc = None
            if doc is None:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"not found")
                return
            payload = doc.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
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
