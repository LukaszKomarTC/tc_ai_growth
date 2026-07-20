# Release 0.3 close-out + integration programme (2026-07-27)

**Status:** pre-registered 2026-07-20, one week before execution. This EXTENDS the
close-out sequence already pinned in `docs/VALIDATION.md` — the first steps are identical
and are not reinterpreted here; the queue behind them grew during the freeze week, so the
integration half is now a programme, not a pair of merges. Controlled integration, not
code volume, is the constraint this week.

## Part 1 — gate close-out (unchanged, from VALIDATION.md)

1. Monday 07:00 run #3 arrives (scheduled; manual runs never count).
2. Grade against the pre-existing criteria. Capture commit identity alongside the report:
   `git rev-parse HEAD` in `/opt/tc_ai_growth/app` + `cat orchestrator/data/last_deploy.json`.
3. case_read evidence via the external observer script (pre-registered method).
4. Close the original boxes (0.3 does NOT sign off with case_read open).
5. Tag `release-0.3-validated` on the exact validated commit (527fdea).

## Part 2 — integration programme (one branch = one recorded release delta)

**Per-branch protocol, no exceptions for code branches:**

1. Merge ONE branch.
2. Run the complete test suite on the merged result.
3. Deploy to staging where the branch has runtime surface.
4. Execute that branch's acceptance protocol.
5. Record the resulting commit identity with the acceptance evidence.
6. Only then begin the next merge.

Never drain the queue quickly: tests passing per-branch does not prove combined
behavior, and losing track of which merge introduced a regression forfeits the clean
validated baseline the whole freeze existed to produce.

**Discipline under success (binding):** the pressure to rush arrives precisely when run
#3 is green and everything looks fine — a green branch is not evidence that the combined
system is green. During this programme: no opportunistic fixes, no reordered merges, no
"while we are here" changes, and no observer-retirement discussion until the registered
criteria are met. Anything discovered mid-programme is RECORDED (case, finding, or patch
item for a later batch), not fixed inline. Causal clarity outranks one or two days of
feature velocity.

**Order:**

| # | Branch | Acceptance protocol |
|---|---|---|
| 1 | `feature/site-intelligence` | WP-06 acceptance: first live snapshot on the VPS, mechanical + behavioral grading |
| 2 | `feature/source-reader` | WP-07 acceptance: deploy TC_SOURCE_ROOTS + ACLs (re-check after update), nine-point qTranslate citation exercise |
| 3 | `feature/prompt-caching` | docs/PROMPT_CACHING.md protocol: venv SDK version check, service restart, validation pair within TTL, ledger query |
| 4 | urgent hardening patches (small, separate commits) | day-one items: stored XSS (R17), deploy-evidence overclaim (R13), autodeploy bash order (R14), **smoke acknowledgement (SMOKE-01, below)** |
| 5 | `docs/master-roadmap-capture` + `docs/evidence-platform-spec` | docs-only; may be grouped — no executable overlap; suite run once after the group |
| 6 | `feature/action-registry` | **merges LAST**: it is stacked on source-reader and its drift tests must validate the FINAL combined command/phase surface, not an intermediate state; suite + `list-operations` output recorded |

## Part 3 — Release 0.3 retrospective (after the programme completes, before ANY 1.1 work)

Written to `docs/reviews/RETRO-0.3.md` once the last branch has merged and its acceptance
is recorded. About process, not bugs. Questions fixed NOW — before the outcome exists —
so the retro cannot drift into a victory lap or a blame exercise:

1. Which governance rules prevented mistakes? (name the incident each one caught)
2. For EVERY recurring control, classify and re-justify it (see the taxonomy below):
   has it moved Transitional → Operational → Constitutional, or is it ready to retire?
   A control that catches nothing isn't safety, it's cost wearing safety's clothes —
   but classification, not raw hit-count, decides: some controls exist precisely in the
   hope of never firing.
