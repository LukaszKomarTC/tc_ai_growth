# WP-U4d.2 — on-host acceptance: exact execution guide

*The concrete command sequence behind `U4D2-CONSOLE-ACCEPTANCE.md`. Section A (the technical
maintainer, terminal, once) installs and enables the machinery; Section B (the owner, browser
only) runs the acceptance. Every path/value below is the real production constant from
`tc_growth/deploy_target.py` — **confirm each against your actual host before running**, and note
that Section A touches production paths (`/usr/local/lib/tc-deploy`, `/usr/local/bin`,
`/etc/sudoers.d/tc-console-scan`). It is reversible (the `rollback` verb, and the drop-in/inspector
can be removed), but it is a real change to production infrastructure — run it as a controlled
deployment.*

Record before starting: **#80 engine head `386f332`**, and the exact **#81 surface head recorded
in the PR #81 body** (install that reviewed SHA, not a stale literal — the head advances as review
findings are addressed).

---

## Section A — technical maintainer (terminal, once)

> **Advancing to a newer reviewed head later?** Redo the whole of Section A at that head: A1
> (deploy-console from a new release worktree), A2's installer re-run (the privileged program's
> bytes and manifest change with the head), and A3's worktree + `bootstrap` at the new SHA. The
> dedicated deploy venv and the acceptance drop-in persist; the installer and bootstrap refresh
> what the head governs.
>
> **`bootstrap` will refuse if a trusted runtime already exists.** That is deliberate — it is a
> one-time setup action and will not replace an established runtime — but it means there is
> currently **no least-privilege verb that advances the trusted runtime to a newer head**
> (`apply` would do it, but only by also installing the full production-deploy sudo surface and
> rewriting the Console unit, which is a production posture change, not an acceptance step).
> Until that gap is closed, advancing the acceptance runtime is a **governed manual reset**:
> record the current state, confirm no service depends on the stale runtime, move (do not delete)
> the stale `current` + runtime tree + manifest into a root-owned `0700` quarantine, then
> `bootstrap` the new SHA and let the verified program recreate every trusted artefact. Never
> hand-write `current`, a runtime file or a manifest. This is tracked as a follow-up work item.
>
> You do **not** need to clean the release worktree first. Root materialises the runtime from the
> commit's objects, so the `__pycache__` a serving Console writes into its own release tree and
> the untracked `.env` beside it are neither copied into the trusted tree nor able to block the
> bootstrap. A *tracked* file that differs from the commit is still refused — that is
> substitution, not clutter.

### A1. Put the #81 code in service (release-dir deployment — the shape production actually has)

**Discovery from the first on-host prep:** the Console does *not* serve the `/opt/tc_ai_growth/app`
checkout. Its unit pins `WorkingDirectory` to a **detached release worktree** under
`/opt/tc_ai_growth/releases/<sha>` — with the shared venv's editable install, cwd wins module
resolution, so the release dir *is* the running code, and updating the app checkout + restarting
changes nothing the service executes. Deploy the reviewed head with the Console's own reviewed
deployment operation, `deploy-console.sh`, from a release worktree pinned at that head:

```bash
REVIEWED=<the #81 head SHA from the PR body>
sudo -u tcgrowth git -C /opt/tc_ai_growth/app fetch origin feature/u4d2-console-acceptance
sudo -u tcgrowth git -C /opt/tc_ai_growth/app worktree add --detach \
    /opt/tc_ai_growth/releases/"$REVIEWED" "$REVIEWED"
# the app config the Console reads from its cwd — copy it from the currently-serving release
sudo -u tcgrowth cp -p /opt/tc_ai_growth/releases/<current-serving-sha>/orchestrator/.env \
    /opt/tc_ai_growth/releases/"$REVIEWED"/orchestrator/.env

cd /opt/tc_ai_growth/releases/"$REVIEWED"/orchestrator
sudo TC_VENV=/opt/tc_ai_growth/app/orchestrator/.venv \
     TC_STORE_DB=/opt/tc_ai_growth/app/orchestrator/data/tc_growth.db \
     TC_RELEASE_BRANCH=feature/u4d2-console-acceptance \
     bash scripts/deploy-console.sh              # DRY RUN first — review the plan
# then, when the plan shows the right commit / clean tree / matching remote tip:
sudo TC_VENV=/opt/tc_ai_growth/app/orchestrator/.venv \
     TC_STORE_DB=/opt/tc_ai_growth/app/orchestrator/data/tc_growth.db \
     TC_RELEASE_BRANCH=feature/u4d2-console-acceptance \
     bash scripts/deploy-console.sh --apply
```

`TC_STORE_DB` must name the durable shared store, or acceptance evidence dies with the next
redeploy. The redeploy rotates the session epoch — sign in again with the same token. The Console
venv is **not touched** by any of this.

Also update the plain checkout (A3 stages the release worktree from it):

```bash
sudo -u tcgrowth git -C /opt/tc_ai_growth/app checkout "$REVIEWED"
```

### A2. Provision a dedicated root-owned deploy venv (the supported path)

