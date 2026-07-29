# Operations Console — deployment & owner acceptance runbook

**Status this gates:** *Repository implementation and sandbox validation complete. Production
owner acceptance PENDING.* The Console is **not "live"** until the steps below pass on the real
VPS. This runbook exists so that first deployment is **one reviewed operation**, not a blind
terminal marathon — the very thing the Console exists to end.

Everything is driven by one script: `orchestrator/scripts/deploy-console.sh`. It is a **dry run
by default** and changes nothing until you pass `--apply`. Read it before you run it.

## Prerequisites (one-time, on the VPS)

1. **Bootstrap an isolated release checkout** (D1: never deploy from the checkout that
   `tc-weekly-report` / `tc-autodeploy` run from — preflight refuses it). As the service user,
   detached at the exact reviewed commit:
   ```bash
   cd /opt/tc_ai_growth/app
   sudo -u tcgrowth git fetch origin feature/operations-console
   sudo -u tcgrowth git worktree add --detach /opt/tc_ai_growth/console <reviewed-sha>
   install -m 600 -o tcgrowth -g tcgrowth /opt/tc_ai_growth/app/orchestrator/.env \
       /opt/tc_ai_growth/console/orchestrator/.env
   ```
2. A console token, stored 0600, never printed to a shell that logs history:
   ```bash
   umask 077; printf 'TC_CONSOLE_TOKEN=%s\n' "$(openssl rand -base64 32)" >> /etc/tc-console.env
   ```
3. The shared venv: release checkouts have no `.venv`, so `TC_VENV` must point at the main
   install's (editable-install + `WorkingDirectory` means the service still runs the release
   checkout's code — cwd wins on `sys.path`).

## Deploy (the one operation)

```bash
cd /opt/tc_ai_growth/console/orchestrator     # the release checkout — you deploy what you run from
export TC_VENV=/opt/tc_ai_growth/app/orchestrator/.venv
./scripts/deploy-console.sh                   # DRY RUN — prints every action, changes nothing
# review the plan: pinned commit, sudoers rule, unit, paths — then:
sudo TC_VENV=$TC_VENV TC_BUILD_COMMIT=$(git rev-parse --short HEAD) ./scripts/deploy-console.sh --apply
```

**Scan permission (D2), shown in the plan before you apply:** the deploy installs one
visudo-validated sudoers drop-in — `tcgrowth ALL=(root) NOPASSWD: /usr/local/bin/wp-integrity-scan.sh ""`
— exact root-owned script, zero arguments, nothing else. `sudo`'s `env_reset` also strips the
caller's environment, so the Console cannot redirect the scan target even in principle. The unit
consequently runs without `NoNewPrivileges` and with `ProtectSystem=full`; the rationale for each
relaxation is written in the unit itself.

**To deploy a newer reviewed commit:** advance the detached worktree, then re-run:
```bash
sudo -u tcgrowth git -C /opt/tc_ai_growth/console fetch origin feature/operations-console
sudo -u tcgrowth git -C /opt/tc_ai_growth/console checkout --detach <new-reviewed-sha>
```

### First redeploy (post-acceptance fix batch D4/F1/F2/F3)

This redeploy doubles as the deferred acceptance rows (idempotency; old session rejected;
optional rollback test). Before applying, add the explicit environment label to the console's
env copy (F2 — the badge derives from it):
```bash
echo 'TC_ENV_KIND=production' >> /opt/tc_ai_growth/console/orchestrator/.env
```
Then advance the worktree (above), dry-run, review the plan (expect the new commit; everything
else unchanged), apply once. Verify in the browser: red **PRODUCTION** badge; Execute →
Running… → **Run again** (button now resets — D4); your PRE-redeploy session was signed out.
Ledger rows to close: redeploy idempotency (run `--apply` a second time — no-op in effect),
and optionally `--rollback` followed by a final re-apply.

The script runs six phases, each of which you can verify:

| Phase | What it does | How you know it worked |
|---|---|---|
| 1 Preflight | Read-only checks: app dir, venv, service user, **token present (else fail closed)**, `list-operations` validates, port free | Prints `preflight OK` + the commit it will pin |
| 2 Snapshot | Copies the current systemd unit, deployed inspector, and evidence store to `/var/backups/tc-console/<ts>` | Prints the snapshot dir — rollback is now real |
| 3 Inspector | Installs the **repo** inspector atomically to `/usr/local/bin` (single source of truth), logs its sha256+commit | `logger` line `deployed … sha256=… commit=…` |
| 4 Service | Writes a loopback systemd unit pinning `TC_BUILD_COMMIT` + `TC_INSPECTOR_SCRIPT`, enables + starts it | `systemctl status tc-console` active |
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
| Idempotent / safe to run twice? | **Yes.** Each run snapshots first, then overwrites the unit + inspector; `enable --now` is idempotent. Re-running the same commit is a no-op in effect. |
| Versioned release directories? | **Not yet** — in-place install. Previous states are kept as timestamped **snapshots** under `/var/backups/tc-console`, which is what rollback uses. |
| Atomic activation (symlink swap)? | **Not yet** — service restart is the activation. Blue/green with atomic symlink swap is recorded as **debt** below. |
| Previous releases retained? | **Yes** — every run leaves a timestamped snapshot; none are deleted by the script. |
| Rollback restores code or config? | Restores the **inspector script + systemd unit** (config) and preserves the prior **evidence store**; it does **not** roll back the orchestrator app code (that lives in `APP_DIR`, deployed separately). |
| Health check fails after activation? | The script **aborts and points you at `--rollback`**. |
| Are active Console sessions invalidated on redeploy? | **Yes** — the session/CSRF signature is bound to the deploy commit (`TC_BUILD_COMMIT`), so a new deploy forces re-auth. |
| Does it modify `.env` / touch WordPress? | **No** to both — it reads the console env file, and deploys only the Console + read-only inspector. |

**Debt (record, don't build under deployment pressure):** move to **versioned release directories
with atomic symlink activation and retained N-previous releases**, so activation is atomic and
rollback is a symlink flip. The current snapshot-and-overwrite model is safe for a single-owner
loopback console but should be hardened before this surface grows. (Aligns with the repo audit's
"reproducible deployment + rollback semantics" note.)

## Owner acceptance — the narrow, intentional checklist

Do OP1/OP2 in the browser over the tunnel, **not** the terminal. This is the milestone. Keep it
narrow — validate exactly the package, OP1, OP2, rollback, and the access boundary.

**Deployment**
- [ ] Dry-run output reviewed; the printed action list == what `--apply` will run (no hidden steps).
- [ ] Source commit shown matches the expected branch tip.
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

When all four groups pass, with correct outcome semantics and traceable evidence, the Console MVP
has earned the right to continue. Until then it stays **acceptance pending**, not "live".

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
