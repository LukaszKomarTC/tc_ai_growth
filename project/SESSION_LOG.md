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

Current
- U3a review round

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
