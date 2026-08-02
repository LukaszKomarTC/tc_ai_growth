# Weekly-report validation — closure record

**Closed 2026-08-02.** The accelerated, evidence-based protocol (docs/EVIDENCE_BASED_VALIDATION.md)
is satisfied: two timer-fired, unattended, human-graded weekly-report runs, separated in time,
both PASS. This replaces the Monday-calendar criterion for report quality (owner decision, recorded
in WP-CONSOLE-MERGE-RECORD.md).

## Evidence

| Run | Trigger | Ledger | When | Cost | Grade |
|---|---|---|---|---|---|
| #1 | temporary systemd timer (OnActiveSec) | `weekly-report-validation` #20 | 2026-08-01 13:26 UTC | $1.6179 | PASS — full 4-section report, provenance table, observation/hypothesis discipline, D#9/D#10 proposed |
| #2 | temporary systemd timer, ~24h later | `weekly-report-validation` #21 | 2026-08-02 15:55 UTC | $0.6996 | PASS — full report; caught /shop/ pos-2 SERP anomaly, ES/EN conversion-gap analysis, proposed D#11 |

Both proved: timer→service handoff · unattended execution · production context (tcgrowth, real
cwd, real unit semantics) · email delivery · complete substantive artifact · human review. Run #2
additionally proved repeatability after ~24h of normal operation — the distinct question separation
was designed to answer.

**Run #2 technical evidence (verified 2026-08-02).** `tc-weekly-report-validation.service` finished
`status=0/SUCCESS` (start 15:55:03 → deactivated 16:01:24 UTC), `TriggeredBy` the timer; ledger row
`#21 … weekly-report-validation ok $0.6996`. Both the quality grade (email) and the technical result
(exit 0 + ledger `ok`) are now confirmed for both runs — the gate is formally closed on evidence,
not just on the email read.

Contrast: run #19 (2026-07-31) finished `ok` having emailed only planning narration — the defect
that motivated the fail-closed validator (fix/weekly-report-artifact-validation).

## What this closes and does NOT close

- CLOSES: the weekly-report *quality* gate. Report generation is trusted again.
- Does NOT close: nothing about the Console (separately accepted). Monday's `tc-weekly-report.timer`
  stays armed as ongoing monitoring, not a gate.
- The fail-closed artifact validator (+ lint word-boundary fix) remains UNDEPLOYED on its branch —
  it deploys in the validator round below, now proven to accept run #20's genuine body and reject
  run #19's narration.

## Follow-ups unlocked (owner-run, in order)

1. Remove the temporary units:
   `systemctl stop tc-weekly-report-validation.timer` (already stopped) ·
   `rm /etc/systemd/system/tc-weekly-report-validation.{timer,service}` · `systemctl daemon-reload`
2. Validator deployment round (branch `fix/weekly-report-artifact-validation`, 3 commits) — needs a
   reviewed plan because it updates the production app checkout the weekly timer runs from.
3. Console deploy from clean `main` + short regression.
4. Retire `feature/operations-console`; reopen OP3 / WP-06 / WP-07.

## Pending owner decisions surfaced by the reports (business, not infra)

D#9 (bilingual title/meta, /alquiler_bicicletas), D#10 (guided-tours hub), D#11 (resolve
TRK-20260706-050158 after WP-admin order cross-check). These are growth decisions awaiting approval.
