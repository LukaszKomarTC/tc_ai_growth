# Operations Console — deployment & owner acceptance runbook

**Current status:** the Operations Console MVP and U1 are operationally accepted. This file is
the current deployment and redeployment runbook. Historical acceptance evidence remains
unchanged in `WP-CONSOLE-ACCEPTANCE-LEDGER.md`, `WP-CONSOLE-MERGE-PLAN.md`, and
`WP-CONSOLE-MERGE-RECORD.md`; those files are immutable records, while this runbook follows the
current release model.

Everything is driven by one script: `orchestrator/scripts/deploy-console.sh`. It is a **dry run
by default** and changes nothing until you pass `--apply`. Read it before you run it.

## Prerequisites (one-time, on the VPS)

1. **Bootstrap an isolated release checkout** (D1: never deploy from the checkout that
   `tc-weekly-report` / `tc-autodeploy` run from — preflight refuses it). Resolve the full
   reviewed SHA from `main`, verify that it belongs to `origin/main`, and create one detached
   worktree per release under `/opt/tc_ai_growth/releases/<sha>`:
   ```bash
   cd /opt/tc_ai_growth/app
   sudo -u tcgrowth git fetch origin main
   RELEASE_SHA=<full-reviewed-sha>
   sudo -u tcgrowth git merge-base --is-ancestor "$RELEASE_SHA" origin/main || { echo "SHA is not on origin/main"; exit 1; }
   sudo -u tcgrowth git worktree add --detach \
       "/opt/tc_ai_growth/releases/$RELEASE_SHA" "$RELEASE_SHA"
   install -m 600 -o tcgrowth -g tcgrowth /opt/tc_ai_growth/app/orchestrator/.env \
       "/opt/tc_ai_growth/releases/$RELEASE_SHA/orchestrator/.env"
   ```
2. A console token, stored 0600, never printed to a shell that logs history:
   ```bash
   umask 077; printf 'TC_CONSOLE_TOKEN=%s\n' "$(openssl rand -base64 32)" >> /etc/tc-console.env
   ```
3. Release worktrees have no private virtualenv or durable database. Pass both shared paths
   explicitly on dry run and apply:
   - `TC_VENV=/opt/tc_ai_growth/app/orchestrator/.venv`
   - `TC_STORE_DB=/opt/tc_ai_growth/app/orchestrator/data/tc_growth.db`

   `TC_VENV` supplies the reviewed runtime dependencies. `TC_STORE_DB` makes the unit pin
   `TC_DB_PATH` to the shared weekly-ledger database, so Console evidence survives release
   changes (U1-3).

## Deploy (the one operation)

Run the deployment script from the reviewed release worktree. The script defaults its identity
check to the reviewed branch `main` and derives `TC_BUILD_COMMIT` from the owner-run Git check.

```bash
RELEASE_SHA=<full-reviewed-sha>
cd "/opt/tc_ai_growth/releases/$RELEASE_SHA/orchestrator"
export TC_VENV=/opt/tc_ai_growth/app/orchestrator/.venv
export TC_STORE_DB=/opt/tc_ai_growth/app/orchestrator/data/tc_growth.db

TC_VENV="$TC_VENV" TC_STORE_DB="$TC_STORE_DB" ./scripts/deploy-console.sh
# Review the plan: main ancestry, pinned commit, shared venv, durable store, unit, and paths.
sudo TC_VENV="$TC_VENV" TC_STORE_DB="$TC_STORE_DB" ./scripts/deploy-console.sh --apply
```

**Scan permission (D2), shown in the plan before you apply:** the deploy installs one
visudo-validated sudoers drop-in — `tcgrowth ALL=(root) NOPASSWD: /usr/local/bin/wp-integrity-scan.sh ""`
— exact root-owned script, zero arguments, nothing else. `sudo`'s `env_reset` also strips the
caller's environment, so the Console cannot redirect the scan target even in principle. The unit
consequently runs without `NoNewPrivileges` and with `ProtectSystem=full`; the rationale for each
relaxation is written in the unit itself.

**To deploy a newer reviewed commit:** create a new detached worktree; do not advance the
currently deployed release directory in place.

