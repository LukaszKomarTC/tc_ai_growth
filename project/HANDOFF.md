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

**WP-CONSOLE-USABILITY: U1+U2+U3a+U3b(+.1) ACCEPTED and deployed. U4a MERGED (PR #71 r3, three
review rounds, owner word 2026-08-04, main 95c7974; 262 tests green on the merged tip).**
Deployment phase next, gated by the 6 reviewer criteria on the PR #71 thread: env values
TC_DECISION_TARGET_ENVIRONMENTS=production + TC_DECISION_URL_HOSTS=www.tossacycling.com,
tossacycling.com · controlled v3→v4 migration · full VPS suite · seed one real decision
(decision-propose) · owner browser approve/reject acceptance · confirm no Apply/Execute/Verify
control. Spec authority: docs/workpackages/WP-U4-DECISION-WORKFLOW.md. Deploys touch BOTH the
app checkout (weekly path — controlled ff runbook) and the Console release (deploy-console.sh).

## Blocked on

Owner-run deployment (lead has no SSH — plan lands in chat; owner executes and pastes outputs).

## Next action

1. Owner: run the U4a deploy plan (chat), then the in-browser acceptance click-through.
2. Monday 08-10: artifact #1 (U3a live acceptance) + the Gmail-vs-Console behavioral capstone.

## Standing constraints

Autodeploy DISABLED by decision · manual deliberate deploys only · all server Git as `tcgrowth`
(D5) · owner is release authority · permanent dangers in docs/STANDING-CAUTIONS.md (incl. the
DO_NOT_RESTORE compromised backup) · see PRODUCTION_BASELINE_V1.md for the baseline reference
(note: its commit pins predate today's Console release — the baseline records the 2026-08-02
state by design).
