# OWNER QUEUE — the single interruption mechanism

_Invariant: **empty queue == don't disturb Łukasz.** Fields mirror the future platform decision
objects (PROTOCOL.md, Phase 2). Pointers, not copies — evidence lives where it lives._

## Waiting

| ID | Priority | Decision / action | Evidence | Recommendation | Waiting since | Status |
|---|---|---|---|---|---|---|

## Decided (index — details live at the pointer)

| ID | Decision | Recorded at |
|---|---|---|
| — | Accelerated validation replaces Monday-calendar gate | docs/workpackages/WP-CONSOLE-MERGE-RECORD.md |
| — | Autodeploy stays disabled pending its own review | docs/workpackages/WP-REPORT-VALIDATION-DEPLOYMENT.md §Governance |
| U1 | Console U1 accepted | docs/workpackages/WP-CONSOLE-USABILITY.md (commit f222f03) |
| CODEX-1 | Codex onboarded as Repository Auditor | PR #67 (audit → docs-only PR → lead review → rebase merge cd4623f); project/PROTOCOL.md §Roles |
| U2-A | ops.tossacycling.com live: TLS + basic auth + Apache proxy to loopback Console; SMTP + 114.9s integrity scan streamed through it (evidence run#27); token rotated (F4 closed) | docs/RUNBOOK-CONSOLE.md; WP-CONSOLE-USABILITY.md §U2 |
| U2 | U2 ACCEPTED — Sign out deployed (Console release ab9afa4) and verified in-browser | WP-CONSOLE-USABILITY.md §U2 acceptance record |
| D#9 | Executed: bilingual title/meta live on /alquiler_bicicletas (ES+EN, lead-verified by fetch) | docs/decisions/2026-08-D9-D10-D11.md |
| D#10 | Executed: bilingual title/meta live on /salidas_guiadas-listado (ES+EN, lead-verified) | docs/decisions/2026-08-D9-D10-D11.md |
| P3-ES | Closed on business evidence: real ES orders/bookings arriving; page-level rate stays under weekly monitoring | docs/decisions/2026-08-D9-D10-D11.md |
| D#11 | Closed, REVISED rationale: GA4 pipeline operational; WooCommerce = order/revenue truth, GA4 = attribution (93 orders / €11,604 net in window ≠ mismatch) | docs/decisions/2026-08-D9-D10-D11.md |
