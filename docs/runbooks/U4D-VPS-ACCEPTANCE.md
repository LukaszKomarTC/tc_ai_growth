# WP-U4d.1 — the VPS acceptance run (owner-executed)

*Everything in PR #80 that a machine without a booted systemd can prove has been proven and is on
the PR. This document is the rest: the phases that need a real service manager, executed by the
owner on the host, against a **disposable** target.*

**Why the owner runs this and not the agent.** Issue #77 Decision 2 rejected giving the deployment
agent a remote identity. That decision is being honoured: this build environment has no SSH client,
no keys, no host credentials, and no booted systemd — so the systemd-dependent chain cannot be
executed anywhere the agent can reach. The gate is owner-executed **by design**, not by accident.

**Nothing here touches production.** Every path, unit name, port and evidence namespace below is
disposable. `tc-console`, `/opt/tc_ai_growth/app`, `/opt/tc_ai_growth/releases`, the production
store and the production sudoers file are never named by any command in this document. Check that
claim before you run anything: every `--` value below contains `u4dprobe`.

**`deploy_release` stays `enabled=False` and server-refused throughout.** See the open question in
§3 before starting — one of the review criteria conflicts with that, and it needs a decision.

---

## 0. What to capture

Run everything inside `script(1)` so the transcript is complete and nothing is reconstructed from
memory:

```bash
mkdir -p ~/u4d-evidence && cd ~/u4d-evidence
script -q -c bash u4d-acceptance-$(date -u +%Y%m%dT%H%M%SZ).log
```

Everything after this point happens inside that shell. When you are done, `exit`, and the `.log`
file is the evidence. **Read it before sending it** — it will contain host paths, and it may
contain environment lines from `systemctl show`.

---

## 1. Install and self-check the root-owned helper  *(criterion 1)*

Pick a scratch root that is not under `/opt/tc_ai_growth`:

```bash
export PROBE=/srv/u4dprobe
sudo mkdir -p "$PROBE"/{app,releases,backups,state,host,priv}
```

Seed the disposable application. It must be a real git repository with a real remote, because
`preflight` checks ancestry and root authenticates the runtime against the commit:

```bash
sudo git init --bare "$PROBE/origin.git"
sudo git clone /opt/tc_ai_growth/app "$PROBE/app"          # read-only use of the real checkout
sudo git -C "$PROBE/app" remote set-url origin "$PROBE/origin.git"
sudo git -C "$PROBE/app" push origin HEAD:main
export PROBE_SHA=$(sudo git -C "$PROBE/app" rev-parse HEAD)
echo "disposable target SHA: $PROBE_SHA"
```

Install the helper for the disposable target, provisioning a root-owned interpreter:

```bash
cd /opt/tc_ai_growth/app/orchestrator
sudo bash scripts/install-tc-deploy.sh \
  --prefix       "$PROBE/priv/lib" \
  --runtime-dir  "$PROBE/priv/runtime" \
  --app-dir      "$PROBE/app" \
  --releases-dir "$PROBE/releases" \
  --service      tc-console-u4dprobe \
  --service-user tcgrowth \
  --port         8399 \
  --unit-path    /etc/systemd/system/tc-console-u4dprobe.service \
  --inspector-dest "$PROBE/host/wp-integrity-scan.sh" \
  --sudoers-file /etc/sudoers.d/tc-console-u4dprobe \
  --snapshot-dir "$PROBE/host/snapshots" \
  --unit-prefix  tc-deploy-u4dprobe \
  --store-db     "$PROBE/state/store.db" \
  --venv         "$PROBE/venv" \
  --provision-venv
```

Then install the application's dependencies **as root, and not editable**:

```bash
sudo "$PROBE/venv/bin/pip" install --no-deps -r /opt/tc_ai_growth/app/orchestrator/requirements.txt
# If no pinned requirements file exists, install the third-party dependencies explicitly.
# `pip install -e` is REFUSED by the helper: it would point the root-owned venv back at a
# service-user-writable tree.
```

Capture the state the criterion asks for:

```bash
sudo "$PROBE/priv/lib/tc-deploy-privileged.sh" self-check
sudo ls -la "$PROBE/priv/lib"
sudo cat "$PROBE/priv/lib/manifest.sha256"
sudo stat -c '%n %U:%G %a' "$PROBE/priv/lib" "$PROBE/priv/lib"/*
```

