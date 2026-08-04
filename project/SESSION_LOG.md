# SESSION LOG — append-only breadcrumbs

## 2026-08-03

Completed
- Weekly report run#22 verified (status=0/SUCCESS, ledger ok) — first production Monday through the validator
- Production Baseline v1 recorded (144a173)
- WP-CONSOLE-USABILITY spec v1+v2 (69ea559)
- Deploy-script provenance fix (d260726) — found by U1 dry-run
- Console U1 fix round (63448f3): stream keepalive, nav truth, durable evidence store (TC_DB_PATH)
- Console redeployed twice (d260726 → 63448f3), U1 ACCEPTED in-browser (f222f03; evidence run#24)
- /project protocol adopted and seeded (19ef4b1)
- Protocol v1.1: chat-is-not-canon invariant, multi-engineer rules, reviewer bundles; docs/STANDING-CAUTIONS.md created (DO_NOT_RESTORE backup warning was chat-only until now)
- Codex governance onboarding read (at baf81b6): found HANDOFF stale main pin + wrong "3 doc-only" drift claim — both conceded; HANDOFF corrected with verified drift statement; protocol gains no-self-invalidating-pins corollary
- Reviewer gained GitHub READ connector (no write, by design); CODEX-1 refined to Repository Auditor role with validation task: docs-only PR modernizing WP-CONSOLE-DEPLOYMENT.md
- PR #67 (Codex): runbook modernized — lead-reviewed (193 green on branch), rebase-merged cd4623f. Full governed loop proven; CODEX-1 DECIDED. Found: shared GitHub identity blocks same-account approvals (recorded in PROTOCOL); new ops rule: retain N-1 release worktree until next successful deploy

- U2 EXECUTED: ops.tossacycling.com live (IONOS DNS + Plesk subdomain + Let's Encrypt + Apache-only proxy — no nginx on box, rate-limit deviation recorded; htpasswd perms fix). Verified through URL: SMTP + 114.9s scan (run#27). Token rotated (F4 closed). Logout built + tested (194 green). RUNBOOK-CONSOLE.md written

- U2 ACCEPTED: Console release ab9afa4 deployed; Sign out verified in-browser. U1+U2 done same day

- BUSINESS QUEUE CLEARED: D#9+D#10 executed by owner in WP, lead-verified live (all 4 URLs, ES+EN correct); P3-ES closed (real ES bookings); D#11 closed with reviewer-revised rationale (GA4=attribution, Woo=truth; 93 orders/€11,604 evidence). Record: docs/decisions/2026-08-D9-D10-D11.md. YoY −21% flagged as business observation

- U3a BUILT on feature/u3a-report-artifacts: schema v3 + immutability trigger, hash chain persist-before-deliver, delivery-by-hash, CLI reads, migration test, 201 green. Awaiting review + owner-authorized merge (touches Monday path)

- U3a review: 2 findings (stale branch base; hash-only delivery ambiguity on twin bodies) — both fixed (rebase; ArtifactBody id-binding, fail-closed mismatch, twin regression tests; report-redeliver). 205 green. AUTHORIZED + MERGED f0e5a50

- CI break on main (f0e5a50/7bab5ca): cross-test-module import failed CI's bare-pytest shape (passes python -m pytest locally + VPS). Fixed de3d8d7, CI green in 39s. New protocol rule: pusher verifies CI after every main push

- U3a DEPLOYED: converged b6779cc→d391247, 205 on VPS, v2→v3 migration clean, ledger intact, timer armed. Artifact #1 lands Monday 08-10

- U3b BUILT on feature/u3b-operator-homepage: home five-questions view, /report/<id> chain-metadata view, real Cases tab, redeliver_latest_report registry op, 213 green. Awaiting review

- U3b reviewer criteria recorded: behavioral capstone (Gmail-vs-Console on Monday), homepage checklist, anti-report rule, standing manual-elimination product bar. U3B-1 queued for owner authorization

- U3b reviewer-authorized; U4 opening requirement recorded (U3b=what needs attention, U4=why approve; evidence+impact before controls) + post-Monday owner-behavior instrumentation note. Merge held for OWNER word (reviewer input ≠ authorization)

- U3b MERGED (owner GO): rebased, 213 green, ff to main. Console redeploy pending

- U3b DEPLOYED (release 48e91d7) + in-browser acceptance: STRUCTURAL PASS, 4 observations (truth panel caught uncapped allow_writes + wrong/unconfirmed WP host; store decisions unsynced D#9/10/11; hierarchy debt -> U3b.1 polish adopted). Reviewer: usability 7/10, "beginning of an operations product"

- U3b.1 built+merged (94463c3, CI green, 214 tests): status card first (green all-clear / red top-decision with rationale+age), truth panel to bottom, severity accents, heading hierarchy. Reviewer's 10%-polish budget respected

- O1+O3 executed + U3b.1 DEPLOYED (Console release fd8f682, health 200): decisions approved in store (after lead's decision-set/decision-approve command-name fix), TC_ALLOW_WRITES=false live. O2 (WP host question) still open

- Reviewer wrote issue #68 (U3b UX review + U4 charter) — first reviewer write artifact. Lead replied on-thread (gap 4's simple card already shipped in fd8f682). GitHub-bus workflow ADOPTED (PR threads for increments; owner only authorizes); defer-Issues decision reversed with rationale. PROTOCOL updated

- O2 closed: dev.tourdegirona.com confirmed as Tossa's staging WP (intentional cross-domain; recorded in STANDING-CAUTIONS to prevent future false alarms). U3b observation set fully resolved

- GitHub bus round-trip complete on #68: reviewer accepted all points on-thread + added U4 requirement (auditable eliminated-actions table: disappears vs intentionally-manual); lead committed to it on-thread. Zero owner clipboard involved

- U4 spec written + PR #69 opened (owner GO — no waiting): eliminated-actions table, schema v4, content-bound approvals, verify-execution loop closing production decisions WITHOUT production writes, U2 basic-auth retirement trigger. Lead subscribed to the PR; review happens on-thread

- PR #69 review round 1: nine technical points (envelope binding, canonical hashing, state machine+concurrency, Verify-not-Execute naming, exact fail-closed verification, provenance on estimates, honest unknown counts, staging-apply OVERCLAIM conceded->dependency (verified on main), authority identity). ALL addressed in spec r2 (b02180a), point-by-point reply on thread. Fully on the bus — zero owner clipboard

Current
- PR #69 spec r2 awaiting re-review + owner merge word; then U4a build. Monday: artifact #1 + capstone

Blocked
- Nothing hard; business queue on owner (see OWNER_QUEUE.md)

Next
- U3a artifact persistence; owner business queue (P3-ES, D#9, D#10, D#11)

## 2026-08-02 (prior sessions, reconstructed from records)

Completed
- Accelerated validation runs #20/#21 both PASS — reporting gate closed (7655159)
- Validator branch rebased onto main, deployment plan reviewed (WP-REPORT-VALIDATION-DEPLOYMENT.md)
- Production checkout converged 527fdea → 7655159 (183 tests) → validator merged → b6779cc (190 tests)
- Validator live; run19-narration rejected / run20-genuine accepted on deployed code
- Notify hotfix captured to patch + cleaned (lives in feature/technical-inspector)
