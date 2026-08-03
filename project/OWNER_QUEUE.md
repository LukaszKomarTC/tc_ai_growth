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
| U2-F | Low | Final U2 step: redeploy Console from main tip (adds the Sign out button) — the proven 5-command release loop | docs/RUNBOOK-CONSOLE.md; WP-CONSOLE-USABILITY §U2 | 5 min at the server terminal, any time | 2026-08-03 | waiting |

## Decided (index — details live at the pointer)

| ID | Decision | Recorded at |
|---|---|---|
| — | Accelerated validation replaces Monday-calendar gate | docs/workpackages/WP-CONSOLE-MERGE-RECORD.md |
| — | Autodeploy stays disabled pending its own review | docs/workpackages/WP-REPORT-VALIDATION-DEPLOYMENT.md §Governance |
| U1 | Console U1 accepted | docs/workpackages/WP-CONSOLE-USABILITY.md (commit f222f03) |
| CODEX-1 | Codex onboarded as Repository Auditor | PR #67 (audit → docs-only PR → lead review → rebase merge cd4623f); project/PROTOCOL.md §Roles |
| U2-A | ops.tossacycling.com live: TLS + basic auth + Apache proxy to loopback Console; SMTP + 114.9s integrity scan streamed through it (evidence run#27); token rotated (F4 closed) | docs/RUNBOOK-CONSOLE.md; WP-CONSOLE-USABILITY.md §U2 |
