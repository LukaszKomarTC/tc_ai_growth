# OWNER QUEUE — the single interruption mechanism

_Invariant: **empty queue == don't disturb Łukasz.** Fields mirror the future platform decision
objects (PROTOCOL.md, Phase 2). Pointers, not copies — evidence lives where it lives._

## Waiting

| ID | Priority | Decision / action | Evidence | Recommendation | Waiting since | Status |
|---|---|---|---|---|---|---|
| D#9 | High | Approve + publish bilingual SEO title/meta for `/alquiler_bicicletas` (post 13699) | Weekly report 2026-08-03 §1c Opp 1 (1,502 impressions, pos 14.9); draft queued in platform | Approve — but run P3-ES first (below) so new traffic lands on a working funnel | 2026-08-01 | waiting |
| P3-ES | High | Verify the Spanish booking journey end-to-end (rental page → calendar → add-to-cart → checkout, ES locale) | Weekly report 2026-08-03 §3d: 56 ES organic sessions → 0 conversions vs EN ~9% | Do before D#9 publish; ~30 min in WP/storefront | 2026-08-03 | waiting |
| D#10 | High | Approve + publish bilingual SEO title/meta for `/salidas_guiadas-listado` (post 48284) | Weekly report 2026-08-03 §1c Opp 2 (pos 4.1, CTR 0.75%); draft queued | Approve | 2026-08-01 | waiting |
| D#11 | Medium | Resolve tracking case TRK-20260706-050158 | Weekly report 2026-08-03 §3d: ~20 GA4 conv / ~€2,426 first clean window; needs WP-admin order-count cross-check 2026-07-08→08-03 | Cross-check, then resolve | 2026-08-02 | waiting |
| U2-A | High | Execute U2 Phase A–C in Plesk (create `ops.tossacycling.com`, DNS, TLS, proxy directives) | WP-CONSOLE-USABILITY.md §U2; phase plan delivered 2026-08-03 | Run when at a computer with Plesk access | 2026-08-03 | waiting |
| CODEX-1 | Low | Onboard Codex as **Repository Auditor** (role refined by reviewer 2026-08-03 after a 9.5/10 onboarding read that caught two real HANDOFF defects) | Onboarding report at `baf81b6`; guardrails: project/PROTOCOL.md §Multiple engineers | Yes. Validation task defined: audit → docs-only PR updating the stale deployment runbook WP-CONSOLE-DEPLOYMENT.md (reviewed branch is `main` not `feature/operations-console`; add TC_STORE_DB; `releases/<sha>` convention) — **historical records (ledger, merge plan/record) stay untouched: records are immutable history, runbooks must be current.** Claude reviews the PR; owner or lead merges. Passing = CODEX-1 done + the full governed loop proven | 2026-08-03 | waiting |

## Decided (index — details live at the pointer)

| ID | Decision | Recorded at |
|---|---|---|
| — | Accelerated validation replaces Monday-calendar gate | docs/workpackages/WP-CONSOLE-MERGE-RECORD.md |
| — | Autodeploy stays disabled pending its own review | docs/workpackages/WP-REPORT-VALIDATION-DEPLOYMENT.md §Governance |
| U1 | Console U1 accepted | docs/workpackages/WP-CONSOLE-USABILITY.md (commit f222f03) |