**Expect:** `self-check` exits 0 with `phase=systemd status=available` (it exits 3 only where
systemd is not booted). Every file `root:root`, prefix `755`, manifest covering all four entries.

---

## 2. Bootstrap, and prove it changes only trusted runtime state  *(criterion 2)*

```bash
sudo git -C "$PROBE/app" worktree add --detach "$PROBE/releases/$PROBE_SHA" "$PROBE_SHA"

# Before
sudo ls -la /etc/systemd/system/tc-console-u4dprobe.service /etc/sudoers.d/tc-console-u4dprobe \
            "$PROBE/host/wp-integrity-scan.sh" 2>&1 | tee before-bootstrap.txt

sudo "$PROBE/priv/lib/tc-deploy-privileged.sh" bootstrap "$PROBE_SHA"

# After — these three must STILL be absent
sudo ls -la /etc/systemd/system/tc-console-u4dprobe.service /etc/sudoers.d/tc-console-u4dprobe \
            "$PROBE/host/wp-integrity-scan.sh" 2>&1 | tee after-bootstrap.txt
sudo ls -la "$PROBE/host/snapshots/"
sudo cat "$PROBE/host/snapshots/current"
```

**Expect:** bootstrap exits 0; `before` and `after` both show all three artifacts absent; only
`current` and the runtime tree appear. Bootstrap is not a deployment and must not behave like one.

---

## 3. Launch through the owner surface  *(criterion 3 — see the open question)*

> **Open question for the reviewer, which needs an answer before this step.**
>
> Criterion 3 asks that the deployment be launched "through the actual Console/transient-unit path,
> not a direct helper invocation". Criterion 9 requires `deploy_release` to remain `enabled=False`
> and **server-refused** throughout.
>
> Those conflict. `enabled` lives in the Action Registry in code, not in per-target configuration,
> so there is no way to offer the control in a disposable Console without changing the registry —
> which would either enable it for production too, or require a new per-target enablement
> mechanism, i.e. exactly the "further off-host design increment" this round ruled out.
>
> **Proposed resolution, for the reviewer to accept or replace:** drive the *transient-unit path*
> — which is the part criterion 4 actually tests — while leaving the registry untouched. The
> authorization row is created through the same store API the Console uses, and the run is started
> through `start-run`, which is what the Console invokes. What this does **not** exercise is the
> browser click and the CSRF/consent-digest path, and that limitation gets stated in the evidence
> rather than glossed.
>
> If you would rather have the real click, that needs a per-target enablement mechanism designed
> and reviewed first, and this run should wait for it.

Under the proposed resolution:

```bash
sudo TC_DB_PATH="$PROBE/state/store.db" "$PROBE/venv/bin/python" - <<'PY'
import json, os
from tc_growth import deploy
from tc_growth.store.sqlite import SqliteStore
sha = os.environ["PROBE_SHA"]
store = SqliteStore(os.environ["TC_DB_PATH"])
plan = deploy.build_plan(sha)          # production Target: see the note below
run_id = store.plan_deploy(sha=sha, plan=plan, plan_digest=deploy.plan_digest(plan),
                           requested_by="owner:u4d-vps-acceptance")
print("planned run id:", run_id)
store.close()
PY
```

> **Note.** `build_plan` with no target produces the *production* plan. For the disposable run the
> plan must name the disposable target, which requires the CLI target gate. Use
> `python -m tc_growth.cli deploy-harness` if you want the harness to construct it, or record in
> the evidence that the plan row was built for the production target and the execution context was
> disposable — do not let the two disagree silently.

Then launch through the transient unit:

```bash
sudo "$PROBE/priv/lib/tc-deploy-privileged.sh" start-run <run-id>
systemctl status "tc-deploy-u4dprobe-run-<run-id>" --no-pager
```

---

## 4. Prove the systemd chain end to end  *(criterion 4)*

