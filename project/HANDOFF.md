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
- Console release (tc-console): `9dd11ef` from `/opt/tc_ai_growth/releases/9dd11ef…` — verified:
  owner-run apply + health 200 + 5-check acceptance @ 2026-08-04 (U4a.2). Env truths persist in
  /etc/tc-console.env across releases (proven). Rollback: `releases/8dafa5c…` retained (N-1);
  older release dirs removable

## Current work

**WP-CONSOLE-USABILITY: U1+U2+U3a+U3b(+.1) ACCEPTED · U4a FULLY CLOSED 2026-08-04** (three
increments #71/#72/#73 through the full loop; closure record in WP-CONSOLE-USABILITY.md §U4a).
Production state: app checkout a3104a8 (schema v4, D#12 rejected/superseded, D#13 approved =
as-applied homepage SEO, live-verified both languages); Console release 9dd11ef; env context
TC_DECISION_TARGET_ENVIRONMENTS=production + TC_DECISION_URL_HOSTS set (hosts line hygiene
confirmed via seeding success). Next increment: **U4b** per
docs/workpackages/WP-U4-DECISION-WORKFLOW.md §Verification — verify_decision_execution (two
owner-triggered reads ≥60s apart, store-backed verification_pending, immutable
decision_verify_attempts rows, URL-equality rules, fail-closed both-languages match) ->
decisions marked executed with evidence. D#13 is the natural first verification target.

## Blocked on

Nothing — PR #74 (U4b) review proceeds on-thread; owner queue empty.

## Next action

1. Reviewer round on PR #74 -> lead fixes on-thread -> owner word merges -> deploy (app
   convergence for schema v5 + console redeploy) -> owner acceptance: Verify D#13 live.
2. Monday 08-10: artifact #1 (U3a live acceptance) + the Gmail-vs-Console behavioral capstone.

## Standing constraints

Autodeploy DISABLED by decision · manual deliberate deploys only · all server Git as `tcgrowth`
(D5) · owner is release authority · permanent dangers in docs/STANDING-CAUTIONS.md (incl. the
DO_NOT_RESTORE compromised backup) · see PRODUCTION_BASELINE_V1.md for the baseline reference
(note: its commit pins predate today's Console release — the baseline records the 2026-08-02
state by design).
