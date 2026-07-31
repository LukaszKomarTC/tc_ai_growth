# Operations Console — merge record & governance decision

## Merge executed (2026-07-31)

`main` fast-forwarded `527fdea → 5eca844`, bringing the Scenario-B Operations Console foundation
onto `main` as its layered commits:

- Registry Foundation (accepted ops only: `smtp_test`, `run_integrity_scan`)
- Execution Service + SMTP Test + Integrity Scan
- Console UI + deployment package
- Review round (command-binding invariant + evidence-persistence policy)

Verification at merge: fast-forward (zero conflicts, base `527fdea` unmoved); per-layer CI green
(142 / 169 / 182); post-merge full suite on `main` **183 green**; registry on `main` lists exactly
the two accepted operations. The weekly-report artifact validator was **not** merged — it stays on
`fix/weekly-report-artifact-validation`, undeployed, pending real-report fixtures.

## Owner governance decision (release authority)

> The owner authorizes the Scenario B Operations Console foundation merge based on its independent
> production acceptance evidence. The weekly-report calendar gate is prospectively replaced by two
> human-graded accelerated validation runs triggered automatically through systemd timers and
> separated in time. These runs are explicitly recorded as accelerated validation and are not
> represented as Monday runs. The normal Monday timer remains enabled for ongoing monitoring but is
> no longer a blocker for the independently accepted Console release.

Rationale: the Console and the weekly report are independent code paths with independent evidence.
The Console passed its own VPS acceptance (auth/access boundary, SMTP, integrity clean→findings→
clean, provenance, redeploy idempotency, session invalidation). Blocking its release behind an
unrelated report defect and a calendar date had no risk-control value.

## Follow-ups (owner-run, on the VPS)

1. **Deploy the Console from clean `main`** and run the short regression: login; SMTP → completed/
   success; Integrity → clean; controlled fixture → findings; remove → clean. (Same
   `deploy-console.sh`, pointed at a `main`-based release checkout.)
2. **Accelerated report validation:** two time-separated, timer-triggered, `--validation` runs,
   human-graded on current production code; capture the first genuine good report body as a
   validator fixture.
3. After (1)+(2): the stacked `feature/operations-console` branch can be retired; deploy the report
   validator once it's proven to accept real report bodies.

## Not changed by this merge

The weekly-report generation logic is untouched. `Operation.enabled` stays a kill switch, not the
three-state catalogue (separate later WP). Monday's `tc-weekly-report.timer` stays armed as
monitoring.
