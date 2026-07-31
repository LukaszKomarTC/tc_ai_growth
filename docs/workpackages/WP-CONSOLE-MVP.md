# WP — AI Operations Console (MVP)

**Status:** SLICE 1 BUILT 2026-07-28 (SMTP Test, end to end) — reprioritized to NEXT after
INC-2026-07-27. The incident forced days of manual terminal operation; the owner and independent
review converged on the same signal: *the platform has reached the point where investing in
operator UX returns more than another capability.* Build this before Site Intelligence / Source
Reader resume.

**What exists now (branch `feature/operations-console`):** the origin-agnostic Execution
Service (`core/executor.py`), the `smtp_test` registry operation with instrumented protocol
step events, and the loopback Console (`console.py`) — login → Preview → Execute → live streamed
steps → pass/fail + evidence, with token→session+CSRF auth. 30 tests + a live loopback smoke
test green. Not yet deployed behind the tunnel with real SMTP (owner acceptance pending).

**Origin insight:** we were building the platform by suffering the exact pain the platform
exists to remove (human-as-clipboard, pasting commands nobody can fully verify). The Console
replaces that with named, reviewable, logged operations.

## Scope — deliberately minimal

A console that does ONLY: **list named operations → execute one → stream its output → show
result + evidence → request approval where required.** No free chat. No new dashboards. No
autonomous remediation. Nothing more. (Same bounded discipline applied to the Inspector.)

We already have the other half: the **Action Registry** (`core/actions.py`) — and its role has
been promoted. It is no longer just "governance documentation"; it is the **API contract
between the UI and the execution engine.** The Console is the missing **Execution Service + UI**
on top of it.

**Also excluded from the MVP:** no chat, no "Ask AI," no conversational execution. The panels
are only **Operations · Evidence · Cases · Logs.** The incident showed deterministic workflows
beat conversational interfaces when something important is happening.

## Two things kept strictly separate

1. **Human clicks a button (THIS MVP).** Gets the operator off the terminal. Human-in-the-loop.
2. **AI triggers an operation via an API (LATER, separate WP).** That is AI execution authority
   and needs its own governance design. Do NOT conflate. The MVP does not give Claude (or any
   agent) the ability to execute — it gives the human buttons.

## Security — this is a privileged EXECUTION surface (built the week of a breach)

The old dashboard was read-only GET. This one *runs operations*, so it is a real write/execution
attack surface and must be hardened accordingly — the thing built for safety must not become the
next entry point:

- **Not internet-exposed.** MVP binds `127.0.0.1` only, reached via SSH tunnel (same as the
  read dashboard). A public authenticated endpoint is a later, deliberate step.
- **Session auth + CSRF** on every state-changing request (the dashboard audit already required
  this before any write control shipped). *Implemented:* a shared `TC_CONSOLE_TOKEN` unlocks an
  HMAC-signed, 12h-expiring session cookie (HttpOnly, SameSite=Strict); every execute POST also
  carries a session-bound CSRF token. The server **fails closed** — it refuses to start without a
  token. Self-only CSP; no off-box fetch. (A real IdP is a later, deliberate step.)
- **Governed execution only:** the executor may run ONLY operations in the Action Registry,
  with the registry's phase gate, approval class, and allowlisted arguments enforced server-side.
  No free-form command field, ever. No shell string interpolation.
- **Everything logged:** each execution writes actor, operation id, args, start/end, exit,
  streamed output reference, and result to the run ledger / evidence store.
- **ALWAYS_ASK operations** (e.g. publish) require an explicit in-UI confirmation step; nothing
  in the FORBIDDEN set is reachable.

## Execution Service (the core) — origin-agnostic

`core/executor.py` is an **Execution Service**, not a UI helper. Its defining property:
**it never knows whether a request came from a human click or an AI recommendation.** It
receives an *approved operation* (registry op id + validated args + the approval that cleared
it) and executes it. That single boundary is what lets the human-button MVP and the
future AI-trigger path share one governed, logged execution engine instead of two.

Given an approved operation it:
- resolves the op in the Action Registry; enforces phase + approval class + environment +
  arg allowlist server-side (the client is never trusted);