**Why a separate venv — the on-host A2 discovery.** The privileged program refuses any interpreter
whose venv the service user can write, or whose imports resolve back into a service-user-writable
tree (`resolve_interpreter` → `assert_no_import_path_into_mutable_trees`). The Console's own venv is
service-user-owned and **editable** (`pip install -e`): its `__editable__*` finder points `tc_growth`
back at the checkout, so a root-owned interpreter would still import mutable code. The installer
**correctly refuses** it — that refusal is the boundary working, not an error. The Console venv is
the long-running application runtime and must stay exactly as it is; do **not** chown it and do
**not** overwrite it with `--provision-venv`.

The deploy/acceptance interpreter is therefore a **dedicated, root-owned, non-editable venv**,
distinct from the Console venv. `--provision-venv` creates and locks one; then install the
orchestrator into it **non-editably as root** (`pip install .` — never `-e`), so no import-redirecting
finder is written. (The shape difference — non-editable clean vs editable redirecting — is pinned by
`tests/test_u4d2_deploy_venv_shape.py`, which CI runs.)

```bash
cd /opt/tc_ai_growth/app/orchestrator
DEPLOY_VENV=/usr/local/lib/tc-deploy/deploy-venv     # root-owned; NOT the Console venv
```

`--source` defaults to `scripts/`, which carries `tc-deploy-privileged.sh`,
`lib/permission-guard.sh` and `wp-integrity-scan.sh`. `--provision-venv` creates the root-owned
venv at `--venv` and locks it (`chown root:root`, `go-w`); the installer runs the installed
program's `self-check` and fails if it does not verify.

```bash
sudo bash scripts/install-tc-deploy.sh \
  --prefix           /usr/local/lib/tc-deploy \
  --app-dir          /opt/tc_ai_growth/app \
  --releases-dir     /opt/tc_ai_growth/releases \
  --service          tc-console \
  --service-user     tcgrowth \
  --port             8385 \
  --unit-path        /etc/systemd/system/tc-console.service \
  --inspector-dest   /usr/local/bin/wp-integrity-scan.sh \
  --sudoers-file     /etc/sudoers.d/tc-console-scan \
  --snapshot-dir     /var/backups/tc-console \
  --unit-prefix      tc-deploy \
  --runtime-dir      /usr/local/lib/tc-deploy/runtime \
  --target-name      production \
  --backup-dir       /opt/tc_ai_growth/app/orchestrator/data \
  --evidence-namespace production \
  --remote-ref       origin/main \
  --store-db         /opt/tc_ai_growth/app/orchestrator/data/tc_growth.db \
  --venv             "$DEPLOY_VENV" \
  --provision-venv \
  --console-env-file /etc/tc-console.env
```

Then populate the locked deploy venv **as root, non-editably** (the application is also imported
from the authenticated runtime working directory, but installing it here keeps the interpreter
self-contained and writes no redirecting finder):

```bash
sudo "$DEPLOY_VENV/bin/pip" install "/opt/tc_ai_growth/app/orchestrator"   # non-editable — never -e
# confirm the boundary the guard checks: no .pth/__editable__ finder resolves into a writable tree
sudo "$DEPLOY_VENV/bin/python" - <<'PY'
import site, glob, os, pathlib
mutable = ("/opt/tc_ai_growth/app", "/opt/tc_ai_growth/releases")
bad = []
for s in set(site.getsitepackages()):
    for f in glob.glob(os.path.join(s, "*.pth")) + glob.glob(os.path.join(s, "__editable__*")):
        t = pathlib.Path(f).read_text(errors="ignore")
        if any(m in t for m in mutable):
            bad.append(f)
print("import-redirecting finders:", bad or "none (good)")
PY
sudo chown -R root:root "$DEPLOY_VENV" && sudo chmod -R go-w "$DEPLOY_VENV"   # re-lock after install
```

Confirm the Console venv was left untouched, and the sudoers grant includes the acceptance verb:

```bash
stat -c '%n %U:%G' /opt/tc_ai_growth/app/orchestrator/.venv/bin/python   # still tcgrowth-owned
sudo grep start-acceptance /etc/sudoers.d/tc-console-scan
```

### A3. Establish a root-owned `current` runtime

`start-acceptance` runs the acceptance harness *as root from root-owned code*, so a root-owned
runtime must exist first. Stage the current commit and bootstrap it (one-time, root-only, never in
sudoers):

```bash
SHA=$(git -C /opt/tc_ai_growth/app rev-parse HEAD)
sudo -u tcgrowth git -C /opt/tc_ai_growth/app worktree add --detach \
    /opt/tc_ai_growth/releases/$SHA $SHA
sudo /usr/local/lib/tc-deploy/tc-deploy-privileged.sh bootstrap $SHA
sudo cat /var/backups/tc-console/current    # should print $SHA
```

