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
- Console release (tc-console): `fd8f682` from `/opt/tc_ai_growth/releases/fd8f682` — verified:
  owner-run apply + health 200 @ 2026-08-03 (U3b.1 + TC_ALLOW_WRITES=false live).
  Rollback: `releases/48e91d7` retained (N-1 rule); older release dirs removable

## Current work

**WP-CONSOLE-USABILITY: U1+U2+U3a+U3b(+.1) ACCEPTED and deployed. U4 spec MERGED (PR #69 r4,
owner GO 2026-08-04, main f37dfb8). U4a BUILT — under review on PR #71** (branch
`feature/u4a-decision-detail`, 626b5ce, lead subscribed): schema v4 additive migration, canonical
envelope hashing, storage-trigger lifecycle guards, revision concurrency, /decision/<id> page
with two-step browser Approve / Reject-with-reason. 250 tests green, branch CI green. Review
gate: the 10 acceptance criteria on the PR #69 thread. Spec authority:
docs/workpackages/WP-U4-DECISION-WORKFLOW.md.

## Blocked on

Nothing — PR #71 review proceeds on-thread; owner queue empty.

## Next action

1. Reviewer round on PR #71 → lead fixes on-thread → owner word merges → deploy via runbook →
   owner acceptance click-through (seed decision via `decision-propose`).
2. Monday 08-10: artifact #1 (U3a live acceptance) + the Gmail-vs-Console behavioral capstone.

## Standing constraints

Autodeploy DISABLED by decision · manual deliberate deploys only · all server Git as `tcgrowth`
(D5) · owner is release authority · permanent dangers in docs/STANDING-CAUTIONS.md (incl. the
DO_NOT_RESTORE compromised backup) · see PRODUCTION_BASELINE_V1.md for the baseline reference
(note: its commit pins predate today's Console release — the baseline records the 2026-08-02
state by design).
