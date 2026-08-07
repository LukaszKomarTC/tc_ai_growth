"""Operations Console — the loopback UI half of WP-CONSOLE-MVP slice 1.

The Console is the HUMAN client of the origin-agnostic Execution Service (`core.executor`).
It lists the Action Registry's operations, previews one, and executes it with the step-by-step
output streamed live — getting the operator off the terminal for the exact workflows the
2026-07-27 incident forced by hand (SMTP test, integrity scan, backup verify...).

Security posture — this is a privileged EXECUTION surface, built the week of a breach:
- **Loopback only.** Binds 127.0.0.1; remote access is an SSH tunnel, never a public port.
- **Fail closed.** Refuses to start unless TC_CONSOLE_TOKEN is set — an execution surface with
  no auth secret must not run.
- **Session auth + CSRF.** A shared token unlocks a signed, expiring session cookie
  (HttpOnly, SameSite=Strict); every state-changing POST also carries a CSRF token.
- **Registry-governed.** The executor may run ONLY Action Registry operations, under the phase
  gate; there is no free-form command field anywhere and op ids are validated server-side.
- **Everything logged.** Each execution writes a run record (actor, op, steps, output) via the
  Execution Service — the Console adds no second execution authority.

No chat. No "Ask AI." The panels are Operations · Evidence · Cases · Logs (the read panels defer
to the existing read-only dashboard). Run: python -m tc_growth.cli console [port]
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import re
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote

from . import deploy_target
from .core.actions import OPERATIONS, validate_registry
from .core.approval import Phase
from .core.executor import Executor, StepEvent

_SESSION_COOKIE = "tc_console"
_SESSION_MAX_AGE = 12 * 3600  # a shift; re-auth after that
_TOKEN_ENV = "TC_CONSOLE_TOKEN"
# U1 defect (2026-08-03): a clean integrity scan writes ~nothing to stdout for its whole ~2-minute
# run, so the execute stream carried ZERO bytes — and an idle connection through the operator's
# NAT/SSH-tunnel path was silently dropped. Both ends kept waiting: the browser showed "Running…"
# forever while the backend completed and recorded evidence. The stream must therefore NEVER go
# silent: an SSE comment frame (": keepalive") every few seconds keeps every middlebox alive. The
# client's frame parser skips blocks with no "data:" line, so keepalives are invisible to the UI
# logic (but still tick the elapsed indicator, because bytes arrived).
_KEEPALIVE_S = 10.0
_KEEPALIVE_FRAME = b": keepalive\n\n"  # SSE comment — MUST start with ':' so clients ignore it

# U4a decision actions: POST /decision/<id>/<act>. Outcome text is server-fixed and selected by
# WHITELISTED query keys only — the redirect target can never carry reflected content.
# WP-U4d. Server-fixed text, whitelisted by key — the URL can never inject a message.
_DEPLOY_RUN = re.compile(r"^/deploy/(\d+)$")
_DEPLOY_START = re.compile(r"^/deploy/(\d+)/start$")
_DEPLOY_NOTICES = {
    "planned": "Deployment plan created. Read it in full — including the steps that cannot be "
               "undone — before authorizing.",
    "started": "Deployment authorized and running in its own process. It continues even while "
               "the Console restarts.",
}
_DEPLOY_ERRORS = {
    "sha": "That is not an exact 40-character commit SHA. Branch names, short SHAs and refs are "
           "refused, because a deployment target must mean the same thing tomorrow.",
    "not-offered": "Deployment from the browser is not enabled yet — it must prove its full path "
                   "on a disposable target first (issue #77).",
    "digest": "That authorization did not match the plan you were shown. Open the plan again and "
              "read it before authorizing.",
    "state": "That deployment is not waiting to be authorized.",
    "internal": "Something went WRONG INSIDE THE CONSOLE — this is a defect, not a policy "
                "refusal. It has been recorded in Evidence.",
}

# WP-U4d.2. Same discipline as the deploy surface: whitelisted keys, server-fixed text.
_ACCEPTANCE_RUN = re.compile(r"^/acceptance/(\d+)$")
_ACCEPTANCE_NOTICES = {
    "started": "Acceptance run launched in its own process. This page follows it from the "
               "durable record, so it survives anything that happens to the Console.",
}
_ACCEPTANCE_ERRORS = {
    "not-offered": "Running the acceptance from the browser is not enabled yet — the operation "
                   "is registered for review and stays refused until the privileged verb it "
                   "launches exists on the host and the enabling flip is itself reviewed "
                   "(WP-U4d.2).",
    "busy": "An acceptance run is already live. There is at most one at a time — it mutates "
            "real host state, and two interleaved runs would corrupt each other's evidence.",
    "internal": "Something went WRONG INSIDE THE CONSOLE — this is a defect, not a policy "
                "refusal. It has been recorded in Evidence.",
}

_DECISION_ACT = re.compile(
    r"^/decision/(\d+)/(approve|reject|unapprove|verify|verify-confirm|adopt-live)$")
_DECISION_NOTICES = {
    "approved": "Approved. The envelope is now bound and immutable.",
    "already-approved": "Already approved — nothing changed (duplicate submission is safe).",
    "rejected": "Rejected. The reason is recorded in the history below.",
    "unapproved": "Unapproved — back to proposed; the envelope can be revised again.",
    "verify-pending": "Read #1 matched the approved envelope. Confirm arms after the minimum "
                      "interval — reload this page in about a minute.",
    "executed": "Verified twice against the live pages — this decision is now EXECUTED and "
                "has left the queue. The evidence trail is below.",
    "adopted": "New proposal created from the live page content you reviewed — it is waiting "
               "for your approval. Nothing on this decision changed.",
    "already-adopted": "This exact live content was already adopted — showing that proposal "
                       "instead of creating a duplicate.",
}
_DECISION_ERRORS = {
    "stale": "This page was stale — the decision changed underneath it. Review the current "
             "state below before acting again.",
    "not-approvable": "This decision has no bound envelope (it predates the workflow) — "
                      "nothing to approve.",
    "invalid-transition": "That action does not apply to the decision's current state.",
    "reason-required": "A rejection reason is required — nothing was changed.",
    "verify-mismatch": "The live pages do NOT match the approved envelope — the decision stays "
                       "approved, and the mismatch is recorded below. Check the pages in WP "
                       "and verify again.",
    "verify-error": "A page could not be fetched — nothing was concluded. The attempt is "
                    "recorded below; try again.",
    "verify-too-soon": "The confirm step is not armed yet — the minimum interval between the "
                       "two reads has not passed.",
    "verify-no-pending": "There is no matching first read to confirm — run Verify live change "
                         "first.",
    "verify-unavailable": "Verification is not available for this decision.",
    "adopt-failed": "Could not adopt the live content — the pages could not be read in full. "
                    "Nothing was created; try the comparison again.",
    "adopt-changed": "The live content CHANGED since the comparison you were shown — nothing "
                     "was created. Compare again and review the current wording before "
                     "adopting it.",
    "adopt-token": "That adopt request did not carry a valid reference to the comparison you "
                   "were shown — nothing was created. Run the comparison again.",
    "internal": "Something went WRONG INSIDE THE CONSOLE — this is a defect, not a policy "
                "refusal. Nothing was created. It is recorded in Evidence with the details; "
                "please report it rather than retrying blindly.",
    "unknown": "The action could not be completed — nothing was changed. Check the state below.",
}

# Self-only CSP: no external scripts, styles, fonts, images, or connections — the console must
# not be able to fetch anything off-box (defence for a surface that runs privileged operations).
_CSP = ("default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'")


def _e(s: object) -> str:
    return html.escape(str(s), quote=True)


# Absolute paths only: the lookbehind stops the pattern matching the middle of a RELATIVE path
# (wp-content/uploads/x.php must pass through untouched — F3 regression).
_ABS_PATH = re.compile(r"(?<![\w.\-])(?:/[\w.\-]+){2,}")
# Meaningful WordPress-relative markers to PRESERVE — redaction strips the server-mount prefix but
# keeps the diagnostically important tail, so 'uploads' vs 'mu-plugins' vs 'wp-includes' survives.
_KEEP_FROM = ("wp-content", "wp-includes", "mu-plugins", "uploads", "themes", "plugins",
              "wp-config.php")


def _redact(text: str) -> str:
    """Reduce SERVER LAYOUT before it reaches the browser without destroying evidence. Full
    provenance (absolute paths) stays in the evidence STORE; the UI keeps the meaningful
    WordPress-relative tail (…/wp-content/uploads/x.php stays distinct from …/wp-content/mu-plugins/x)
    but drops the mount prefix. A path with no marker collapses to a basename. Profile/environment
    are shown as their own fields elsewhere, so 'production vs staging' is never lost to redaction."""
    def _repl(m: re.Match[str]) -> str:
        p = m.group(0)
        for marker in _KEEP_FROM:
            i = p.find("/" + marker)
            if i != -1:
                return "…" + p[i:]
        return "…/" + p.rsplit("/", 1)[-1]
    return _ABS_PATH.sub(_repl, text or "")


# --- auth: shared token -> signed, expiring session cookie + CSRF -------------------------


def _secret() -> bytes | None:
    tok = os.environ.get(_TOKEN_ENV, "").strip()
    return tok.encode("utf-8") if tok else None


def _sign(secret: bytes, msg: str) -> str:
    # The KEY is always the high-entropy secret (TC_CONSOLE_TOKEN). The deploy commit is only ever
    # part of the signed MESSAGE (see below), never the key — a git commit is public and must not
    # be a security secret. Model: HMAC(secret, data + deploy_commit). Do NOT swap these.
    return hmac.new(secret, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def _deploy_epoch() -> str:
    """A deploy identity mixed into the signed MESSAGE (not the key) so a REDEPLOY invalidates
    existing sessions — a code change on a privileged execution surface is a natural point to force
    re-auth. It is an EPOCH value, not the secret: security still rests on TC_CONSOLE_TOKEN. Pinned
    per deployment via TC_BUILD_COMMIT; stable ('dev') in a working tree. (MVP forces logout on
    every redeploy; a later explicit session-epoch could spare harmless redeploys.)"""
    return os.environ.get("TC_BUILD_COMMIT", "dev")


def issue_session(secret: bytes, *, now: float | None = None) -> str:
    """A session token `<issued_ts>.<sig>` that only a holder of the shared secret can mint.
    The signature is bound to the deploy epoch, so a redeploy invalidates prior sessions."""
    ts = str(int(now if now is not None else time.time()))
    return f"{ts}.{_sign(secret, f'session.{_deploy_epoch()}.{ts}')}"


def valid_session(value: str | None, secret: bytes, *, now: float | None = None) -> bool:
    if not value or "." not in value:
        return False
    ts_str, sig = value.split(".", 1)
    if not ts_str.isdigit():
        return False
    expected = _sign(secret, f"session.{_deploy_epoch()}.{ts_str}")
    if not hmac.compare_digest(sig, expected):
        return False
    age = (now if now is not None else time.time()) - int(ts_str)
    return 0 <= age <= _SESSION_MAX_AGE


def adopt_token(secret: bytes, *, fetched_at: str, digest: str) -> str:
    """Bind the snapshot the owner is LOOKING AT to the adopt form (review #76 TOCTOU fix).
    Carries the fetch time and the content digest, signed with the console secret + deploy
    epoch — the browser cannot forge or edit either half."""
    return f"{fetched_at}|{digest}|{_sign(secret, f'adopt.{_deploy_epoch()}.{fetched_at}.{digest}')}"


def read_adopt_token(token: str | None, secret: bytes) -> tuple[str, str] | None:
    """(fetched_at, digest) for a valid token; None when absent, malformed or tampered."""
    parts = (token or "").split("|")
    if len(parts) != 3:
        return None
    fetched_at, digest, sig = parts
    expected = _sign(secret, f"adopt.{_deploy_epoch()}.{fetched_at}.{digest}")
    return (fetched_at, digest) if hmac.compare_digest(sig, expected) else None


def csrf_for(session_value: str, secret: bytes) -> str:
    return _sign(secret, f"csrf.{_deploy_epoch()}.{session_value}")


def valid_csrf(token: str | None, session_value: str, secret: bytes) -> bool:
    return bool(token) and hmac.compare_digest(token, csrf_for(session_value, secret))


# --- executor wiring ----------------------------------------------------------------------


def _console_phase() -> Phase:
    """Phase the Console runs the Execution Service at. READ_ONLY by default — slice 1 surfaces
    diagnostics (SMTP test, integrity scan); write/ALWAYS_ASK ops show as not-runnable in preview
    until the confirmation-step slice ships. Override with TC_CONSOLE_PHASE for supervised use."""
    raw = os.environ.get("TC_CONSOLE_PHASE", "").strip().lower()
    return {"drafts": Phase.DRAFTS, "controlled_execution": Phase.CONTROLLED_EXECUTION}.get(
        raw, Phase.READ_ONLY)


def _executor() -> Executor:
    # No confirm hook in the MVP: ALWAYS_ASK ops are refused (shown as needs-confirmation in the
    # preview) until the in-UI confirmation step is built. Never silently auto-confirm.
    return Executor(phase=_console_phase(), confirm=None)


# --- HTML ---------------------------------------------------------------------------------

_STYLE = """
:root { color-scheme: light dark; --bg:#0d1117; --panel:#161b22; --line:#30363d; --fg:#e6edf3;
  --muted:#8b949e; --ok:#3fb950; --err:#f85149; --warn:#d29922; --accent:#2f81f7; }
* { box-sizing: border-box; }
body { margin:0; font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg);
  color:var(--fg); }
header { padding:14px 20px; border-bottom:1px solid var(--line); display:flex; gap:18px;
  align-items:baseline; }
header h1 { font-size:15px; margin:0; font-weight:600; }
header .env { color:var(--muted); font-size:12px; }
.envbadge { font-size:11px; font-weight:700; letter-spacing:.06em; padding:3px 10px; border-radius:6px; }
.envbadge.prod { background:var(--err); color:#fff; }
.envbadge.stag { background:var(--warn); color:#0d1117; }
nav { display:flex; gap:4px; padding:8px 16px; border-bottom:1px solid var(--line); }
nav a { color:var(--muted); text-decoration:none; padding:6px 12px; border-radius:6px; font-size:13px; }
nav a.on { color:var(--fg); background:var(--panel); }
main { max-width:900px; margin:0 auto; padding:24px 20px; }
.op { border:1px solid var(--line); border-radius:8px; padding:14px 16px; margin-bottom:10px;
  background:var(--panel); display:flex; justify-content:space-between; align-items:center; gap:12px; }
.op .meta { color:var(--muted); font-size:12px; margin-top:3px; }
.op h3 { margin:0; font-size:14px; }
.badge { font-size:11px; padding:2px 7px; border-radius:20px; border:1px solid var(--line);
  color:var(--muted); }
.badge.write { color:#d29922; border-color:#d29922; }
.badge.ok { color:var(--ok); border-color:color-mix(in srgb, var(--ok) 45%, var(--line)); }
.badge.warn { color:var(--warn); border-color:color-mix(in srgb, var(--warn) 45%, var(--line)); }
.badge.err { color:var(--err); border-color:color-mix(in srgb, var(--err) 45%, var(--line)); }
button { font:inherit; cursor:pointer; border:1px solid var(--accent); background:var(--accent);
  color:#fff; padding:7px 14px; border-radius:6px; }
button.ghost { background:transparent; color:var(--accent); }
button:disabled { opacity:.4; cursor:not-allowed; }
/* U3b.1 hierarchy: the eye must land on the status card, then section headers, then detail. */
.statuscard { border-radius:10px; padding:18px 20px; margin-bottom:18px; border:1px solid; }
.statuscard.calm { background:color-mix(in srgb, var(--ok) 10%, var(--panel));
  border-color:color-mix(in srgb, var(--ok) 45%, var(--line)); }
.statuscard.act { background:color-mix(in srgb, var(--err) 9%, var(--panel));
  border-color:color-mix(in srgb, var(--err) 45%, var(--line)); }
.statuscard .lead { font-size:18px; font-weight:700; margin:0 0 4px; }
.statuscard .why { color:var(--muted); font-size:13px; }
section.card { border:1px solid var(--line); border-radius:8px; padding:14px 16px;
  margin-bottom:14px; background:var(--panel); }
section.card h2 { margin:0 0 10px; font-size:16px; font-weight:700; }
section.card > div { padding:3px 0; }
.sev-warn { border-left:3px solid var(--warn); padding-left:10px !important; }
.sev-err  { border-left:3px solid var(--err); padding-left:10px !important; }
#envtruth { color:var(--muted); font-size:12.5px; }
#envtruth .tag { min-width:150px; display:inline-block; }
.muted { color:var(--muted); }
.ok { color:var(--ok); } .err { color:var(--err); }
.tag { color:var(--muted); font-size:12px; }
.muted { color:var(--muted); }
.modal { position:fixed; inset:0; background:rgba(0,0,0,.6); display:none; align-items:center;
  justify-content:center; padding:20px; }
.modal.on { display:flex; }
/* Modal dialog card ONLY — scoped under .modal on purpose (U4a.2): the bare `.card` selector
   also matched every `section.card` content panel, silently clamping page sections to 560px
   with an inner 86vh scrollbar. On short pages it read as "narrow cards"; on the decisions
   history it compressed the list into a scroll-box-in-a-scroll-box. Page sections are styled
   by `section.card` above and must never inherit dialog geometry. */
.modal .card { background:var(--panel); border:1px solid var(--line); border-radius:10px;
  width:560px; max-width:100%; max-height:86vh; overflow:auto; }
.modal .card header { border-bottom:1px solid var(--line); }
.modal .card .body { padding:16px 18px; }
.modal .card .foot { padding:14px 18px; border-top:1px solid var(--line); display:flex;
  gap:10px; justify-content:flex-end; }
ul.actions { margin:8px 0; padding-left:18px; } ul.actions li { margin:2px 0; }
#stream { font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace; background:#0a0d12;
  border:1px solid var(--line); border-radius:8px; padding:12px; margin-top:12px; min-height:60px;
  white-space:pre-wrap; }
.step { display:block; } .step .ok{color:var(--ok);} .step .err{color:var(--err);}
.step .tag{color:var(--muted);}
.result { margin-top:10px; font-weight:600; } .result.ok{color:var(--ok);} .result.err{color:var(--err);}
.result.warn{color:var(--warn);}
input[type=password]{ font:inherit; padding:9px 12px; border-radius:6px; border:1px solid var(--line);
  background:var(--bg); color:var(--fg); width:100%; }
form.login { max-width:340px; margin:12vh auto; }
form.login h1 { font-size:16px; }
kbd{font:11px ui-monospace,monospace;background:var(--bg);border:1px solid var(--line);
  border-radius:4px;padding:1px 5px;}
"""


def _shell(title: str, active: str, body: str, *, site_name: str, env_kind: str) -> str:
    """Page chrome. F2 (VPS acceptance): the environment must be impossible to misread on an
    execution surface — PRODUCTION renders as a filled red badge, anything else amber. The badge
    derives from the profile's env_kind; set TC_ENV_KIND explicitly in the console's .env."""
    def _tab(name: str, href: str) -> str:
        on = " on" if active == name.lower() else ""
        return f'<a class="{on.strip()}" href="{href}">{name}</a>'
    # ONE tab per destination (U1: "Evidence" and "Logs" both pointed at /logs — a nav item that
    # takes you somewhere other than what it says is a truth defect on this surface).
    nav = "".join([
        _tab("Home", "/"), _tab("Decisions", "/decisions"), _tab("Operations", "/operations"),
        _tab("Evidence", "/logs"), _tab("Cases", "/cases"), _tab("Deploy", "/deploy"),
        _tab("Acceptance", "/acceptance"),
    ])
    kind = (env_kind or "staging").strip().lower()
    badge_cls = "prod" if kind == "production" else "stag"
    badge = f"<span class='envbadge {badge_cls}'>{_e(kind.upper())}</span>"
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_e(title)} — TC Operations Console</title><style>{_STYLE}</style></head><body>"
        f"<header><h1>TC Operations Console</h1><span class='env'>{_e(site_name)}</span>{badge}"
        "<form method='post' action='/logout' style='margin-left:auto'>"
        "<button class='ghost' type='submit'>Sign out</button></form></header>"
        f"<nav>{nav}</nav><main>{body}</main></body></html>"
    )


def _login_page(*, error: str = "") -> str:
    err = f"<p class='result err'>{_e(error)}</p>" if error else ""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Sign in — TC Operations Console</title><style>{_STYLE}</style></head><body>"
        "<form class='login' method='post' action='/login'>"
        "<h1>TC Operations Console</h1>"
        "<p class='muted'>Privileged execution surface. Enter the console token.</p>"
        f"{err}"
        "<input type='password' name='token' placeholder='Console token' autofocus autocomplete='off'>"
        "<p><button type='submit'>Sign in</button></p>"
        "<p class='muted' style='font-size:12px'>Loopback only · reached via SSH tunnel.</p>"
        "</form></body></html>"
    )


def _operations_body() -> str:
    ex = _executor()
    rows = []
    for op in OPERATIONS:
        # Off the generic operations surface: disabled ops, and ops with their OWN dedicated
        # surface (deploy → /deploy, acceptance → /acceptance). The latter must never be
        # runnable through the generic executor, which would invoke them with no arguments.
        if not op.enabled or not op.self_service:
            continue
        prev = ex.preview(op.id)
        badge = "<span class='badge write'>writes</span>" if prev.writes else "<span class='badge'>read-only</span>"
        approval = "" if prev.approval == "none" else f"<span class='badge'>{_e(prev.approval)}</span>"
        btn = (f"<button onclick=\"openPreview('{_e(op.id)}')\">Preview</button>"
               if prev.runnable_now
               else f"<button class='ghost' disabled title=\"{_e(prev.block_reason)}\">Unavailable</button>")
        rows.append(
            f"<div class='op'><div><h3>{_e(op.name)} {badge} {approval}</h3>"
            f"<div class='meta'>{_e(op.category)} · targets {_e('/'.join(op.environments))} · "
            f"<code>{_e(prev.binding)}</code></div></div><div>{btn}</div></div>"
        )
    listing = "".join(rows) or "<p class='muted'>No operations available.</p>"
    modal = """
<div class='modal' id='modal'><div class='card'>
  <header><h1 id='mTitle'>Operation</h1></header>
  <div class='body' id='mBody'></div>
  <div id='stream' style='display:none'></div>
  <div class='foot'>
    <span id='mPulse' class='tag'></span>
    <button class='ghost' onclick='closeModal()'>Close</button>
    <button id='mExec' onclick='execOp()'>Execute</button>
  </div>
</div></div>"""
    return listing + modal + _SCRIPT


_SCRIPT = """
<script>
let currentOp = null;
function h(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML;}
async function openPreview(op){
  currentOp = op;
  const r = await fetch('/api/preview?op='+encodeURIComponent(op));
  const p = await r.json();
  document.getElementById('mTitle').textContent = p.name;
  const actions = (p.expected_actions||'').split(';').map(s=>s.trim()).filter(Boolean);
  document.getElementById('mBody').innerHTML =
    "<p class='muted'>Target: <b>"+h(p.environments.join(' / '))+"</b> · "+
    (p.writes?"<b style='color:#d29922'>changes state</b>":"read-only, changes nothing")+"</p>"+
    "<p>Expected actions / verification:</p><ul class='actions'>"+
    actions.map(a=>"<li>"+h(a)+"</li>").join('')+"</ul>"+
    "<p class='muted' style='font-size:12px'>Binding: <code>"+h(p.binding)+"</code> · "+
    "approval: "+h(p.approval)+"</p>";
  const stream = document.getElementById('stream');
  stream.style.display='none'; stream.innerHTML='';
  const btn = document.getElementById('mExec');
  btn.disabled = !p.runnable_now; btn.textContent='Execute';
  if(!p.runnable_now){ btn.title = p.block_reason || 'not runnable now'; }
  document.getElementById('modal').classList.add('on');
}
function closeModal(){ document.getElementById('modal').classList.remove('on'); }
async function execOp(){
  // Button lifecycle (D4): Execute -> Running… -> Run again. The server closes the connection
  // after the final frame, so the read loop terminates; a network error also restores the button.
  const btn = document.getElementById('mExec'); btn.disabled=true; btn.textContent='Running…';
  const stream = document.getElementById('stream'); stream.style.display='block'; stream.innerHTML='';
  // Liveness indicator: ANY received bytes (step frames or server keepalives) bump lastByte.
  // The server pulses every ~10s, so >25s of silence is a genuinely stalled stream and the
  // indicator says so — a quiet-but-alive scan and a dead connection must look different.
  const pulse = document.getElementById('mPulse'); const t0 = Date.now(); let lastByte = Date.now();
  const tick = setInterval(()=>{
    const idle = (Date.now()-lastByte)/1000;
    pulse.textContent = 'running — '+Math.round((Date.now()-t0)/1000)+'s'
      + (idle > 25 ? ' · NO DATA for '+Math.round(idle)+'s — stream may be lost' : '');
  }, 1000);
  try {
    const res = await fetch('/api/execute', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'},
      body:'op='+encodeURIComponent(currentOp)+'&csrf='+encodeURIComponent(window.__CSRF__)});
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf='';
    while(true){
      const {value, done} = await reader.read(); if(done) break;
      lastByte = Date.now();
      buf += dec.decode(value, {stream:true});
      let idx;
      while((idx = buf.indexOf('\\n\\n')) >= 0){
        const frame = buf.slice(0, idx); buf = buf.slice(idx+2);
        const line = frame.split('\\n').find(l=>l.startsWith('data:'));
        if(!line) continue;
        const ev = JSON.parse(line.slice(5).trim());
        renderEvent(ev, stream);
      }
    }
  } catch (err) {
    stream.innerHTML += "<div class='result err'>CONNECTION LOST — "+h(String(err))+"</div>";
  } finally {
    clearInterval(tick); pulse.textContent='';
    btn.textContent='Run again'; btn.disabled=false;
  }
}
function renderEvent(ev, stream){
  if(ev.type==='step'){
    const mark = ev.status==='ok'?"<span class='ok'>✓</span>":
      ev.status==='error'?"<span class='err'>✗</span>":"<span class='tag'>·</span>";
    stream.innerHTML += "<span class='step'>"+mark+" "+h(ev.step)+
      (ev.detail?" <span class='tag'>— "+h(ev.detail)+"</span>":"")+"</span>";
  } else if(ev.type==='result'){
    // Severity, not exit code, drives the colour — and findings are 'completed', never 'failed'.
    const sevClass = {ok:'ok', attention:'warn', warn:'warn', error:'err'}[ev.severity] || 'warn';
    let label;
    if(ev.block_reason){ label = 'BLOCKED — ' + ev.block_reason; }
    else if(ev.execution_status==='error'){ label = 'EXECUTION ERROR'; }
    else if(ev.outcome==='findings'){ label = 'COMPLETED — FINDINGS'; }
    else if(ev.outcome==='warnings'){ label = 'COMPLETED — WARNINGS'; }
    else { label = 'COMPLETED — ' + (ev.outcome||'').toUpperCase(); }
    stream.innerHTML += "<div class='result "+sevClass+"'>"+h(label)+
      (ev.evidence_ref?" · evidence "+h(ev.evidence_ref):"")+
      (ev.duration_s!=null?" · "+h(ev.duration_s)+"s":"")+"</div>";
  }
  stream.scrollTop = stream.scrollHeight;
}
</script>"""



class _Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 so we can stream the execution with chunked transfer encoding.
    protocol_version = "HTTP/1.1"

    def handle_one_request(self) -> None:
        """WP-U4d.1. Latch this process as an HTTP server before the request is parsed.

        Placed here rather than in `do_GET`/`do_POST` because it must hold for every request the
        Console will ever see, including ones no handler recognises. Once latched, the deployment
        target seam is closed for the life of the process: no request — well-formed, malformed, or
        aimed at a route that does not exist — can put this process in a state where a target
        other than production could be constructed.
        """
        deploy_target.note_http_boundary()
        super().handle_one_request()

    # ---- low-level helpers ----
    def _headers(self, status: int, content_type: str, *, extra: list[tuple[str, str]] | None = None,
                 body_len: int | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Security-Policy", _CSP)
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or []):
            self.send_header(k, v)
        if body_len is not None:
            self.send_header("Content-Length", str(body_len))
        self.end_headers()

    def _send(self, status: int, payload: bytes, content_type: str,
              extra: list[tuple[str, str]] | None = None) -> None:
        self._headers(status, content_type, extra=extra, body_len=len(payload))
        self.wfile.write(payload)

    def _html(self, status: int, doc: str) -> None:
        self._send(status, doc.encode("utf-8"), "text/html; charset=utf-8")

    def _json(self, status: int, obj: dict) -> None:
        self._send(status, json.dumps(obj, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    # ---- auth ----
    def _session_value(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = SimpleCookie(raw)
        c = jar.get(_SESSION_COOKIE)
        return c.value if c else None

    def _authed(self, secret: bytes) -> str | None:
        val = self._session_value()
        return val if (val and valid_session(val, secret)) else None

    # ---- GET ----
    def do_GET(self):
        secret = _secret()
        if secret is None:
            self._send(503, b"console token not configured", "text/plain; charset=utf-8")
            return
        path = unquote(self.path.split("?", 1)[0])
        session = self._authed(secret)
        if session is None:
            self._html(200, _login_page())
            return

        if path == "/api/operations":
            self._json(200, {"operations": [
                {"id": op.id, "name": op.name}
                for op in OPERATIONS if op.enabled and op.self_service]})
            return
        if path == "/api/preview":
            op_id = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "").get("op", [""])[0]
            try:
                self._json(200, _executor().preview(op_id).as_dict())
            except KeyError:
                self._json(404, {"error": "unknown operation"})
            return

        from .config import active_site, get_settings
        s = get_settings()
        chrome = {"site_name": s.site_name or (active_site() or "Tossa Cycling"),
                  "env_kind": s.env_kind}
        if path in ("/", ""):
            # U3b: the landing page answers the owner's five questions (console_views.home_body);
            # the execute surface lives under /operations. Store trouble must degrade, not 500.
            from . import console_views
            from urllib.parse import urlparse

            try:
                from .store import open_store

                body = console_views.home_body(
                    open_store(), profile=chrome["site_name"], env_kind=s.env_kind,
                    wp_host=urlparse(s.wp_base_url).netloc if s.wp_base_url else "",
                    allow_writes=bool(s.allow_writes), redact=_redact)
            except Exception as exc:  # noqa: BLE001 - an empty home beats a dead console
                body = f"<p class='muted'>Home unavailable: {_e(_redact(str(exc)))}</p>"
            self._html(200, _shell("Home", "home", body, **chrome))
        elif path == "/operations":
            csrf = csrf_for(session, secret)
            body = f"<script>window.__CSRF__={json.dumps(csrf)};</script>" + _operations_body()
            self._html(200, _shell("Operations", "operations", body, **chrome))
        elif path == "/decisions":
            # U4a.1: the decision history — everything that ever entered the workflow stays
            # discoverable here after it leaves the homepage queue. Filter values are
            # whitelisted; anything else falls back to 'all'.
            from . import console_views

            q = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            wanted = q.get("status", ["all"])[0]
            status = wanted if wanted in console_views._DECISION_FILTERS else "all"
            try:
                from .store import open_store

                body = console_views.decisions_body(open_store(), status=status)
            except Exception as exc:  # noqa: BLE001 - degrade, never 500
                body = f"<p class='muted'>Decisions unavailable: {_e(_redact(str(exc)))}</p>"
            self._html(200, _shell("Decisions", "decisions", body, **chrome))
        elif path.startswith("/decision/"):
            # U4a: the decision detail page. Success/error state arrives as WHITELISTED keys in
            # the query string (PRG pattern — a refresh must never repeat a mutation), rendered
            # through fixed server-side text: nothing user-supplied is ever reflected.
            from . import console_views

            try:
                decision_id = int(path.rsplit("/", 1)[1])
            except ValueError:
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            from . import verify as verify_mod

            try:
                from .store import open_store

                store = open_store()
                decision = store.get_decision(decision_id)
                events = store.list_decision_events(decision_id) if decision else []
                attempts = store.list_verify_attempts(decision_id) if decision else []
                pending = (store.pending_verify_attempt(decision_id,
                                                        revision=decision.revision)
                           if decision and decision.status == "approved" else None)
            except Exception:  # noqa: BLE001 - store trouble -> not found, never 500
                decision = None
                events, attempts, pending = [], [], None
            if decision is None:
                self._send(404, b"no such decision", "text/plain; charset=utf-8")
                return
            q = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            notice = _DECISION_NOTICES.get(q.get("msg", [""])[0], "")
            error = _DECISION_ERRORS.get(q.get("err", [""])[0], "")
            # U4c: the live comparison is fetched ON REQUEST (?live=1) — a detail page must not
            # hit the site on every open. Failure renders as failure; no stale value is shown.
            comparison = snapshot = snap_token = None
            if q.get("live", [""])[0] == "1" and decision.envelope_sha256:
                try:
                    envelope = json.loads(decision.envelope or "")
                    snapshot = verify_mod.live_snapshot(envelope)
                    comparison = verify_mod.compare_fields(envelope, snapshot)
                    snap_token = adopt_token(
                        secret, fetched_at=snapshot["fetched_at"],
                        digest=verify_mod.snapshot_digest(
                            snapshot, source_id=decision.id, revision=decision.revision,
                            envelope_sha256=decision.envelope_sha256))
                except Exception as exc:  # noqa: BLE001 - a failed read is content, not a 500
                    snapshot = {"fetched_at": "—"}
                    comparison = [{"lang": "?", "label": "live read", "url": None,
                                   "proposed": "", "current": None,
                                   "error": _redact(f"{type(exc).__name__}: {exc}"),
                                   "same": False}]
            body = console_views.decision_body(
                decision, events, csrf=csrf_for(session, secret), notice=notice, error=error,
                verifiable=decision.kind in verify_mod.VERIFIABLE_KINDS,
                pending=pending,
                wait_s=verify_mod.confirm_wait_s(pending) if pending else 0,
                attempts=attempts, comparison=comparison, snapshot=snapshot,
                snapshot_token=snap_token)
            self._html(200, _shell(f"Decision D#{decision.id}", "decisions", body, **chrome))
        elif path == "/deploy" or _DEPLOY_RUN.match(path):
            # WP-U4d. Reading deployment history is never dangerous, so the page always renders;
            # the control that AUTHORIZES one appears only when the operation is enabled.
            from . import deploy as deploy_mod
            from .core.actions import get_operation
            from . import console_views  # noqa: F811 - function-local name in do_GET
            from .store import open_store  # noqa: F811 - same reason

            op = get_operation("deploy_release")
            offered = op.enabled
            reason = ("Deployment from the browser is not offered yet: this operation must "
                      "prove its full path on a disposable target before its first real use "
                      "(issue #77). Until then deployments are run from the terminal and "
                      "recorded here.")
            csrf = csrf_for(session, secret)
            q = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            notice = _DEPLOY_NOTICES.get(q.get("msg", [""])[0], "")
            error = _DEPLOY_ERRORS.get(q.get("err", [""])[0], "")
            m = _DEPLOY_RUN.match(path)
            try:
                store = open_store()
                if m:
                    run = store.get_deploy_run(int(m.group(1)))
                    if run is None:
                        self._send(404, b"no such deploy run", "text/plain; charset=utf-8")
                        return
                    if run["status"] == "planned":
                        plan = json.loads(run["plan"])
                        body = console_views.deploy_plan_body(
                            run, plan, deploy_mod.plan_text(plan), csrf=csrf, offered=offered,
                            notice=notice, error=error)
                    else:
                        body = console_views.deploy_run_body(
                            run, store.list_deploy_steps(run["id"]))
                    title = f"Deploy #{run['id']}"
                else:
                    body = console_views.deploy_body(
                        store.list_deploy_runs(limit=20), csrf=csrf, offered=offered,
                        disabled_reason=reason, notice=notice, error=error)
                    title = "Deploy"
            except Exception as exc:  # noqa: BLE001 - a defect, and it must say so. Rendered
                # in place, never redirected: a failing view that redirects to ITSELF is an
                # infinite loop, which is a worse way to fail than saying what went wrong.
                self._record_internal_error("deploy/view", exc)
                body = (f"<div class='sev-warn'>{_DEPLOY_ERRORS['internal']}</div>")
                self._html(200, _shell("Deploy", "deploy", body, **chrome))
                return
            self._html(200, _shell(title, "deploy", body, **chrome))
        elif path == "/acceptance" or _ACCEPTANCE_RUN.match(path):
            # WP-U4d.2. Reading acceptance history is never dangerous, so the page always
            # renders; the control that LAUNCHES one appears only when the operation is enabled.
            from .core.actions import get_operation
            from . import console_views  # noqa: F811 - function-local name in do_GET
            from .store import open_store  # noqa: F811 - same reason

            offered = get_operation("deploy_acceptance").enabled
            csrf = csrf_for(session, secret)
            q = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            notice = _ACCEPTANCE_NOTICES.get(q.get("msg", [""])[0], "")
            error = _ACCEPTANCE_ERRORS.get(q.get("err", [""])[0], "")
            m = _ACCEPTANCE_RUN.match(path)
            try:
                store = open_store()
                if m:
                    run = store.get_acceptance_run(int(m.group(1)))
                    if run is None:
                        self._send(404, b"no such acceptance run", "text/plain; charset=utf-8")
                        return
                    from . import acceptance_run as acceptance_mod
                    phases = store.list_acceptance_phases(run["id"])
                    # The DISPLAYED verdict is computed against the root-owned receipt, never
                    # read from the store's verdict column — application data cannot finalise a
                    # positive result. No valid receipt ⇒ BLOCKED.
                    trusted = acceptance_mod.trusted_verdict(run, phases)
                    body = console_views.acceptance_run_body(run, phases, trusted=trusted)
                    title = f"Acceptance #{run['id']}"
                else:
                    from . import acceptance_run as acceptance_mod
                    runs = store.list_acceptance_runs(limit=20)
                    trusted = {r["id"]: acceptance_mod.trusted_verdict(
                        r, store.list_acceptance_phases(r["id"])) for r in runs}
                    body = console_views.acceptance_body(
                        runs, csrf=csrf, offered=offered, trusted=trusted,
                        disabled_reason=_ACCEPTANCE_ERRORS["not-offered"],
                        notice=notice, error=error)
                    title = "Acceptance"
            except Exception as exc:  # noqa: BLE001 - a defect, and it must say so; rendered
                # in place for the same reason the deploy view is (redirect-to-self loops).
                self._record_internal_error("acceptance/view", exc)
                body = (f"<div class='sev-warn'>{_ACCEPTANCE_ERRORS['internal']}</div>")
                self._html(200, _shell("Acceptance", "acceptance", body, **chrome))
                return
            self._html(200, _shell(title, "acceptance", body, **chrome))
        elif path.startswith("/report/"):
            from . import console_views

            try:
                from .store import open_store

                artifact = open_store().get_report_artifact(int(path.rsplit("/", 1)[1]))
            except Exception:  # noqa: BLE001 - bad id / no store -> not found, never 500
                artifact = None
            if artifact is None:
                self._send(404, b"no such report artifact", "text/plain; charset=utf-8")
            else:
                self._html(200, _shell(f"Report #{artifact.id}", "home",
                                       console_views.report_body(artifact, redact=_redact),
                                       **chrome))
        elif path == "/logs":
            self._html(200, _shell("Evidence", "evidence", _logs_body(), **chrome))
        elif path == "/cases":
            from . import console_views

            try:
                from .store import open_store

                body = console_views.cases_body(open_store())
            except Exception as exc:  # noqa: BLE001
                body = f"<p class='muted'>Cases unavailable: {_e(_redact(str(exc)))}</p>"
            self._html(200, _shell("Cases", "cases", body, **chrome))
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    # ---- POST ----
    def do_POST(self):
        secret = _secret()
        if secret is None:
            self._send(503, b"console token not configured", "text/plain; charset=utf-8")
            return
        path = unquote(self.path.split("?", 1)[0])
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        form = {k: v[0] for k, v in parse_qs(raw).items()}

        if path == "/login":
            if hmac.compare_digest(form.get("token", ""), secret.decode("utf-8")):
                cookie = (f"{_SESSION_COOKIE}={issue_session(secret)}; Path=/; HttpOnly; "
                          f"SameSite=Strict; Max-Age={_SESSION_MAX_AGE}")
                self._headers(303, "text/html; charset=utf-8",
                              extra=[("Location", "/"), ("Set-Cookie", cookie)], body_len=0)
                return
            self._html(401, _login_page(error="Invalid token."))
            return

        # Everything below requires a valid session.
        session = self._authed(secret)
        if session is None:
            self._json(401, {"error": "not authenticated"})
            return

        if path == "/logout":
            # U2: explicit sign-out. Sessions are STATELESS signed cookies, so "logout" clears
            # THIS browser's cookie; it cannot revoke a copied token server-side (that's what
            # token rotation / service restart-on-redeploy are for — documented in the runbook).
            # No CSRF required: a forged logout can only sign the victim out, never in.
            expired = f"{_SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
            self._headers(303, "text/html; charset=utf-8",
                          extra=[("Location", "/"), ("Set-Cookie", expired)], body_len=0)
            return

        if path == "/api/execute":
            if not valid_csrf(form.get("csrf"), session, secret):
                self._json(403, {"error": "bad csrf token"})
                return
            self._stream_execute(form.get("op", ""))
            return

        if path == "/deploy/plan" or _DEPLOY_START.match(path):
            if not valid_csrf(form.get("csrf"), session, secret):
                self._json(403, {"error": "bad csrf token"})
                return
            self._deploy_act(path, form)
            return

        if path == "/acceptance/run":
            if not valid_csrf(form.get("csrf"), session, secret):
                self._json(403, {"error": "bad csrf token"})
                return
            self._acceptance_act(form, session=session, secret=secret)
            return

        m = _DECISION_ACT.match(path)
        if m:
            if not valid_csrf(form.get("csrf"), session, secret):
                self._json(403, {"error": "bad csrf token"})
                return
            self._decision_act(int(m.group(1)), m.group(2), form)
            return

        self._send(404, b"not found", "text/plain; charset=utf-8")

    def _redirect_deploy(self, run_id: int | None, param: str) -> None:
        where = f"/deploy/{run_id}" if run_id else "/deploy"
        self._headers(303, "text/html; charset=utf-8",
                      extra=[("Location", f"{where}?{param}")], body_len=0)

    def _deploy_act(self, path: str, form: dict) -> None:
        """Plan a deployment, or authorize one that was already planned.

        Approval and execution are separate acts on separate rows in time: planning writes the
        target and the plan the owner will read; authorizing requires the digest of THAT plan.
        The commit is never an argument to the runner — it lives on the immutable planned row.
        """
        from . import deploy as deploy_mod
        from .core.actions import get_operation
        from .store import open_store  # noqa: F811 - see do_GET

        if not get_operation("deploy_release").enabled:
            self._redirect_deploy(None, "err=not-offered")
            return
        try:
            store = open_store()
            m = _DEPLOY_START.match(path)
            if m is None:
                try:
                    sha = deploy_mod.validate_sha(form.get("sha", ""))
                except deploy_mod.DeployRefused:
                    self._redirect_deploy(None, "err=sha")
                    return
                plan = deploy_mod.build_plan(sha)
                run_id = store.plan_deploy(sha=sha, plan=plan,
                                           plan_digest=deploy_mod.plan_digest(plan),
                                           requested_by="owner")
                self._redirect_deploy(run_id, "msg=planned")
                return

            run_id = int(m.group(1))
            run = store.get_deploy_run(run_id)
            if run is None or run["status"] != "planned":
                self._redirect_deploy(run_id if run else None, "err=state")
                return
            if not hmac.compare_digest(form.get("digest", ""), run["plan_digest"]):
                self._redirect_deploy(run_id, "err=digest")
                return
            deploy_mod.spawn_detached(run_id)
            self._redirect_deploy(run_id, "msg=started")
        except Exception as exc:  # noqa: BLE001 - defects never wear policy's clothes
            self._redirect_deploy(None, f"err={self._record_internal_error('deploy/act', exc)}")

    def _redirect_acceptance(self, run_id: int | None, param: str) -> None:
        where = f"/acceptance/{run_id}" if run_id else "/acceptance"
        self._headers(303, "text/html; charset=utf-8",
                      extra=[("Location", f"{where}?{param}")], body_len=0)

    def _acceptance_act(self, form: dict, *, session: str, secret: bytes) -> None:
        """Launch the bounded disposable acceptance (WP-U4d.2).

        The browser contributes NOTHING but the approved click: no field of this form reaches
        the run. The run directory is derived server-side from the fixed safe parent, every
        other value is the engine's own resolution, and the one escalation happens in a
        detached process through the privileged program's fixed verb surface. Approval is
        genuinely two-step: the first POST mutates nothing and renders the confirmation page;
        only the confirmed POST creates the row and launches.
        """
        from . import acceptance_run as acceptance_mod
        from . import console_views  # noqa: F811 - function-local, see do_GET
        from .config import active_site, get_settings
        from .core.actions import get_operation
        from .store import open_store  # noqa: F811 - see do_GET

        if not get_operation("deploy_acceptance").enabled:
            self._redirect_acceptance(None, "err=not-offered")
            return
        try:
            if form.get("confirmed") != "1":
                s = get_settings()
                chrome = {"site_name": s.site_name or (active_site() or "Tossa Cycling"),
                          "env_kind": s.env_kind}
                body = console_views.acceptance_confirm_body(csrf=csrf_for(session, secret))
                self._html(200, _shell("Confirm acceptance run", "acceptance", body, **chrome))
                return
            store = open_store()
            # The row id is not known until the row exists, and the root is derived FROM the
            # id — so reserve the id first, then stamp the derived root. Two steps, one row;
            # begin_acceptance_run's NOT EXISTS guard still makes concurrent requests lose.
            run_id = store.begin_acceptance_run(requested_by="owner", root="pending")
            if run_id is None:
                self._redirect_acceptance(None, "err=busy")
                return
            store.set_acceptance_root(run_id, acceptance_mod.derive_run_root(run_id))
            acceptance_mod.spawn_detached(run_id)
            self._redirect_acceptance(run_id, "msg=started")
        except Exception as exc:  # noqa: BLE001 - defects never wear policy's clothes
            self._redirect_acceptance(
                None, f"err={self._record_internal_error('acceptance/act', exc)}")

    def _record_internal_error(self, where: str, exc: BaseException) -> str:
        """An UNEXPECTED exception is a defect, not a policy outcome (review #76). Record it as
        evidence — a failed run in the ledger, visible in the Evidence panel with the exception
        type, message and traceback — and return the query key for a message that says exactly
        that. A catch-all that renders defects as polite refusals is how real bugs hide."""
        import traceback

        try:
            from .store import open_store

            open_store().log_run(
                kind="console-error", status="error",
                summary=f"Console defect in {where}: {type(exc).__name__}",
                detail=_redact("".join(traceback.format_exception(exc))[:8000]))
        except Exception:  # noqa: BLE001 - never let error recording break error handling
            pass
        return "internal"

    def _decision_act(self, decision_id: int, action: str, form: dict) -> None:
        """U4a approve/reject/unapprove. Approve is genuinely two-step: the first POST (no
        `confirmed`) mutates NOTHING and renders the confirmation page; only the confirmed POST
        calls the lifecycle API. All outcomes redirect (303) so a refresh never re-submits."""
        from . import console_views
        from .config import active_site, get_settings
        from .store import open_store
        from .store.records import DecisionError, InvalidTransition, NotApprovable, StaleRevision

        # One secret for the whole handler: the adopt-token check needs it too, and a branch
        # that quietly lacked it once turned a NameError into a generic refusal (caught by the
        # U4c tests — the broad handler below must never be the reason a bug looks like policy).
        secret = _secret() or b""

        def _redirect(param: str) -> None:
            self._headers(303, "text/html; charset=utf-8",
                          extra=[("Location", f"/decision/{decision_id}?{param}")], body_len=0)

        try:
            revision = int(form.get("revision", ""))
        except ValueError:
            _redirect("err=stale")
            return
        try:
            store = open_store()
            if action == "approve" and form.get("confirmed") != "1":
                decision = store.get_decision(decision_id)
                if decision is None:
                    self._send(404, b"no such decision", "text/plain; charset=utf-8")
                    return
                if not decision.envelope_sha256:
                    _redirect("err=not-approvable")
                    return
                if decision.status != "proposed":
                    _redirect("err=invalid-transition")
                    return
                s = get_settings()
                session = self._authed(secret)
                body = console_views.decision_confirm_body(
                    decision, csrf=csrf_for(session, secret))
                self._html(200, _shell(f"Confirm D#{decision.id}", "decisions", body,
                                       site_name=s.site_name or (active_site() or "Tossa Cycling"),
                                       env_kind=s.env_kind))
                return
            if action == "adopt-live":
                # U4c: creates a NEW unapproved proposal from the live values, with provenance.
                # It never mutates, approves, executes or closes the source decision (review
                # #75) — superseding stays an explicit owner act.
                from . import verify as verify_mod
                from .config import decision_proposal_context

                source = store.get_decision(decision_id)
                if source is None or not source.envelope_sha256:
                    _redirect("err=adopt-failed")
                    return
                if source.revision != revision:
                    _redirect("err=stale")
                    return
                # Consent is bound to the snapshot the owner SAW. Re-fetching and adopting
                # whatever is live at click time would create wording they never reviewed
                # (review #76: TOCTOU consent failure).
                bound = read_adopt_token(form.get("snapshot"), secret)
                if bound is None:
                    _redirect("err=adopt-token")
                    return
                shown_at, shown_digest = bound
                # Idempotence via a DURABLE EXACT KEY in the store — not a scan over recent
                # rows, and not a substring search in prose (review #76). The key stays valid
                # however large the archive grows.
                from .store.records import adopt_key as _adopt_key

                key = _adopt_key(source_id=source.id, source_revision=source.revision,
                                 envelope_sha256=source.envelope_sha256,
                                 snapshot_digest=shown_digest)
                already = store.adopted_decision_id(key)
                if already is not None:
                    self._headers(303, "text/html; charset=utf-8",
                                  extra=[("Location", f"/decision/{already}?msg=already-adopted")],
                                  body_len=0)
                    return
                # EXPECTED failures (unreadable page, malformed stored envelope) are policy
                # refusals; anything else is a defect and must NOT wear policy's clothing.
                try:
                    envelope = json.loads(source.envelope or "")
                    snapshot = verify_mod.live_snapshot(envelope)
                    confirm_digest = verify_mod.snapshot_digest(
                        snapshot, source_id=source.id, revision=source.revision,
                        envelope_sha256=source.envelope_sha256)
                except (ValueError, TypeError):
                    _redirect("err=adopt-failed")
                    return
                except Exception as exc:  # noqa: BLE001 - a DEFECT: record it, show it as one
                    _redirect(f"err={self._record_internal_error('adopt-live/read', exc)}")
                    return
                if not hmac.compare_digest(confirm_digest, shown_digest):
                    _redirect("err=adopt-changed")
                    return
                if not store.claim_adoption(
                        key, source_id=source.id, source_revision=source.revision,
                        envelope_sha256=source.envelope_sha256, snapshot_digest=shown_digest):
                    already = store.adopted_decision_id(key)
                    _redirect("err=adopt-failed") if already is None else self._headers(
                        303, "text/html; charset=utf-8",
                        extra=[("Location", f"/decision/{already}?msg=already-adopted")],
                        body_len=0)
                    return
                try:
                    new_envelope = verify_mod.adopt_live_envelope(envelope, snapshot)
                    profile, envs, hosts = decision_proposal_context()
                    urls = ", ".join(f"{k}={v['url']}" for k, v in snapshot["urls"].items())
                    values = "; ".join(
                        f"{k}: title={v['title']!r} meta={v['meta_description']!r}"
                        for k, v in snapshot["urls"].items())
                    new_id = store.propose_decision(
                        title=f"Adopt live wording (from D#{source.id})",
                        envelope=new_envelope,
                        expected_profile=profile, allowed_environments=envs,
                        allowed_hosts=hosts,
                        rationale=(f"The live pages no longer match D#{source.id}'s approved "
                                   "content. This proposal binds exactly what is serving now, "
                                   "so verification can close the loop against reality. "
                                   f"Approving it does not change the site."),
                        # Provenance covers BOTH reads: what was displayed and what the
                        # click confirmed. Their digests are identical by construction — that
                        # identity IS the evidence that the owner adopted what they reviewed.
                        evidence=(f"Adopted from D#{source.id} (revision {source.revision}, "
                                  f"envelope {source.envelope_sha256[:12]}) · displayed "
                                  f"{shown_at} · confirmed {snapshot['fetched_at']} · snapshot "
                                  f"{shown_digest} · {urls} · {values}"),
                        case_id=source.case_id, made_by="human")
                except ValueError:            # partial snapshot / rejected proposal: policy
                    _redirect("err=adopt-failed")
                    return
                except Exception as exc:  # noqa: BLE001 - a DEFECT, surfaced as a defect
                    _redirect(f"err={self._record_internal_error('adopt-live/create', exc)}")
                    return
                store.complete_adoption(key, new_id)
                self._headers(303, "text/html; charset=utf-8",
                              extra=[("Location", f"/decision/{new_id}?msg=adopted")],
                              body_len=0)
                return
            if action in ("verify", "verify-confirm"):
                # U4b: revision must match what the owner's page showed — a stale view must
                # never trigger reads against an envelope the owner has since revisited.
                from . import verify as verify_mod

                decision = store.get_decision(decision_id)
                if decision is None:
                    self._send(404, b"no such decision", "text/plain; charset=utf-8")
                    return
                if decision.revision != revision:
                    _redirect("err=stale")
                    return
                outcome = verify_mod.verify_step(
                    store, decision, step=1 if action == "verify" else 2)
                _redirect({
                    "pending": "msg=verify-pending",
                    "executed": "msg=executed",
                    "read-mismatch": "err=verify-mismatch",
                    "read-error": "err=verify-error",
                    "too-soon": "err=verify-too-soon",
                    "no-pending": "err=verify-no-pending",
                    "not-approved": "err=invalid-transition",
                    "not-verifiable": "err=verify-unavailable",
                }.get(outcome, "err=unknown"))
                return
            if action == "approve":
                outcome = store.approve_decision(decision_id, expected_revision=revision,
                                                 actor="owner")
                _redirect("msg=already-approved" if outcome == "already-approved"
                          else "msg=approved")
            elif action == "reject":
                if not (form.get("reason") or "").strip():
                    _redirect("err=reason-required")
                    return
                store.reject_decision(decision_id, expected_revision=revision,
                                      reason=form["reason"], actor="owner")
                _redirect("msg=rejected")
            elif action == "unapprove":
                store.unapprove_decision(decision_id, expected_revision=revision, actor="owner")
                _redirect("msg=unapproved")
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")
        except StaleRevision:
            _redirect("err=stale")
        except NotApprovable:
            _redirect("err=not-approvable")
        except InvalidTransition:
            _redirect("err=invalid-transition")
        except DecisionError:
            _redirect("err=unknown")
        except Exception as exc:  # noqa: BLE001 - answer, but never disguise a defect as policy
            _redirect(f"err={self._record_internal_error(f'decision/{action}', exc)}")

    # ---- streaming execution ----
    def _stream_execute(self, op_id: str) -> None:
        """Run the operation and stream step events as `data: {json}` frames, then CLOSE.

        The op id is validated by the Execution Service (unknown -> a 'blocked' result event);
        the Console never accepts a free-form command, only a registry op id from the listing.

        D4 (VPS acceptance): the response has no Content-Length, so the ONLY end-of-body signal
        the browser gets is the connection closing. The first deployment kept the connection
        alive after the final frame, so the client's read loop never resolved and the Execute
        button stayed on "Running…" forever. Declare `Connection: close` and actually close.
        """
        self._headers(200, "text/event-stream; charset=utf-8",
                      extra=[("Cache-Control", "no-cache"), ("X-Accel-Buffering", "no"),
                             ("Connection", "close")])

        # One lock serialises ALL stream writes (event frames + keepalives) so frames never
        # interleave mid-byte. See _KEEPALIVE_S for why the pulse exists (U1: silent scan +
        # idle NAT drop = "Running…" forever while the backend completed).
        wlock = threading.Lock()

        def frame(obj: dict) -> None:
            payload = f"data: {json.dumps(obj, default=str)}\n\n".encode()
            with wlock:
                self.wfile.write(payload)
                self.wfile.flush()

        stop_pulse = _start_keepalive(self.wfile, wlock)

        # A dedicated-surface operation (deploy_release, deploy_acceptance) must never run through
        # the generic executor — it would be invoked with no run id. It is absent from the
        # operations listing, but a crafted /api/execute POST could still name it, so refuse here.
        op = next((o for o in OPERATIONS if o.id == op_id), None)
        if op is None or not op.self_service:
            frame({"type": "result", "execution_status": "blocked", "outcome": "blocked",
                   "severity": "attention",
                   "block_reason": "this operation is not runnable from the operations surface; "
                                   "use its dedicated page"})
            stop_pulse.set()
            self.close_connection = True
            return

        def emit(ev: StepEvent) -> None:
            # F3: step detail can carry scanner output including server paths — reduce them the
            # same way the Logs panel does (WP-relative tails survive; mount prefixes do not).
            frame({"type": "step", "step": ev.step, "status": ev.status,
                   "detail": _redact(ev.detail)})

        try:
            result = _executor().execute(op_id, emit=emit, actor="human")
            frame({"type": "result", "execution_status": result.execution_status,
                   "outcome": result.outcome, "severity": result.severity,
                   "exit_code": result.exit_code, "evidence_ref": result.evidence_ref,
                   "duration_s": result.duration_s, "block_reason": result.block_reason})
        except Exception as exc:  # noqa: BLE001 - a stream must end with a frame, never a broken socket
            frame({"type": "result", "execution_status": "error", "outcome": "failure",
                   "severity": "error", "block_reason": _redact(f"{type(exc).__name__}: {exc}")})
        finally:
            stop_pulse.set()
            # End of body = end of connection; the client's reader resolves and resets the button.
            self.close_connection = True

    def log_message(self, fmt, *args):  # quiet; see dashboard.py
        pass


def _start_keepalive(wfile, wlock: threading.Lock, interval_s: float | None = None) -> threading.Event:
    """Pulse SSE comment frames onto an execute stream until told to stop; returns the stop event.

    Runs as a daemon thread so a wedged socket can never keep the process alive. A write failure
    ends the pulse quietly — the client is gone, but the OPERATION keeps running and its evidence
    still persists (disconnecting an observer must never kill the work)."""
    stop = threading.Event()

    def _pulse() -> None:
        while not stop.wait(interval_s if interval_s is not None else _KEEPALIVE_S):
            try:
                with wlock:
                    wfile.write(_KEEPALIVE_FRAME)
                    wfile.flush()
            except OSError:
                return
    threading.Thread(target=_pulse, daemon=True).start()
    return stop


def _logs_body() -> str:
    """Recent operation runs from the ledger — the Console's Evidence/Logs view."""
    try:
        from .store import open_store

        rows = open_store().list_runs()
    except Exception:  # noqa: BLE001 - no store yet is fine; show an empty state, never 500
        rows = []
    op_runs = [r for r in rows if str(getattr(r, "kind", "")).startswith("op:")]
    if not op_runs:
        return ("<h2 style='font-size:15px'>Operation log</h2>"
                "<p class='muted'>No operations have been run through the Console yet. "
                "Each execution records actor, steps, output and result here.</p>")
    _sev_class = {"ok": "ok", "attention": "warn", "warn": "warn", "error": "err"}
    items = []
    for r in op_runs:
        exec_status = str(getattr(r, "status", "?"))   # ledger status = execution_status
        outcome, severity = exec_status, ""
        try:
            detail = json.loads(getattr(r, "detail", "") or "{}")
            outcome = detail.get("outcome") or exec_status
            severity = detail.get("severity", "")
        except (ValueError, TypeError):
            pass
        # Label reflects the DOMAIN result, not just pass/fail — 'findings' reads as a completed
        # scan that found something, never as a broken tool.
        if exec_status == "error":
            label, cls = "execution error", "err"
        elif exec_status == "blocked":
            label, cls = "blocked", "err"
        else:
            label = f"completed · {outcome}"
            cls = _sev_class.get(severity, "ok")
        items.append(
            f"<div class='op'><div><h3>{_e(getattr(r, 'kind', ''))} "
            f"<span class='badge {cls}'>{_e(label)}</span></h3>"
            f"<div class='meta'>{_e(getattr(r, 'started_at', ''))} · "
            f"{_e(_redact(getattr(r, 'summary', '') or ''))}</div></div></div>")
    return "<h2 style='font-size:15px'>Operation log</h2>" + "".join(items)


def serve(host: str = "127.0.0.1", port: int = 8385) -> int:
    """Blocking server. Loopback by default on purpose — see the module docstring.

    Fails closed: without TC_CONSOLE_TOKEN there is no auth, and an execution surface must not
    run unauthenticated. Returns a non-zero exit in that case so the CLI surfaces it.
    """
    if _secret() is None:
        print(f"REFUSING TO START: {_TOKEN_ENV} is not set.")
        print("The Operations Console runs privileged operations; it will not run without a token.")
        print(f"Set one first, e.g.:  export {_TOKEN_ENV}=\"$(python -c 'import secrets;print(secrets.token_urlsafe(32))')\"")
        return 1
    validate_registry()  # never serve a catalogue that contradicts the enforcement layer
    # WP-U4d.1: latch BEFORE binding, so the deployment target seam is closed in this process even
    # if the bind itself fails and something later reuses the process.
    deploy_target.note_http_boundary()
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"TC Operations Console on http://{host}:{port}  — Ctrl+C to stop")
    print(f"Remote access: ssh -L {port}:127.0.0.1:{port} <user>@<vps>  then open http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