`bootstrap` now also installs the **acceptance-only** sudo capability — the fix for the defect the
first prep run exposed (the Console's `sudo -n start-acceptance` was ungranted until a full
production `apply`). It is a separate least-privilege drop-in granting `tcgrowth` exactly
`start-acceptance <numeric id>` on the fixed entry point — never `apply`/`rollback`/`start-run`.
Confirm it, and confirm your existing integrity-scan grant is untouched:

```bash
sudo cat /etc/sudoers.d/tc-console-scan-acceptance   # start-acceptance [0-9]* only
sudo cat /etc/sudoers.d/tc-console-scan              # your original inspector grant, unchanged
```

### A4. Enablement is already committed in this head — nothing to edit

The review of `76a9fd3` required enablement to be a **committed, reviewed diff**, not a manual live
edit. It is: `deploy_acceptance` ships **`enabled=True`** in the #81 head you installed at A1, so
there is no file to change and the runtime/receipt SHA is unambiguous. The enablement is
principled, not a blanket loosening:

- a `production_write` marker distinguishes the production deployer from the disposable acceptance;
  `validate_registry` refuses to let any `production_write` operation be enabled (#77), so
  **`deploy_release` stays `enabled=False` and server-refused** and this change cannot enable it;
- a `self_service=False` marker keeps `deploy_acceptance` off the generic `/operations` page and
  refuses a crafted `/api/execute` naming it — the operation is reachable only through its
  dedicated `/acceptance` surface, so there is no second, argument-less invocation path.

Both are pinned by tests (`test_action_registry.py`, `test_u4d2_console_acceptance.py`). Confirm on
the host after A1:

```bash
sudo -u tcgrowth /opt/tc_ai_growth/app/orchestrator/.venv/bin/python - <<'PY'
from tc_growth.core.actions import get_operation
print("acceptance enabled:", get_operation("deploy_acceptance").enabled)
print("release enabled:", get_operation("deploy_release").enabled)
PY
```

---

### A5. Provide the owner a ready browser endpoint

Establishing and troubleshooting the loopback SSH tunnel (or an equivalent maintainer-managed
reverse proxy / port-forward) is **maintainer administration, not an owner step**. Before handing
off, confirm the tunnel is up and give the owner a working URL and a valid session, so the owner
never opens a terminal. If the endpoint is not reachable, **stop here** — do not tell the owner to
run the acceptance against an unavailable Console; report it and fix the access first.

### Reversibility and pre/post state (record before A2)

Capture the pre-state so the install is provably reversible, and the post-state after A2–A4:

```bash
for f in /opt/tc_ai_growth/app /usr/local/lib/tc-deploy /usr/local/bin/wp-integrity-scan.sh \
         /etc/sudoers.d/tc-console-scan /var/backups/tc-console/current; do
  echo "== $f =="; sudo stat -c '%n %U:%G %a' "$f" 2>/dev/null || echo "absent"; done
sudo systemctl is-active tc-console
git -C /opt/tc_ai_growth/app rev-parse HEAD
```

To reverse: `rollback` restores the unit/inspector/sudoers from root-owned snapshots; the checkout
returns to its recorded HEAD; the prefix, inspector and drop-in can be removed. If any step in
Section A fails, stop and roll back — never improvise a fix on the live host, and do not proceed to
the acceptance (an unproven install must surface as `BLOCKED`, never as a partial success).

---

## Section B — owner (browser only)

1. Open the **Console URL the maintainer gave you** (the maintainer owns the tunnel/endpoint;
   you do not create or diagnose it) and sign in.
2. **Acceptance** tab → **Run deployment acceptance** → read the preview → **Yes — run the
   acceptance**. That click is the only input.
3. Watch the run page. The runner streams the engine phases and then its own self-checks —
   `check-attestation-resistance`, `check-receipt-binds-runtime-and-target`,
   `check-store-ownership-preserved`, `check-console-restart-reconnect` — each as a durable phase.
   The page reconnects on its own after the runner restarts the Console.
4. Read the single verdict at the top: **`PASS`** (every phase and check `ok`, zero deferred),
   `FAILED SAFELY`, or `BLOCKED`. The verdict is computed against the root-owned receipt, not the
   store column.

---

## What to bring back

- the recorded heads (#80 `386f332`, #81 `7ad6b0f`) and the acceptance run id;
- the owner-visible final verdict, and — if not `PASS` — the exact failed phase;
- the self-check phases' statuses (all `ok` for a `PASS`);
- the receipt fields as shown (`engine_head`, `target`, `verdict`);
- confirmation the production-untouched phase is green.

A `PASS` is what lets #80 (engine) merge, then #81 (surface). Merge and any later production
enablement (`deploy_release`) remain separate owner decisions.

## If it does not pass

- **Every launch shows `BLOCKED`, no phases run** → the machinery/runtime is not in place (A2/A3),
  or the operation is not enabled (A4). Re-check A.
- **`BLOCKED` with a deferred phase** → systemd was not booted for a phase, or a self-check
  deferred. The run page names which phase; bring that back.
- **`BLOCKED` with a failed self-check** → a trust/integration check failed; bring back the failed
  check's detail. Do not merge; report it on #81 and it will be fixed before re-running.
