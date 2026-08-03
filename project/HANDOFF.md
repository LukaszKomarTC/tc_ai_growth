# HANDOFF — where the next engineer starts

_Index, not authority (PROTOCOL.md). If this disagrees with git or the server, this file is wrong._

## Commits

- `main`: NOT pinned here — a file committed to `main` cannot pin `main`'s HEAD (the commit that
  updates the pin invalidates it; Codex caught the stale value on 2026-08-03). Authority:
  `git rev-parse origin/main`. Only deployment pins belong below.
- Production app checkout (`/opt/tc_ai_growth/app`): `d391247` — verified: owner-run
  convergence @ 2026-08-03 ~19:40 UTC — ff b6779cc→d391247, 205 passed on the VPS, store
  migrated v2→v3 (report_artifacts empty, ledger intact #25–27), Monday timer armed 08-10
  05:00 UTC. Rollback marker: `backup/pre-u3a-b6779cc`.
- Console release (tc-console): `ab9afa4` from `/opt/tc_ai_growth/releases/ab9afa4` — verified:
  deploy apply plan + owner in-browser confirmation @ 2026-08-03 ~17:40 UTC (Sign out working).
  Rollback: `releases/63448f3` retained (N-1 rule); `releases/d260726` removable

## Current work

**WP-CONSOLE-USABILITY: U1 + U2 ACCEPTED; U3a BUILT, awaiting review+merge.** U3a lives on
branch `feature/u3a-report-artifacts` (1 commit on main tip): schema v3 report_artifacts with a
database-layer immutability trigger, hash-verified persist-before-deliver wiring, hash-keyed
delivery marking, CLI read commands, 201 tests green, v2→v3 migration proven non-destructive.
CAUTION: this changes report.py/cli.py — the scheduled Monday path — so merge is
owner-authorized and production convergence follows the controlled-ff runbook. Next Monday run:
2026-08-10 (would produce production artifact #1 if deployed before then).

## Blocked on

Nothing — engineering (U3a) and the owner's business queue proceed independently.

## Next action

1. Review round on feature/u3b-operator-homepage → merge → Console redeploy → in-browser
   acceptance (five sections render truthfully; redeliver button once artifact #1 exists).
2. Monday 08-10: verify artifact #1 (hash vs email) — closes U3a's live acceptance.

## Standing constraints

Autodeploy DISABLED by decision · manual deliberate deploys only · all server Git as `tcgrowth`
(D5) · owner is release authority · permanent dangers in docs/STANDING-CAUTIONS.md (incl. the
DO_NOT_RESTORE compromised backup) · see PRODUCTION_BASELINE_V1.md for the baseline reference
(note: its commit pins predate today's Console release — the baseline records the 2026-08-02
state by design).
