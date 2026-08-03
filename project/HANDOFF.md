# HANDOFF — where the next engineer starts

_Index, not authority (PROTOCOL.md). If this disagrees with git or the server, this file is wrong._

## Commits

- `main`: NOT pinned here — a file committed to `main` cannot pin `main`'s HEAD (the commit that
  updates the pin invalidates it; Codex caught the stale value on 2026-08-03). Authority:
  `git rev-parse origin/main`. Only deployment pins belong below.
- Production app checkout (`/opt/tc_ai_growth/app`): `b6779cc` — verified: owner-run
  `git rev-parse HEAD` in server terminal @ 2026-08-03. Drift vs main: main is ahead by commits
  touching docs, /project, `deploy-console.sh`, `console.py`, and tests — but the scheduled
  weekly-report path is UNCHANGED (verified @ 2026-08-03 10:5x UTC:
  `git diff --quiet b6779cc HEAD -- …/report.py …/cli.py …/core …/store` → identical), and the
  Console does not run from this checkout. Reconcile via controlled ff at next deploy round.
- Console release (tc-console): `ab9afa4` from `/opt/tc_ai_growth/releases/ab9afa4` — verified:
  deploy apply plan + owner in-browser confirmation @ 2026-08-03 ~17:40 UTC (Sign out working).
  Rollback: `releases/63448f3` retained (N-1 rule); `releases/d260726` removable

## Current work

**WP-CONSOLE-USABILITY: U1 + U2 ACCEPTED** (records in the WP doc). Console reachable at
https://ops.tossacycling.com from any device (docs/RUNBOOK-CONSOLE.md). Next increment: **U3a —
immutable report artifact persistence** (spec in WP-CONSOLE-USABILITY.md §U3a): persist the
validated weekly-report body with hash-bound identity so the dashboard can display provably the
artifact that was validated and emailed.

## Blocked on

Nothing — engineering (U3a) and the owner's business queue proceed independently.

## Next action

1. Claude: U3a design + implementation on a branch (data model only, no UI).
2. Owner: business queue (P3-ES → D#9 → D#10 → D#11) — independent of engineering.

## Standing constraints

Autodeploy DISABLED by decision · manual deliberate deploys only · all server Git as `tcgrowth`
(D5) · owner is release authority · permanent dangers in docs/STANDING-CAUTIONS.md (incl. the
DO_NOT_RESTORE compromised backup) · see PRODUCTION_BASELINE_V1.md for the baseline reference
(note: its commit pins predate today's Console release — the baseline records the 2026-08-02
state by design).