```bash
systemctl list-units 'tc-deploy-u4dprobe-*' --all --no-pager
journalctl -u "tc-deploy-u4dprobe-run-<run-id>" --no-pager | tail -60
systemctl is-active tc-console-u4dprobe
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8399/
systemctl show tc-console-u4dprobe --no-pager -p Environment -p ExecStart -p WorkingDirectory
```

The four things to establish, each with its own command output:

1. **transient unit created** — `systemctl list-units` shows it, created by `start-run`.
2. **`daemon-reload` and restart happened** — `apply` reports `phase=restart-service status=ok`.
3. **restart survival** — the runner's own process outlived the Console restart it performed.
   Prove it by the run reaching a terminal status *after* the restart, with the pre-restart PID
   gone: `ps -o pid,etimes,cmd -p <runner-pid>` before and after.
4. **durable Evidence completion after the old process exited** —
   `sudo sqlite3 "$PROBE/state/store.db" "select id,status,finished_at,outcome from deploy_runs"`
   shows a terminal status written by the detached runner, not by the Console.

**The unit must name the runtime tree, never the release tree.** `WorkingDirectory` should be under
`$PROBE/priv/runtime/<sha>/orchestrator`. If it names `$PROBE/releases/...`, stop and report it.

---

## 5. Rollback through the same boundary  *(criterion 5)*

```bash
sudo "$PROBE/priv/lib/tc-deploy-privileged.sh" rollback
systemctl is-active tc-console-u4dprobe
sudo ls -la /etc/systemd/system/tc-console-u4dprobe.service /etc/sudoers.d/tc-console-u4dprobe \
            "$PROBE/host/wp-integrity-scan.sh" 2>&1
```

**Expect:** a per-artifact report (`rollback-unit`, `rollback-inspector`, `rollback-sudoers`,
`rollback-current`), each `restored` or `removed`, and a final `phase=rollback status=complete`
with `failed=0`. On a first deployment everything should be **removed**, because none of it existed
before. Partial must say partial and exit non-zero.

---

## 6. A post-start failure  *(criterion 6)*

Make the deployed Console fail its health check, then run the chain again:

```bash
sudo sed -i 's/^Environment=TC_CONSOLE_PORT=8399/Environment=TC_CONSOLE_PORT=8498/' \
     /etc/systemd/system/tc-console-u4dprobe.service
sudo systemctl daemon-reload
# re-run the deployment; health should fail at the configured port
```

**Expect:** `phase=health-check status=failed`, the run's terminal status `failed`, the terminal
message naming the health check, **no later step attempted**, and rollback still usable afterwards.

---

## 7. Read the evidence by eye  *(criterion 7)*

This is the step that cannot be delegated to a test, and the one criterion 10 of the work package
has been waiting for:

```bash
sudo sqlite3 -line "$PROBE/state/store.db" "select * from deploy_steps order by seq"
sudo sqlite3 -line "$PROBE/state/store.db" "select * from deploy_runs"
```

Read all of it. Look for:

- **credentials** — anything from `/etc/tc-console.env`, `.env`, `TC_CONSOLE_TOKEN`,
  SMTP/API keys, or an `Authorization:` header that survived redaction;
- **environment leakage** — `systemctl show -p Environment` output is the realistic source, and it
  is stored in the `health` step's detail;
- **claims about phases that did not run** — any `status=ok` for something the transcript shows was
  skipped, or a terminal message naming a step that is not in the step list.

If anything looks wrong, that is the finding — send it rather than filtering it.

---

## 8. Tear down

```bash
sudo systemctl disable --now tc-console-u4dprobe 2>/dev/null
sudo rm -f /etc/systemd/system/tc-console-u4dprobe.service /etc/sudoers.d/tc-console-u4dprobe
sudo systemctl daemon-reload
sudo git -C "$PROBE/app" worktree prune
sudo rm -rf "$PROBE"
systemctl status tc-console --no-pager | head -5     # production, untouched, still running
```

---

## 9. What to send back

The `script(1)` log, plus:

- the exact head deployed and the disposable SHA;
- the transient unit name and the deploy run id;
- the terminal status of each run, and the rollback report;
- anything from §7 that looked wrong;
- confirmation that `systemctl status tc-console` shows production untouched.

`deploy_release` stays `enabled=False` and server-refused until this evidence is reviewed and merge
and enablement are separately authorized.