- runs it (CLI operations as governed subprocesses with timeout + captured stdout/stderr;
  tool operations via the registry dispatch);
- emits **step events** as it goes (see Streaming); persists a run record + evidence;
  returns a structured result (see Result semantics below).
Reuses the existing phase gate and Action Registry — it does not invent a second authority.

## Result semantics — findings are not failures

An evidence-centric platform must not collapse every operation into Unix `exit 0 = success,
nonzero = failure`. That's too primitive for diagnostics: an integrity scan that exits `2`
**completed successfully and found something** — recording it as *failed* would poison
reliability metrics, make operator history say the tool broke when it worked, let alerting
confuse a security finding with an infrastructure outage, and teach a future AI that the scanner
is unreliable. So the result model separates three axes:

- **execution_status** — did the op run to a defined result? `completed | error | blocked`
- **outcome** — the domain result it reports: `clean | findings | warnings | success | failure`
- **severity** — operator attention: `ok | attention | warn | error`

The exit-code → outcome mapping is **data on the registry operation** (`result_policy`), so the
executor stays generic while the registry describes each op's own semantics. Integrity scan
declares `{0: clean, 2: findings}`; a code outside the policy is a genuine execution error (a
crash, a timeout). The ledger stores `execution_status` as the run status (so a findings scan
counts as a *completed* run) with `outcome`/`severity` in the evidence detail for richer queries.
The Console shows "Completed — findings" in amber, not a red "failed". Outcome labels are a
closed vocabulary validated in CI. *This was a real correction during op #2 — the first version
mislabelled exit 2 as failed.*

## Operation Preview — show before you run

Every operation renders a **Preview** before the Execute button is live: target
(prod / staging / localhost), profile, the concrete actions it will take, expected duration,
approval class, and whether it writes anything. Read-only ops say so plainly; write/ALWAYS_ASK
ops make the blast radius visible *before* the click, not after. The Preview is generated from
the registry entry — same source of truth the executor enforces — so what you're shown and what
runs cannot drift.

## Streaming — step events, not a spinner

The UI shows the operation progressing as discrete **step events** (e.g. `connect smtp` →
`starttls` → `auth` → `send` → `ok`), each with its own status, not an opaque spinner. The
executor emits these as it runs; the transport is a simple server→client event stream. A stalled
step is visible as a stalled step. The full streamed transcript is persisted with the run record
so the evidence matches exactly what the operator watched.

## First operations to surface (all already exist as named ops or CLI)

SMTP test · Run integrity scan (Technical Inspector) · Check mail queue · Verify backups ·
Restore test · Weekly report · Refresh site snapshot. These are exactly the operations we ran
by hand tonight — the Console retires that manual work.

## Build order — one vertical slice first, then widen

Do NOT build a generic executor and then hunt for operations to feed it. Build the whole
stack around **one operation, end to end**, prove it, then add operations one at a time. The
first slice is **SMTP Test** — low blast radius (read-only-ish, no site writes), exactly the
thing we fought with tonight, and it exercises every layer the platform needs.

1. **SMTP Test — full vertical slice. ✅ BUILT.** Preview → Execute button → Execution Service
   runs the op → step events stream to the UI → pass/fail + evidence shown → audit record written.
   Backend + streaming + evidence + tests, then the minimal loopback UI around it. Remaining:
   deploy behind the tunnel with real SMTP so the owner clicks it and watches it succeed — the
   only step that needs the box.
2. **Integrity Scan (Technical Inspector). ✅ BUILT.** The second op — proves a longer-running,
   multi-step CLI operation streams and captures evidence the same way, and it did so as a pure
   **registry entry + CLI binding with ZERO executor changes** (a test asserts it has no native
   runner). It also forced a **result-semantics** correction (see below): exit 2 is a *completed
   scan with findings*, not a failure.
3. **Verify Backups / Restore Test** as the third — proves an op that produces a file/report
   artifact as evidence.
4. Only after three real ops share the one engine: the ALWAYS_ASK in-UI confirmation step (auth +
   CSRF already shipped in slice 1), then widen to the rest (mail queue, weekly report, snapshot).

