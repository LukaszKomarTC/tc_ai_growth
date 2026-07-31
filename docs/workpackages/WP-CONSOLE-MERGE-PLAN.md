# Operations Console — merge plan (Scenario B: decoupled foundation)

**Decision (2026-07-29):** Scenario B — extract a minimal registry/execution/Console foundation
into `main` as clean, independently-reviewed layers, then register accepted operations one at a
time. NOT a bundle merge of the stacked branch. Owner is release authority; nothing merges to
`main` until the owner authorises and the restarted validation gate is satisfied. This document is
the plan only — it touches nothing on `main`.

## Governing constraints

- **Extraction, not rewrite.** Move proven code into clean dependency layers. Do NOT change APIs,
  names, UI, or behaviour except the minimum needed to remove dependency coupling — otherwise the
  hard-won VPS acceptance evidence (SMTP `run#5`, Integrity clean/findings/clean) is invalidated.
- **The deployed commit is the source of truth.** The VPS runs `94c945a`. The extracted
  foundation must be behaviourally identical to it for the two accepted operations.
- **Freeze still holds.** Extraction branches may be BUILT and reviewed now; the merge to `main`
  is a separate, owner-authorised step.

## What is actually NEW on the branch (vs. `main` @ 527fdea)

Already on `main`: runtime, tools framework, `report.py`, `config`, `store`, **`core/approval.py`
(the phase gate)**, dashboard, existing analytics tools, CLI base. These are NOT extracted.

New, and the ONLY things the Console foundation needs:
- `core/actions.py` — the Action Registry (schema + validation + `OUTCOME_SEVERITY` + `timeout_s`)
- `core/executor.py` — the origin-agnostic Execution Service
- `console.py` — the loopback UI
- `report.py` addition — `smtp_test_steps()`
- `cli.py` additions — `smtp-test`, `integrity-scan` commands
- `scripts/wp-integrity-scan.sh` — the inspector
- `scripts/deploy-console.sh` + the WP-CONSOLE-*.md docs

NOT part of the foundation (each merges later, independently, with its own acceptance):
`core/site_intel.py`, `core/lifecycle.py`, `tools/site_intel.py` (WP-06); `core/source_reader.py`,
`tools/source_reader.py` (WP-07); their `TOOL_MIN_PHASE` entries; their registry operation entries.

**Consequence — the extraction is clean:** SMTP Test and Integrity Scan are `command=` operations,
not `tool=` operations, so the foundation needs NO `TOOL_MIN_PHASE` tool entries and does not
import a single WP-06/WP-07 module. The import DAG (`console → executor → actions → approval`,
stdlib only) is already proven. Extraction is additive-onto-main, not history surgery.

## The fork that must be decided first (OBS-1)

`core/actions.py` on the branch lists operations bound to WP-06/WP-07 tools. On the VPS, clicking
`Refresh site-structure snapshot` returned `404 rest_no_route` (OBS-1) — the registry advertised a
capability whose backing isn't present. The foundation must not carry that gap into `main`. Two ways:

**Option A — subtraction (recommended).** The foundation's `actions.py` lists ONLY the accepted
operations (`smtp_test`, `run_integrity_scan`). WP-06/07/backup entries are simply *absent* until
their capability merges; each capability merge adds its own entry. OBS-1 becomes impossible in
`main` (an unlisted op cannot be clicked). No new mechanism → truest to "no redesign" → smallest,
most boring first merge. Downside: the catalogue doesn't advertise the roadmap.

**Option B — three-state model (`declared`/`available`/`accepted`).** Keep all entries; add a
status field + availability check so unbacked ops render disabled/"pending." Preserves the full
catalogue as a roadmap and fixes OBS-1 by *display*. But this is a NEW mechanism — new behaviour,
its own small acceptance — which contradicts "extraction, not rewrite" for the very first merge.

**Recommendation: A for the foundation merge; B later as its own reviewed feature if/when we want
roadmap visibility.** OBS-1 is a *safety* issue and A fully resolves it (absent ⇒ unclickable);
B is an *enhancement* (advertising pending capabilities), not a fix. Keep the first `main` merge
minimal; introduce the three-state model deliberately afterward, with acceptance, when a
"declared-but-pending" op actually earns a place in the catalogue.

## Merge sequence (each layer its own reviewed PR off `main`)

1. **Tag the validated baseline** — `console-vps-accepted-94c945a` on the branch, so the accepted
   state is permanently referenceable.
2. **Registry Foundation** — `core/actions.py` reduced to accepted ops (Option A), with schema,
   validation, `OUTCOME_SEVERITY`, `result_policy`, `timeout_s`, approval class, environments,
   arg allowlist. No WP-06/07 imports or entries. Tests: `test_action_registry.py` (trimmed).
3. **Execution Service** — `core/executor.py`: origin-agnostic executor, phase enforcement,
   `interpret_exit`, evidence persistence, step events, provenance. Tests: `test_executor.py`.
4. **Console UI** — `console.py`: auth + CSRF, preview, streaming, logs, evidence, env badge, the
   `report.smtp_test_steps` + `cli` command additions. Tests: `test_console.py`.
5. **Register SMTP Test** — its registry entry + `smtp-test` binding (may fold into 2/4; kept
   nominal to preserve the "operations register individually" discipline).
6. **Register Technical Inspector** — `run_integrity_scan` entry + `integrity-scan` binding +
   `wp-integrity-scan.sh` + `deploy-console.sh`.
7. **Post-merge regression acceptance (SMALL, not the full fixture drill):** from a fresh worktree
   at the merged `main`, redeploy and confirm — Console starts; login/CSRF; SMTP → completed/
   success; Integrity → completed/clean; evidence persists; provenance stamped. Re-run the
   controlled-fixture drill ONLY if extraction materially changed scanner execution (it should not).
8. **Only then** reopen OP3 and the queued WP-06/WP-07 branches, each rebased onto the new `main`
   and merged with its own acceptance.

## What this explicitly is NOT

- Not a bundle merge of `feature/operations-console`.
- Not a redesign — no API/name/UI/behaviour changes during extraction.
- Not a merge performed without owner authorisation + the validation gate.
- Not the moment to build the three-state model (that is deliberate later work).
