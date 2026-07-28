# Operations Console — deployment & owner acceptance runbook

**Status this gates:** *Repository implementation and sandbox validation complete. Production
owner acceptance PENDING.* The Console is **not "live"** until the steps below pass on the real
VPS. This runbook exists so that first deployment is **one reviewed operation**, not a blind
terminal marathon — the very thing the Console exists to end.

Everything is driven by one script: `orchestrator/scripts/deploy-console.sh`. It is a **dry run
by default** and changes nothing until you pass `--apply`. Read it before you run it.

## Prerequisites (one-time, on the VPS)

1. A console token, stored 0600, never printed to a shell that logs history:
   ```bash
   umask 077; printf 'TC_CONSOLE_TOKEN=%s\n' "$(openssl rand -base64 32)" >> /etc/tc-console.env
   ```
2. Confirm the config block at the top of `deploy-console.sh` matches your box (`TC_APP_DIR`,
   `TC_VENV`, `TC_SERVICE_USER`, `TC_CONSOLE_PORT`). Override via env if not.

## Deploy (the one operation)

```bash
cd <repo>/orchestrator
./scripts/deploy-console.sh                 # DRY RUN — prints every action, changes nothing
# review the printed systemd unit, paths, and pinned commit, then:
sudo TC_BUILD_COMMIT=$(git rev-parse --short HEAD) ./scripts/deploy-console.sh --apply
```

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

## Owner acceptance — OP1 + OP2 through the actual Console

Do this in the browser over the tunnel, **not** the terminal. This is the milestone.

**OP1 — SMTP Test**
- [ ] Preview shows target/profile/expected actions before Execute.
- [ ] Execute streams connect → starttls → auth → send live.
- [ ] Result reads **Completed — success** (green); a real test mail arrives.
- [ ] Logs panel shows the run as `completed · success` with evidence + provenance (commit/profile/env).

**OP2 — Integrity Scan** (the semantics that were corrected)
- [ ] Runs against the real production docroot under the real `tcgrowth` permissions.
- [ ] A clean box → **Completed — clean** (green), exit 0.
- [ ] Add a harmless controlled fixture (e.g. a throwaway extra admin, or a benign marker file the
      scanner keys on) → **Completed — findings** (amber), exit 2 — **NOT** "failed". Then remove
      the fixture → **Completed — clean** again.
- [ ] The evidence record shows the scanner's `sha256` + commit (first output line) and the
      structured `provenance` block — you can tell exactly which scanner ran.
- [ ] Findings persisted to the log even if alert delivery fails.
- [ ] Filenames / scanner output render HTML-escaped in the browser (no injection from a log line).
- [ ] The scheduled cron and the Console invoke the **same** `/usr/local/bin/wp-integrity-scan.sh`
      (the unit pins `TC_INSPECTOR_SCRIPT` to that path; cron uses it too).

When both operations pass here, with correct outcome semantics and traceable evidence, the Console
MVP has earned the right to continue. Until then it stays "acceptance pending."

## Do not expand scope during this

No OP3, no new operations, no new panels while deploying. The next milestone is **deployment
proof**, not more code. (OP3 Verify Backups remains paused per WP-CONSOLE-MVP.md.)

## Evidence provenance (now recorded on every run)

Each execution's evidence detail carries a `provenance` block — `repo_commit` (pinned at deploy
via `TC_BUILD_COMMIT`), `release`, `profile`, `environment`, and `binding` — so "the scan passed"
is always traceable to a reviewed revision on a known target. Script-backed ops additionally emit
their script's `sha256` as the first evidence line. Verify it in the Logs panel after the first
run.
