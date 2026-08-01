# Evidence-based validation protocols (governance principle)

**Adopted in principle 2026-08-01** (owner + reviewer, during the accelerated weekly-report
validation), for use in **future** acceptance protocols. Existing in-flight gates finish under
the rules they started with.

## The principle

Validation protocols should be **evidence-based, not calendar-based**. A waiting period is only
justified by the evidence it produces — never by the calendar itself. Before requiring a wait,
name the question the wait answers; if a faster mechanism answers the same question honestly
(e.g. a temporary timer-fired run), use it and record it explicitly for what it is.

Each additional validation step must answer a **different question** than the steps before it.
Repetition without a new question is cost, not evidence. (Run #1 proved timer→service handoff,
unattended production execution, delivery, and artifact quality. Run #2's question is different:
*does the mechanism still produce a valid artifact after the system has operated normally for
some time?* — which is why 25 minutes of separation was rejected and several hours required.)

## Template acceptance checklist (replaces "wait until <weekday>")

```
Acceptance requires:
  ✓ one scheduled timer execution        (proves the unattended trigger path)
  ✓ one separated repeated execution     (proves repeatability over elapsed operation)
  ✓ one human review of the artifact     (proves quality, not just exit status)
  ✓ no critical defects observed         (and any found are recorded + fixed in Git)
  ✓ identical execution path to production (same user, cwd, unit semantics, code)
```

Time separation is still required **where it adds evidence** (the "separated repeated
execution"); what is dropped is the arbitrary calendar anchor.

## Provenance

Born from the 2026-07/08 sequence: the Monday-anchored clean-report gate coupled unrelated
work (the accepted Operations Console) to a calendar event; the owner decoupled them, replaced
the calendar rule with two labelled, timer-fired, human-graded validation runs, and stopped a
prematurely re-armed second run because it would have answered no new question. Full context:
`docs/workpackages/WP-CONSOLE-MERGE-RECORD.md` and the run #19/#20 record on
`fix/weekly-report-artifact-validation`.
