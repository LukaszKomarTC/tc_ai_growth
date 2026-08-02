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

**Autodeploy is the DESIGNED delivery mechanism — but it is currently DISABLED.** The owner ran
`systemctl disable --now tc-autodeploy.timer` earlier in the freeze, so merging to `main` right now
delivers *nothing* to `/opt/tc_ai_growth/app`. The GitOps path (merge → server-side test-gate →
restart-or-rollback) is the right shape for this change and the target end-state, but it is not the
current reality. So the deploy is a two-part decision, not a one-line merge:
- **Delivery:** either re-enable `tc-autodeploy.timer` (preferred — it is the tested, self-rolling
  path) *after* the checkout is clean and aligned with `main`, or perform a one-time manual
  pull+install+test+restart under this reviewed plan and re-arm autodeploy after.
- **Trigger:** the merge to `main` only matters once delivery is live.

This also corrects an earlier assumption that production tracks the `claude/wordpress-ai-growth-agent-*`
branch and would need a surgical back-port. It does not — autodeploy (when enabled) tracks `main`.
(A back-port onto that branch was proven clean as a fallback, but it is not the production path and
would only deepen divergence.)

## Why recon must come first

The server was last observed at commit `527fdea` (owner-authored, 2026-07-20) with a *staged,
uncommitted* `cli.py` notify hotfix, and **autodeploy disabled** — which fully explains why the
checkout never advanced to main's tip (`7655159`): with the timer off, nothing pulls. On top of
that the working tree is dirty (a `git pull --ff-only` would refuse over local changes even if the
timer were re-armed). Three things must be established before merging, and only recon can confirm
the live state of each:

1. **Autodeploy's actual state** — disabled (owner's recollection) vs. re-enabled-but-stuck. This
   decides the whole delivery path; do not assume, verify (`systemctl is-enabled/is-active`, log).
2. **The staged notify hotfix is captured in Git, or deliberately discarded.** An uncommitted fix
   that lives only on the server violates the freeze protocol and would be destroyed by a reset. If
   it matters, it lands as a commit first; if it is stale, it is cleared on purpose.
3. **The checkout can reach a clean `main` that ff-tracks `origin/main`** before any delivery —
   whether that delivery is a re-enabled autodeploy or a manual pull.

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
and a **deliberately chosen delivery path** (autodeploy re-enabled, or manual). Do not leave
autodeploy half-on: either it is enabled and known-good, or it stays disabled and we deliver by hand.

## STEP 2 — merge validator to `main` (owner-authorized)

Fast-forward merge (validator branch is `main` + 3 code commits — no merge commit needed), consistent
with prior practice:

```bash
git checkout main && git pull --ff-only origin main
git merge --ff-only fix/weekly-report-artifact-validation
git push origin main
```

The merge advances `origin/main` by the validator commits. **It does not itself deploy** — with
autodeploy disabled, `origin/main` and the server checkout are decoupled. Delivery is STEP 3.

## STEP 3 — deliver to the server (path chosen in STEP 1)

**Path A — re-enable autodeploy (preferred; the tested, self-rolling path).** Only once the checkout
is clean `main`:

```bash
sudo systemctl enable --now tc-autodeploy.timer     # owner runs
# within ~5 min, observe (read-only):
tail -n 30 /opt/tc_ai_growth/app/orchestrator/data/autodeploy.log
cat /opt/tc_ai_growth/app/orchestrator/data/last_deploy.json   # expect result:"deployed", tests green
git -C /opt/tc_ai_growth/app rev-parse HEAD                    # expect main tip
```

**Path B — one-time manual deploy (if autodeploy stays disabled).** Mirror what autodeploy does, by
hand, so the server test-gate still runs before anything serves:

```bash
cd /opt/tc_ai_growth/app && git pull --ff-only origin main
.venv/bin/pip install -q -e 'orchestrator[anthropic,google,dev]'
(cd orchestrator && ../.venv/bin/python -m pytest -q)          # MUST be green before proceeding
# no dashboard restart needed for the weekly-report path; it re-reads code each run
```

Either way, autodeploy runs (or we run) the full test suite on the server itself; a green run is the
deploy's own proof. On failure, do not advance — roll back (below) and fix `main`.

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

- **Path A (autodeploy on):** server test failure → autodeploy reverts to the prior commit and
  reinstalls automatically. To undo a *green* deploy, `git revert` the merge on `main` and push;
  autodeploy pulls the revert.
- **Path B (manual):** `git revert` the merge on `main`, push, then `git pull --ff-only` + reinstall
  on the server. No direct server edits either way — rollback is a Git operation.

## Governance

Owner is release authority; this plan is authorized before STEP 2 runs. Autodeploy is currently
**disabled** — so the delivery path (re-enable vs. manual) is itself an owner decision, made from
recon, not assumed. All changes reach the server through `origin/main` — never a hand-edit on the
box. The staged `cli.py` hotfix is the one open thread that must be resolved into Git during STEP 1.
