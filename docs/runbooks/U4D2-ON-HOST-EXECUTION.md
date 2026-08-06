# WP-U4d.2 — on-host acceptance: exact execution guide

*The concrete command sequence behind `U4D2-CONSOLE-ACCEPTANCE.md`. Section A (the technical
maintainer, terminal, once) installs and enables the machinery; Section B (the owner, browser
only) runs the acceptance. Every path/value below is the real production constant from
`tc_growth/deploy_target.py` — **confirm each against your actual host before running**, and note
that Section A touches production paths (`/usr/local/lib/tc-deploy`, `/usr/local/bin`,
`/etc/sudoers.d/tc-console-scan`). It is reversible (the `rollback` verb, and the drop-in/inspector
can be removed), but it is a real change to production infrastructure — run it as a controlled
deployment.*

Record before starting: **#80 engine head `386f332`**, **#81 surface head `0bd5b63`**.

---

## Section A — technical maintainer (terminal, once)

### A1. Put the #81 branch on the host

The console must run the #81 code (which contains #80). As a controlled deployment, update the
production checkout to the surface head and restart:

```bash
sudo -u tcgrowth git -C /opt/tc_ai_growth/app fetch origin feature/u4d2-console-acceptance
sudo -u tcgrowth git -C /opt/tc_ai_growth/app checkout 0bd5b63
sudo -u tcgrowth /opt/tc_ai_growth/app/orchestrator/.venv/bin/pip \
    install --no-deps -r /opt/tc_ai_growth/app/orchestrator/requirements.txt
sudo systemctl restart tc-console
```

### A2. Install the root-owned privileged machinery (production values)

`--source` defaults to `scripts/`, which carries `tc-deploy-privileged.sh`,
`lib/permission-guard.sh` and `wp-integrity-scan.sh`. The installer runs the installed program's
`self-check` and fails if it does not verify.

```bash
cd /opt/tc_ai_growth/app/orchestrator
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
  --venv             /opt/tc_ai_growth/app/orchestrator/.venv \
  --console-env-file /etc/tc-console.env
```

Confirm the sudoers grant includes the acceptance verb:

```bash
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

### A4. Enable the acceptance operation (reviewed code change + deploy)

`deploy_acceptance` ships `enabled=False`; the registry is code, so enabling it is a reviewed edit
to `tc_growth/core/actions.py` (`enabled=True` on the `deploy_acceptance` Operation) that is
deployed like any other change, then `sudo systemctl restart tc-console`. **`deploy_release` stays
`enabled=False`** — this enables the acceptance only, not production deployment.

> If you prefer not to edit committed code, this is the point to decide the enablement mechanism
> with the reviewer. The acceptance cannot be launched from the browser until the operation is
> enabled at both layers.

---

## Section B — owner (browser only)

1. Open the Console over the SSH tunnel and sign in.
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

- the recorded heads (#80 `386f332`, #81 `0bd5b63`) and the acceptance run id;
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