```bash
cd /opt/tc_ai_growth/app
sudo -u tcgrowth git fetch origin main
NEW_SHA=<full-reviewed-sha>
sudo -u tcgrowth git merge-base --is-ancestor "$NEW_SHA" origin/main || { echo "SHA is not on origin/main"; exit 1; }
sudo -u tcgrowth git worktree add --detach \
    "/opt/tc_ai_growth/releases/$NEW_SHA" "$NEW_SHA"
install -m 600 -o tcgrowth -g tcgrowth /opt/tc_ai_growth/app/orchestrator/.env \
    "/opt/tc_ai_growth/releases/$NEW_SHA/orchestrator/.env"

cd "/opt/tc_ai_growth/releases/$NEW_SHA/orchestrator"
export TC_VENV=/opt/tc_ai_growth/app/orchestrator/.venv
export TC_STORE_DB=/opt/tc_ai_growth/app/orchestrator/data/tc_growth.db
TC_VENV="$TC_VENV" TC_STORE_DB="$TC_STORE_DB" ./scripts/deploy-console.sh
sudo TC_VENV="$TC_VENV" TC_STORE_DB="$TC_STORE_DB" ./scripts/deploy-console.sh --apply
```

**Worktree ownership rule (D5):** every manual Git command in the app checkout or a release
worktree runs as `tcgrowth` (`sudo -u tcgrowth git -C …`), never as root. Root Git can rewrite
worktree metadata and indexes with root ownership. If that happens, stop and identify the exact
checkout and its metadata before performing a targeted ownership repair:
```bash
sudo -u tcgrowth git -C /opt/tc_ai_growth/app worktree list --porcelain
```
The deploy script runs its identity checks as the checkout owner automatically.

### Historical acceptance fix batches

Do not replay the old first-redeploy commands from chat or reconstruct them here. The original
release paths, defect batches, results, and branch names are immutable history in
`WP-CONSOLE-ACCEPTANCE-LEDGER.md`. Every current redeploy follows the new-release procedure
above from a reviewed `main` SHA.

The script runs six phases, each of which you can verify:

| Phase | What it does | How you know it worked |
|---|---|---|
| 1 Preflight | Read-only checks: app dir, venv, service user, **token present (else fail closed)**, `list-operations` validates, port free | Prints `preflight OK` + the commit it will pin |
| 2 Snapshot | Copies the current systemd unit, deployed inspector, and sudoers state to `/var/backups/tc-console/<ts>`; the shared `TC_STORE_DB` remains in place | Prints the snapshot dir — rollback is now real |
| 3 Inspector | Installs the **repo** inspector atomically to `/usr/local/bin` (single source of truth), logs its sha256+commit | `logger` line `deployed … sha256=… commit=…` |
| 4 Service | Writes a loopback systemd unit pinning `TC_BUILD_COMMIT`, `TC_INSPECTOR_SCRIPT`, and `TC_DB_PATH`, then enables + restarts it | `systemctl status tc-console` active |
| 5 Health check | Curls the loopback login page; aborts (suggests rollback) if not HTTP 200 | Prints `health check OK` |
| 6 Access | Prints the SSH-tunnel command + the `http://localhost:<port>` URL | You open it in a browser |

Rollback at any time: `sudo ./scripts/deploy-console.sh --rollback` (restores the last snapshot).

The dry run prints a **deployment plan** (source commit, destination paths, files replaced, the
systemd unit, service user, bind address, backup location, rollback command, whether it restarts a
service, whether it touches `.env` or production WordPress) — so you review the exact delta at
business-impact level before `--apply`, not just "preflight passed".

## Redeploy & upgrade semantics

The second deployment is often riskier than the first. Where this package stands today, answered
plainly:

| Question | Answer |
|---|---|
| Idempotent / safe to run twice? | **Yes.** Each run snapshots first, overwrites the unit + inspector, then runs `systemctl enable` + `restart`. Re-running the same commit redeploys identical state. |
| Versioned release directories? | **Yes.** Each reviewed `main` SHA gets a detached worktree at `/opt/tc_ai_growth/releases/<sha>`; the script deploys the checkout it lives in. |
| Atomic activation (symlink swap)? | **Not yet** — systemd unit replacement plus service restart activates the selected release worktree. A symlink swap remains recorded debt below. |
| Previous releases retained? | **Yes** — release worktrees are retained under `/opt/tc_ai_growth/releases/`, and every deploy also leaves a timestamped snapshot; neither is pruned automatically. |
| Rollback restores code or config? | Restores the prior **systemd unit** (including its release `WorkingDirectory`), inspector, and sudoers state; it preserves the durable evidence store. The prior release worktree must still exist. |
| Health check fails after activation? | The script **aborts and points you at `--rollback`**. |
| Are active Console sessions invalidated on redeploy? | **Yes** — the session/CSRF signature is bound to the deploy commit (`TC_BUILD_COMMIT`), so a new deploy forces re-auth. |
| Does it modify `.env` / touch WordPress? | **No** to both — it reads the console env file, and deploys only the Console + read-only inspector. |