Each new operation is a registry entry + (if needed) a step-event mapping — not new executor
code. If adding an operation needs executor changes, that's the signal the abstraction is wrong.
Then STOP at the agreed set — broader capabilities resume afterward.

## Acceptance

- [x] **Slice 1 (SMTP Test) mechanism complete:** Preview renders from the registry → Execute →
      step events stream → pass/fail + evidence shown → audit record written. Verified by a live
      loopback smoke test (login→session→CSRF→preview→stream→result→`run#…` evidence).
- [ ] **Owner acceptance:** deployed behind the tunnel with real SMTP; owner clicks SMTP Test and
      watches it succeed, no terminal. *(pending the box)*
- [x] Execution Service runs a READ_ONLY named op end-to-end with evidence logged; refuses an op
      above the current phase / with a disallowed arg (tests). Receives an *approved operation* and
      does not distinguish human vs AI origin.
- [x] Adding op #2 (Integrity Scan) required a registry entry + CLI binding, **no executor
      changes** — locked by a test asserting it has no native runner.
- [x] **Result semantics correct:** exit 2 (findings) is `completed / findings / attention`, not
      `failed`; exit-code→outcome mapping is registry data (`result_policy`), validated in CI;
      outcome/severity persisted as evidence; scanner output HTML-escaped in the UI (tests + smoke).

### OP2 real-box acceptance (pending the box — needs the VPS)

Repository tests are necessary but not sufficient. Before OP2 is "accepted":

- [ ] Run against the real production WordPress docroot under the real `tcgrowth` permissions.
- [ ] Confirm fixed target + no path injection (op takes no args; script path is env-pinned).
- [ ] A clean scan produces `completed / clean`.
- [ ] A harmless controlled fixture produces `completed / findings` (NOT `failed`); then remove it
      and confirm `completed / clean` again.
- [ ] Findings persist to the log even if alert delivery fails.
- [ ] The browser safely escapes filenames and scanner output (verified in the loopback smoke; re-check on the box).
- [ ] Establish the script **source of truth** (see docs/TECHNICAL_INSPECTOR.md): repo → deployed
      path, cron and Console run the *same* deployed file. No hand-edited `/usr/local/bin` copy.
- [x] Auth fails closed (no token → no serve); session is HMAC-signed + expiring; CSRF is
      session-bound; execute without CSRF → 403 (tests + smoke).
- [ ] A write/ALWAYS_ASK op requires explicit in-UI confirmation; FORBIDDEN ops are unreachable.
      *(confirmation UI is the slice-4 step; today such ops show as not-runnable in preview.)*
- [x] No free-form command input anywhere; server enforces the registry, not the client (op ids
      validated server-side; subprocess argv is a list, no shell).

## Center of gravity — where this is heading

Worth naming explicitly: across the incident and this reprioritization, the project's center of
gravity moved from "an AI that runs growth tasks" to an **Evidence-Centric Operations Platform** —
named operations, previews, streamed execution, evidence, cases, audit. The AI is becoming *one
client* of that platform, not the platform itself. This Console is the human client; the AI-trigger
path (separate, later WP) is a second client of the *same* Execution Service. Keep that framing:
build the platform, then let each origin — human or agent — call it through the same governed door.

## Branch stack & merge discipline

The Console branch now carries a stack of feature layers (Action Registry, Site Intelligence,
Source Reader, Technical Inspector, plus the Console itself). To keep a Console merge from becoming
a **backdoor merge of several frozen branches**, the dependency map, the true-vs-co-present
analysis, and the base-up merge order are captured in
[`WP-CONSOLE-DEPENDENCY-MAP.md`](./WP-CONSOLE-DEPENDENCY-MAP.md). Core invariant: **the operations
a user can click must equal the capabilities that have passed their own acceptance** — the registry
must not advertise an operation whose backing layer is still frozen.

## What this does NOT change

Merges still wait for the restarted clean-Monday gate. The Console is built now on this branch;
it deploys with the re-baselined platform, not before. Development continues; baseline trust is
not diluted. OP3 (Verify Backups) is **explicitly paused** until OP1+OP2 have real-box owner
acceptance and the result-semantics + source-of-truth items above are closed — three operations
are not better than two if the outcome model is wrong or neither is accepted on the VPS.
