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
- Console release (tc-console): `63448f3` from `/opt/tc_ai_growth/releases/63448f3` — verified:
  deploy apply output + health check HTTP 200 @ 2026-08-03 ~09:33 UTC; U1 acceptance in-browser
  (evidence run#24)

## Current work

**WP-CONSOLE-USABILITY, U2 essentially complete** (2026-08-03 evening):
https://ops.tossacycling.com is LIVE — TLS (Let's Encrypt + 301), Apache basic auth (no nginx on
this Plesk: rate-limit deviation recorded in the runbook), proxy to loopback :8385. Verified
through the URL: SMTP test + full 114.9s integrity scan (evidence run#27). Token rotated (F4
CLOSED). RUNBOOK-CONSOLE.md delivered. Remaining: one 5-min Console redeploy from main tip to
ship the new Sign out button (last U2 checkbox), then U2 acceptance closes.

## Blocked on

Nothing hard — U2-F is a 5-minute owner convenience; U3a can start regardless.

## Next action

1. Owner: 5-command Console redeploy (queue item U2-F) → Sign out visible → U2 CLOSED.
2. Then: U3a (immutable report artifact persistence) per WP-CONSOLE-USABILITY.md.

## Standing constraints

Autodeploy DISABLED by decision · manual deliberate deploys only · all server Git as `tcgrowth`
(D5) · owner is release authority · permanent dangers in docs/STANDING-CAUTIONS.md (incl. the
DO_NOT_RESTORE compromised backup) · see PRODUCTION_BASELINE_V1.md for the baseline reference
(note: its commit pins predate today's Console release — the baseline records the 2026-08-02
state by design).
