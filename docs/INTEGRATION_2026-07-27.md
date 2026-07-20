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

**Order:**

| # | Branch | Acceptance protocol |
|---|---|---|
| 1 | `feature/site-intelligence` | WP-06 acceptance: first live snapshot on the VPS, mechanical + behavioral grading |
| 2 | `feature/source-reader` | WP-07 acceptance: deploy TC_SOURCE_ROOTS + ACLs (re-check after update), nine-point qTranslate citation exercise |
| 3 | `feature/prompt-caching` | docs/PROMPT_CACHING.md protocol: venv SDK version check, service restart, validation pair within TTL, ledger query |
| 4 | urgent hardening patches (small, separate commits) | day-one items: stored XSS (R17), deploy-evidence overclaim (R13), autodeploy bash order (R14), **smoke acknowledgement (SMOKE-01, below)** |
| 5 | `docs/master-roadmap-capture` + `docs/evidence-platform-spec` | docs-only; may be grouped — no executable overlap; suite run once after the group |
| 6 | `feature/action-registry` | **merges LAST**: it is stacked on source-reader and its drift tests must validate the FINAL combined command/phase surface, not an intermediate state; suite + `list-operations` output recorded |

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
