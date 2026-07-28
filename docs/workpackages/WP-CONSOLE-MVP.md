# WP — AI Operations Console (MVP)

**Status:** SPEC 2026-07-28 — reprioritized to NEXT after INC-2026-07-27. The incident forced
days of manual terminal operation; the owner and independent review converged on the same
signal: *the platform has reached the point where investing in operator UX returns more than
another capability.* Build this before Site Intelligence / Source Reader resume.

**Origin insight:** we were building the platform by suffering the exact pain the platform
exists to remove (human-as-clipboard, pasting commands nobody can fully verify). The Console
replaces that with named, reviewable, logged operations.

## Scope — deliberately minimal

A console that does ONLY: **list named operations → execute one → stream its output → show
result + evidence → request approval where required.** No free chat. No new dashboards. No
autonomous remediation. Nothing more. (Same bounded discipline applied to the Inspector.)

We already have the other half: the **Action Registry** (`core/actions.py`) is the named-
operation catalogue (id, category, min phase, approval class, enforcement, environments). The
Console is the missing **executor + UI** on top of it.

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
  this before any write control shipped).
- **Governed execution only:** the executor may run ONLY operations in the Action Registry,
  with the registry's phase gate, approval class, and allowlisted arguments enforced server-side.
  No free-form command field, ever. No shell string interpolation.
- **Everything logged:** each execution writes actor, operation id, args, start/end, exit,
  streamed output reference, and result to the run ledger / evidence store.
- **ALWAYS_ASK operations** (e.g. publish) require an explicit in-UI confirmation step; nothing
  in the FORBIDDEN set is reachable.

## Executor (the core)

`core/executor.py` — given an Action Registry operation id + validated args:
- resolve the operation; enforce phase + approval + environment + arg allowlist;
- run it (CLI operations as governed subprocesses with timeout + captured stdout/stderr;
  tool operations via the registry dispatch);
- stream output to the caller; persist a run record + evidence; return a structured result.
Reuses the existing phase gate and Action Registry — it does not invent a second authority.

## First operations to surface (all already exist as named ops or CLI)

SMTP test · Run integrity scan (Technical Inspector) · Check mail queue · Verify backups ·
Restore test · Weekly report · Refresh site snapshot. These are exactly the operations we ran
by hand tonight — the Console retires that manual work.

## Build order

1. `core/executor.py` + tests (no UI): execute a named op, enforce the gate, capture evidence.
2. Minimal loopback web UI: op list (from the registry) → button → streamed output → result.
3. Session auth + CSRF; confirmation step for ALWAYS_ASK ops.
4. Wire the first operations; deploy behind the tunnel; owner acceptance (click each, see result).
Then STOP — broader capabilities resume afterward.

## Acceptance

- [ ] Executor runs a READ_ONLY named op end-to-end with evidence logged; refuses an op above
      the current phase / with a disallowed arg (tests).
- [ ] UI (loopback) lists registry ops, runs one, streams output, shows pass/fail + evidence.
- [ ] A write/ALWAYS_ASK op requires explicit confirmation; FORBIDDEN ops are unreachable.
- [ ] No free-form command input anywhere; server enforces the registry, not the client.
- [ ] Owner runs SMTP test + integrity scan from the UI, no terminal.

## What this does NOT change

Merges still wait for the restarted clean-Monday gate. The Console is built now on this branch;
it deploys with the re-baselined platform, not before. Development continues; baseline trust is
not diluted.
