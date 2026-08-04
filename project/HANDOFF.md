# HANDOFF — where the next engineer starts

_Index, not authority (PROTOCOL.md). If this disagrees with git or the server, this file is wrong._

## Commits

- `main`: NOT pinned here — a file committed to `main` cannot pin `main`'s HEAD (the commit that
  updates the pin invalidates it; Codex caught the stale value on 2026-08-03). Authority:
  `git rev-parse origin/main`. Only deployment pins belong below.
- Production app checkout (`/opt/tc_ai_growth/app`): `3edb0de` — verified: owner-run
  convergence @ 2026-08-04 — 297 passed on the VPS, store migrated v4→v5 (decision_verify_attempts
  + append-only triggers; 13 decisions / 26 runs / 3 cases intact), Monday timer armed 08-10
  05:00 UTC. Rollback marker: `backup/pre-u3a-b6779cc`.
- Console release (tc-console): `3edb0de` from `/opt/tc_ai_growth/releases/3edb0de…` — verified:
  owner-run apply + health 200 @ 2026-08-04 (U4b). Env truths persist in /etc/tc-console.env
  across releases (proven). Rollback: `releases/9dd11ef…` retained (N-1); older dirs removable

## Current work

**WP-CONSOLE-USABILITY: U1+U2+U3a+U3b(+.1) ACCEPTED · U4a FULLY CLOSED · U4b ACCEPTED
2026-08-04 — the platform closes its own loop** (acceptance records in
WP-CONSOLE-USABILITY.md §U4b/§U4a). Live production state, store-verified 2026-08-04 19:47 UTC:
schema v5 · D#12 rejected (superseded) · D#13 rejected (live copy drifted again) · **D#14
EXECUTED by the platform** (`propose`→`approve`(owner)→two matching live reads→`execute`
(platform), evidence `verify_attempt:3`) · queue empty · env context
TC_DECISION_TARGET_ENVIRONMENTS=production + TC_DECISION_URL_HOSTS set.

Remaining in U4: **U4c** (per spec §UI — homepage smart card with impact/confidence,
business-review report block, 🔴/🟡 labels, Recent-operations collapse) plus the new
**"adopt live content"** candidate (copy drift proved a pattern across D#12→D#13→D#14).
Also now triggered: the **U2 basic-auth retirement review** (spec exit condition 4 — approval
authority is live for daily use).

## Blocked on

Nothing — owner queue empty; U4b accepted and live.

## Next action

1. U4c on owner word (smart card + business-review block + labels; "adopt live content"
   candidate), and/or the U2 basic-auth retirement review.
2. Monday 08-10 05:00 UTC: artifact #1 lands (U3a live acceptance = `report-artifact 1` hash
   vs the delivered email) + the behavioral capstone (Console-first vs Gmail-first).

## Standing constraints

Autodeploy DISABLED by decision · manual deliberate deploys only · all server Git as `tcgrowth`
(D5) · owner is release authority · permanent dangers in docs/STANDING-CAUTIONS.md (incl. the
DO_NOT_RESTORE compromised backup) · see PRODUCTION_BASELINE_V1.md for the baseline reference
(note: its commit pins predate today's Console release — the baseline records the 2026-08-02
state by design).
