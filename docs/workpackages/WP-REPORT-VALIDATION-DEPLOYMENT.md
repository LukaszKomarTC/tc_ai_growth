# Weekly-report validator — deployment plan (reviewed)

**Status: awaiting owner authorization + server recon. Nothing has been merged or deployed.**

This is the reviewed plan the closure record (WP-REPORT-VALIDATION-CLOSURE.md, step 2) requires
before the fail-closed artifact validator touches the production app checkout the weekly timer
runs from. It changes the code that emails the owner every Monday, so it is owner-authorized and
Git-only (freeze protocol: never patch the server by hand).

## What deploys

Branch `fix/weekly-report-artifact-validation` = `main` + 3 linear commits (fast-forwardable):

| Commit | Change |
|---|---|
| `477799b` | Fail-closed `validate_report_artifact` + `persist_run(status, detail)` + `cmd_weekly_report` gate (exit 1 + `[REPORT FAILED]` on invalid artifact) |
| `346342a` | First genuine real-corpus fixture: run #20 body (owner-graded PASS), `test_genuine_run20_report_is_accepted` |
| `6b858d8` | Lint `\bnot\b` word-boundary fix (run #20 `(NOT robots.txt)` false positive) |

Running-code blast radius is exactly two files, both in the weekly-report path:
`cli.py` (+11) and `report.py` (+86). The rest is tests + one fixture. Nothing else — no infra,
no Console code, no connector, no unit changes.

Pre-flight, verified locally:
- Rebased on current `main` (`7655159`); full suite **190 passed**.
- The validator now **accepts** run #20's genuine body and **rejects** run #19's narration —
  the accept/reject evidence the review demanded before deploy.

## Deployment architecture (verified from the repo, not memory)

There is ONE production checkout, `/opt/tc_ai_growth/app`, and two timers read from it:

- **`tc-autodeploy.timer`** (every 5 min, `orchestrator/scripts/autodeploy.sh`): GitOps on
  **`origin/main`**. On a new main commit it does `git pull --ff-only origin main`, reinstalls,
  runs the **full pytest suite on the server**, and restarts the dashboard **only if green** —
  otherwise it `git checkout`s the previous commit and reinstalls (auto-rollback). Kill switch:
  `systemctl disable --now tc-autodeploy.timer`.
- **`tc-weekly-report.timer`** (Mon 07:00 Europe/Madrid): runs `python -m tc_growth.cli
  weekly-report` from `/opt/tc_ai_growth/app/orchestrator` — the same checkout autodeploy maintains.

**Therefore the deploy IS the merge to `main`.** Autodeploy is the delivery mechanism and its
server-side test-gate + auto-rollback is the safety net. This is the right shape for this change:
small, tested, no infra. The weekly report picks up the new code on the following Monday.

This corrects an earlier assumption that production tracks the `claude/wordpress-ai-growth-agent-*`
branch and would need a surgical back-port. It does not — autodeploy tracks `main`. (A back-port
onto that branch was proven clean as a fallback, but it is not the production path and would only
deepen divergence.)

## Why recon must come first

The server was last observed at commit `527fdea` (owner-authored, 2026-07-20) with a *staged,
uncommitted* `cli.py` notify hotfix. If autodeploy were healthy the checkout would already be at
main's tip (`7655159`), so **it is probably stuck** — most likely because the working tree is dirty
(`git pull --ff-only` refuses to run over local changes) or HEAD is not on `main`. Two things must
be true before merging, and only recon can confirm them:

1. **The staged notify hotfix is captured in Git, or deliberately discarded.** An uncommitted fix
   that lives only on the server violates the freeze protocol and would be destroyed by a reset. If
   it matters, it lands as a commit first; if it is stale, it is cleared on purpose.
2. **Autodeploy can actually fast-forward `main`.** If it is stuck/dirty/disabled, merging to main
   deploys nothing (or deploys unpredictably). The checkout must be on a clean `main` that
   ff-tracks `origin/main` before the merge, or we deploy manually and re-arm autodeploy after.

## STEP 0 — server recon (owner runs; strictly read-only)

```bash
cd /opt/tc_ai_growth/app
echo "== branch/HEAD ==";        git rev-parse --abbrev-ref HEAD; git rev-parse HEAD
echo "== working tree ==";       git status --short
echo "== staged hotfix (cached diff) =="; git diff --cached
echo "== unstaged diff ==";      git diff
echo "== fetch main (read-only) =="; git fetch origin main --quiet && \
  echo "origin/main = $(git rev-parse origin/main)"
echo "== can it ff to main? =="; git merge-base --is-ancestor HEAD origin/main \
  && echo "HEAD is an ancestor of origin/main (ff-able if on main)" \
  || echo "HEAD is NOT an ancestor of origin/main (diverged — needs reconcile)"
echo "== autodeploy timer =="; systemctl is-enabled tc-autodeploy.timer; \
  systemctl is-active tc-autodeploy.timer; \
  systemctl list-timers tc-autodeploy.timer --no-pager 2>/dev/null | head
echo "== autodeploy log tail =="; tail -n 25 orchestrator/data/autodeploy.log 2>/dev/null
echo "== last deploy record =="; cat orchestrator/data/last_deploy.json 2>/dev/null
echo "== weekly-report timer =="; systemctl list-timers tc-weekly-report.timer --no-pager 2>/dev/null | head
```

Paste the output back. It tells us which branch the checkout is on, what the staged hotfix is,
whether autodeploy is enabled and when it last succeeded/failed, and whether HEAD can ff to main.

## STEP 1 — reconcile the checkout (only what recon shows is needed)

Chosen after reading STEP 0 output. Likely one of:

- **Staged hotfix matters** → capture it as a commit on the appropriate branch and land it in `main`
  BEFORE the validator merge, so it is not lost and is covered by the server test-gate.
- **Staged hotfix is stale/superseded** → `git restore --staged . && git checkout -- <file>` (owner
  runs, after we confirm it is truly redundant against main).
- **HEAD not on `main` / diverged** → move the checkout onto a clean `main` that ff-tracks
  `origin/main` (exact commands depend on recon; no force operations without explicit sign-off).
- **Autodeploy disabled** → decide whether to re-enable it (preferred: it is the tested path) or do
  a one-time manual pull+install+test+restart, then re-arm.

Goal state before STEP 2: `/opt/tc_ai_growth/app` on a **clean** `main`, working tree not dirty,
`tc-autodeploy.timer` enabled and known-good.

## STEP 2 — merge validator to `main` (the deploy trigger; owner-authorized)

Fast-forward merge (validator branch is `main` + 3 commits — no merge commit needed), consistent
with prior practice:

```bash
git checkout main && git pull --ff-only origin main
git merge --ff-only fix/weekly-report-artifact-validation
git push origin main
```

At this point `origin/main` advances by 3 commits and the next autodeploy tick (≤5 min) picks it up.

## STEP 3 — observe autodeploy carry it (do not touch the server)

Within ~5 minutes, on the server:

```bash
tail -n 30 /opt/tc_ai_growth/app/orchestrator/data/autodeploy.log
cat /opt/tc_ai_growth/app/orchestrator/data/last_deploy.json   # expect result:"deployed", tests green
git -C /opt/tc_ai_growth/app rev-parse HEAD                    # expect main tip
```

Autodeploy runs the 190-test suite on the server itself; a green run is the deploy's own proof.
If tests fail there, autodeploy auto-rolls-back and `last_deploy.json` shows `result:"rolled-back"`
— main is then the thing to fix, not the server.

## STEP 4 — post-deploy verification

```bash
grep -n "def validate_report_artifact" /opt/tc_ai_growth/app/orchestrator/tc_growth/report.py
# Optional dry check that a good body validates and narration does not (no email sent):
/opt/tc_ai_growth/app/.venv/bin/python - <<'PY'
from tc_growth.report import validate_report_artifact
print("narration:", validate_report_artifact("Good — all the data is in. Now I'll write the report."))
PY
```

The real proof is the next Monday report delivering normally (subject without `[REPORT FAILED]`),
and — the point of the whole exercise — a future narration-only run being caught and marked failed
instead of silently `ok`.

## Rollback

- **Automatic:** server test failure → autodeploy reverts to the prior commit and reinstalls.
- **Manual:** `git revert` the merge on `main` and push; autodeploy pulls the revert and redeploys
  the previous good state. No direct server edits.

## Governance

Owner is release authority; this plan is authorized before STEP 2 runs. All changes reach the
server through `origin/main` and autodeploy — never a hand-edit on the box. The staged hotfix is the
one open thread that must be resolved into Git during STEP 1.
