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
| U3B-1 | U3b merge authorized (owner GO 2026-08-03) and merged to main; Console redeploy + in-browser acceptance next | WP-CONSOLE-USABILITY.md §U3b |
| U3B-O1 | Production-writes cap set (TC_ALLOW_WRITES=false in release env, deployed fd8f682) | WP §U3b acceptance O1 |
| U3B-O3 | Store synced: D#9/D#10/D#11 proposed→approved via decision-approve (correct CLI verb; 'decision-set' was a lead command-name error, caught by usage output) | WP §U3b acceptance O3 |
| U3B-O2 | Owner confirmed: `dev.tourdegirona.com` IS Tossa's staging WordPress host (cross-domain by design, not a config error) | docs/STANDING-CAUTIONS.md note |
| U4-SPEC | Owner GO 2026-08-04 → PR #69 rebase-merged (main f37dfb8); U4a opened against the 10 thread criteria | PR #69 thread; docs/workpackages/WP-U4-DECISION-WORKFLOW.md |
| AGENTS-1 | PR #70 merged to main (365f623): AGENTS.md attribution protocol in force; lead's 2 record alignments executed (AGENTS.md→PROTOCOL pointer; PROTOCOL reviewer-surface update) | PR #70 thread; /AGENTS.md; project/PROTOCOL.md §Reviewer access |
| U4A-1 | Owner "merge" 2026-08-04 → PR #71 rebase-merged (main 95c7974, 262 green on merged tip); deploy plan + browser acceptance next per the 6 thread criteria | PR #71 thread; WP-U4-DECISION-WORKFLOW.md |
