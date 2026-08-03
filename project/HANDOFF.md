# HANDOFF — where the next engineer starts

_Index, not authority (PROTOCOL.md). If this disagrees with git or the server, this file is wrong._

## Commits

- `main`: `f222f03` — verified: `git rev-parse HEAD` → f222f03 @ 2026-08-03 10:08 UTC
- Production app checkout (`/opt/tc_ai_growth/app`): `b6779cc` — verified: owner-run
  `git rev-parse HEAD` in server terminal @ 2026-08-03 (STEP 3b convergence; main is 3 doc-only
  commits ahead — no runtime difference, reconciles at next touch)
- Console release (tc-console): `63448f3` from `/opt/tc_ai_growth/releases/63448f3` — verified:
  deploy apply output + health check HTTP 200 @ 2026-08-03 ~09:33 UTC; U1 acceptance in-browser
  (evidence run#24)

## Current work

**WP-CONSOLE-USABILITY, increment U2** (fixed HTTPS access for the Console).
U1 ACCEPTED 2026-08-03 (record: docs/workpackages/WP-CONSOLE-USABILITY.md, commit f222f03).
U2 plan delivered to owner and reviewer-endorsed: Plesk subdomain `ops.tossacycling.com` + TLS +
transitional basic auth (retirement criteria in the WP spec) reverse-proxying loopback :8385,
then token rotation (F4), then RUNBOOK-CONSOLE.md.

## Blocked on

Owner executing U2 Phase A in Plesk (create subdomain + DNS + Let's Encrypt). Full phase list
A–F is in the chat-delivered plan; the durable spec is WP-CONSOLE-USABILITY.md §U2.

## Next action

1. Owner: U2 Phase A–C (Plesk + two terminal commands), paste any Plesk error back.
2. Claude: verify Phase D through the URL, guide token rotation (E), write RUNBOOK-CONSOLE.md (F).
3. Then: U3a (immutable report artifact persistence) per WP-CONSOLE-USABILITY.md.

## Standing constraints

Autodeploy DISABLED by decision · manual deliberate deploys only · all server Git as `tcgrowth`
(D5) · owner is release authority · see PRODUCTION_BASELINE_V1.md for the baseline reference
(note: its commit pins predate today's Console release — the baseline records the 2026-08-02
state by design).