**Debt (record, don't build under deployment pressure):** add atomic release activation
(for example, a reviewed `current` symlink strategy) and a deliberate retention/pruning policy.
Versioned release worktrees already exist; the remaining debt is atomic selection and lifecycle
management, not creation of release directories.

## Owner acceptance — the narrow, intentional checklist

Do OP1/OP2 in the browser over the tunnel, **not** the terminal. This is the milestone. Keep it
narrow — validate exactly the package, OP1, OP2, rollback, and the access boundary.

**Deployment**
- [ ] Dry-run output reviewed; the printed action list == what `--apply` will run (no hidden steps).
- [ ] Source commit is the reviewed SHA on `origin/main`, and the checkout path is `/opt/tc_ai_growth/releases/<sha>`.
- [ ] Backup/snapshot created before any change.
- [ ] Service installed under the expected user (`tcgrowth`), not root.
- [ ] Bind address is loopback only (`127.0.0.1`), confirmed with `ss -ltn`.
- [ ] No WordPress and no `.env`/profile mutation occurred.
- [ ] Redeploy behaves idempotently (run `--apply` twice; second run is a no-op in effect).
- [ ] Rollback is **executable**, not merely documented (`--rollback` restores the prior state).

**OP1 — SMTP Test**
- [ ] Preview shows the correct profile and **production** environment before Execute.
- [ ] Execution streams connect → starttls → auth → send live.
- [ ] A real test email arrives; result reads **Completed — success** (green).
- [ ] `completed · success` evidence persists with provenance (commit/profile/env).
- [ ] **No SMTP password** appears in output, logs, or evidence (guarded by a test; confirm on the box).
- [ ] Repeated execution does not create malformed state.

**OP2 — Integrity Scan**
- [ ] Console and cron invoke the **same** pinned scanner (`TC_INSPECTOR_SCRIPT` = the deployed path).
- [ ] Clean box → `completed / clean` (green, exit 0).
- [ ] Harmless controlled fixture → `completed / findings / attention` (amber, exit 2) — **not** failed.
- [ ] An unexpected exit (e.g. wp-cli missing) → `error / failure`.
- [ ] Finding output renders HTML-escaped; server paths reduced to WP-relative (`…/wp-content/uploads/…`).
- [ ] Target cannot be overridden from the Console (op takes no args; guarded by a test).
- [ ] Fixture removed → final scan `completed / clean` again.
- [ ] Evidence shows the scanner `sha256` + commit, so you know exactly which scanner ran.

**Security / access boundary**
- [ ] Console is inaccessible without the tunnel (not reachable on a public interface).
- [ ] Missing or bad token fails closed (no session issued).
- [ ] Execute without a valid CSRF token → 403.
- [ ] A session minted before the redeploy is rejected afterward.
- [ ] The service cannot execute arbitrary commands (registry-only; no free-form field).
- [ ] `tcgrowth` does not receive broad sudo authority as part of this.

The Console MVP's original acceptance decision is preserved in
`WP-CONSOLE-ACCEPTANCE-LEDGER.md`. For every current redeploy, all applicable checks above must
pass before the new release is treated as current; failures follow the ledger protocol:
observe → record → fix in Git → deploy a new reviewed release.

## Keep it to five owner steps

The package exists so the owner task is only: **(1)** inspect the readable plan → **(2)** approve
`--apply` → **(3)** open the protected Console over the tunnel → **(4)** click OP1 and OP2 →
**(5)** review the evidence. If deployment instead needs prolonged interactive repair, that is a
**deployment-package failure** to record and fix — not "just one more terminal session."

## Do not expand scope during this

No OP3, no new operations, no new panels while deploying. The next milestone is **deployment
proof**, not more code. (OP3 Verify Backups remains paused per WP-CONSOLE-MVP.md.)

## Evidence provenance (now recorded on every run)

Each execution's evidence detail carries a `provenance` block — `repo_commit` (pinned at deploy
via `TC_BUILD_COMMIT`), `release`, `profile`, `environment`, and `binding` — so "the scan passed"
is always traceable to a reviewed revision on a known target. Script-backed ops additionally emit
their script's `sha256` as the first evidence line. Verify it in the Logs panel after the first
run.

**Provenance is layered so it can't leak filesystem layout to the browser:** the full detail
(absolute paths, hashes) lives in the **evidence store** and the server-side deploy log
(journald records `path + sha256 + commit` at install). The **UI** shows a *reduced* view — the
scanner is identified by **basename + sha256 + commit**, and any absolute paths in rendered
summaries/errors are redacted to a basename. So a shared screenshot of the Logs panel does not
expose where things live on the box, while the audit trail server-side stays complete.