3. Which acceptance criteria were ambiguous when the moment came to grade them?
4. Which architectural decisions proved especially valuable?
5. What surprised us during integration?
6. What would we change before the next major release?

**Control taxonomy (governance principle, adopted 2026-07-20):**

- **Constitutional** — permanent unless governance itself changes: FORBIDDEN
  capabilities, the financial-transfer prohibition, production-write per-run approval,
  profile isolation. Retiring one is an amendment with cooldown, never a retro outcome.
- **Operational** — remain only while they demonstrably reduce risk: extra verification
  steps, review depth requirements, merge restrictions. The retro's main pruning ground.
- **Transitional** — exist to reach a maturity milestone and are EXPECTED to disappear,
  with retirement criteria pre-registered at creation: the observer dual-run, manual
  validation counters, the clean-Monday gate itself. A transitional control without
  retirement criteria is a defect — it will silently ossify into fake-constitutional.

**Proportionality rule (standing, feeds question 6):** release-programme rigor — freezes,
pre-registered evidence, one-branch-one-delta integration — is reserved for changes
touching architecture, execution authority, evidence integrity, production safety, or
platform-wide invariants. Routine feature work stays disciplined (branch, tests, review)
but is NOT burdened with programme ceremony. This complements the 0.3 admission filters:
those decide whether a change enters; this decides how much process weight it carries.
A retro that finds governance applied disproportionately to routine work must say so.

The retro is institutional memory: its answers feed the 1.1 planning directly, and no
1.1 design work starts until it exists. The freeze-week's own lesson is pre-seeded as its
first data point: the binding constraint stopped being code volume and became controlled
integration and owner attention — 1.1 planning must budget for that from the start.

## SMOKE-01 — privileged diagnostic path hardening (finding, 2026-07-20)

**Finding:** the `smoke` command is a privileged diagnostic execution path that bypasses
orchestrator phase and profile-cap enforcement (`cmd_smoke` dispatches directly). It
relies on operator intent and connector-side protections, which reduce blast radius but
are not equivalent controls. Surfaced while cataloguing reality for the Action Registry;
recorded honestly in the `run_smoke_test` entry.

**Required hardening (post-gate patch batch, step 4 — does not block 0.3):**

- Explicit environment acknowledgement:
  `smoke <tool> --confirm-target staging` — the command states its target and refuses
  when the resolved profile's environment does not match the acknowledgement.
- Write-capable tools additionally require `--acknowledge-write-risk`, and are rejected
  outright unless the target is staging (or, in the future, an approved production named
  operation via the 1.1 execution ledger).
- Registry entry updates from documentation to enforcement (`enforced_by` gains the new
  guard) only AFTER the guard exists and is tested — documentation is not enforcement.

## Observer retirement criteria (pre-registered — the checklist decides)

The Evidence Platform provenance model (runs carrying a metadata-only tool trace) will
eventually make the external observer script unnecessary — but self-reported evidence can
be wrong in exactly the way the action is wrong: the same defect can corrupt both the
behavior and its logging. Independent observation is valuable precisely because it does
not trust the system under test. Therefore:

- **Dual-run for at least one full release cycle** after the trace ships: every
  validation-relevant run captures BOTH platform-generated trace AND independent observer
  output; the two are compared per run.
- Retire the observer ONLY when all three hold:
  1. Several consecutive runs show agreement between trace and observer.
  2. The self-evidence path has negative-path tests: missing persistence, malformed
     trace, failed store write — each visibly marked, never silently absent.
  3. The retirement is recorded as a decision with the comparison evidence attached.

## Registry safety rule (standing)

An operation is not "safe" because its registry metadata documents rollback or
verification. Safety exists only when the corresponding mechanism is executable and
tested. The `*_description` → `*_handler` naming boundary in `core/actions.py` is the
permanent marker of that line; crossing it requires the handler plus its tests, never a
rename alone.
