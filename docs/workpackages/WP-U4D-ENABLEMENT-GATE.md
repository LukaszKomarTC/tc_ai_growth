# WP-U4d — the enablement gate

*U4d is merged and **disabled**. This document is the work between "merged" and "usable": the
seven post-merge criteria from issue #77 / PR #78, and the two host decisions that gate the rest.*

**Status:** criteria 2 and 3 answered here for review. Criteria 1, 4, 5, 6 are execution work that
follows the decision on 3. Criterion 7 holds throughout — `deploy_release` stays `enabled=False`
and the Console keeps refusing the POST, not merely hiding the control.

---

## Criterion 2 — the fixed host privilege surface

### What I got wrong in the merged code

The merged runner escalated far more than it needed to. It wrapped git, `install` and the deploy
script in `sudo`:

```
sudo -u tcgrowth git -C /opt/tc_ai_growth/app fetch origin main
sudo -u tcgrowth git ... merge --ff-only <sha>
sudo -u tcgrowth <venv>/bin/python -m tc_growth.cli db-init
sudo install -m 600 -o tcgrowth -g tcgrowth .../.env .../release/.env
sudo TC_VENV=... TC_STORE_DB=... ./scripts/deploy-console.sh --apply
```

**Every `sudo -u tcgrowth` there is a no-op.** `tc-console.service` sets `User=tcgrowth`, and the
runner is a detached child of the Console, so it already *is* `tcgrowth`. The calls changed
nothing about who ran the command — but they would have required a sudoers rule permitting
`tcgrowth` to run `git` and `python` as `tcgrowth`. Written the obvious way, that rule is close to
arbitrary command execution: `python -m <anything>` is a general command path, which is precisely
what #77 forbids.

The last line is worse. `sudo ... ./scripts/deploy-console.sh --apply` executes a script **from
the release worktree** — a directory the unprivileged runner creates and can write. Root
executing a file that the unprivileged caller controls is the standard shape of a privilege
escalation, and no sudoers rule can fix it, because the rule would have to name a path under
`/opt/tc_ai_growth/releases/<sha>/`.

I did not notice this while writing it. The review criterion "the host privilege surface exposes
no general command path" is what made me look.

### What it is now

Everything the runner does happens **unprivileged, as the service user it already is**: fetching,
the ancestry check, the fast-forward, the test suite, `db-init`, the worktree creation, and
copying `.env` into the release (both files belong to `tcgrowth`; the copy needs no privilege).

Exactly **one** action escalates:

```
sudo -n /usr/local/bin/tc-deploy-release.sh <40-hex-sha>
```

`test_the_runner_escalates_exactly_once_and_only_through_the_wrapper` parses the module's AST and
fails if a second `sudo` argv list ever appears, or if this one gains an argument.

### The wrapper (`orchestrator/scripts/tc-deploy-release.sh`, installed root-owned 0755)

- Takes **exactly one argument**, refusing zero or two.
- Validates it as 40 lowercase hex **itself**. Root-owned code does not trust its caller: anything
  that can reach `sudo` can pass any string, so the wrapper — not the runner — is what decides
  that only a SHA is meaningful.
- Refuses a SHA with **no existing release worktree**. It never creates one, so it cannot be
  talked into materialising an arbitrary tree.
- Re-checks that the worktree's `HEAD` **equals the requested SHA**, so it does not depend on the
  caller having done the ancestry check.
- Takes no path, service, branch or flag; never sources, evals or interpolates the argument.
- `--rollback` is a separate entry point taking **no SHA at all** — nothing to choose, so nothing
  to get wrong — and refuses unless the running service points at a release worktree.

### The sudoers rule

```
tcgrowth ALL=(root) NOPASSWD: /usr/local/bin/tc-deploy-release.sh
```

**A known limitation, stated rather than hidden:** sudoers cannot express "one argument matching
`^[0-9a-f]{40}$`". Written bare as above, sudo permits the script with *no* arguments; written
with a glob it permits one *arbitrary* argument. Either way the argument check is the wrapper's
job, which is why the wrapper validates before it uses. This is the same shape as the existing
integrity-scan rule (`… /usr/local/bin/wp-integrity-scan.sh ""` — one fixed root-owned script,
argument surface controlled by the script), so it does not introduce a new *kind* of trust, only a
second instance of an accepted one.

### What this surface cannot do

No interactive shell. No arbitrary command. No path, service or repository outside the compiled-in
allowlists. No `.env` reading (the runner copies the file; it never parses or logs it). No
firewall, SSH, cron or backup-policy reach. No WordPress path of any kind — the runner never
imports the connector.

---

## Criterion 3 — restart survival without broadening unrelated authority

The deployment restarts `tc-console`, and the runner must outlive that restart to record its own
outcome. Two mechanisms; the choice is the decision this criterion asks for.

### Option A — `KillMode=process` on `tc-console.service`

systemd's default (`control-group`) kills every process in the unit's cgroup on stop/restart, so
the detached runner dies with the Console. `KillMode=process` signals only the main process,
leaving children alive.

- **For:** one line; no new privilege of any kind; the runner is already `setsid`-detached.
- **Against:** it is a **standing, unscoped** change. Every future child of the Console survives a
  restart, forever — including ones nobody has written yet. The integrity scan already spawns a
  long-running subprocess; under `KillMode=process` a redeploy would silently orphan a running
  scan instead of stopping it. That is a behaviour change to an unrelated feature, bought to
  serve this one.

### Option B — a transient unit per deployment

The Console asks systemd to run the deployment as its own short-lived unit:

```
systemd-run --unit=tc-deploy-<sha> --uid=tcgrowth --collect \
    <venv>/bin/python -m tc_growth.cli deploy-run <run-id>
```

The deployment is then not a child of the Console at all. Restarting `tc-console` cannot touch it,
and nothing else about the Console's process behaviour changes.

- **For:** survival is **scoped to the deployment**. `KillMode` stays default, so a redeploy still
  cleanly stops a running scan. The unit is independently inspectable (`systemctl status
  tc-deploy-<sha>`) and its lifecycle is visible to the host, not only to our store.
- **Against:** it needs a second privileged entry — `systemd-run` as root, or a polkit rule — and
  the unit name embeds the SHA, so the same "validate before use" discipline applies again. It is
  more moving parts.

### Recommendation: **Option B**, with the escalation folded into the existing wrapper

The cost of A is not that it is insecure today; it is that it is **unscoped and permanent**. It
buys restart survival for the deployment by granting it to everything the Console will ever spawn,
and the person who later adds a subprocess will not know they inherited it. That is the kind of
change that is cheap to make and expensive to remember.

B's extra privilege can be made narrow by the same trick already used for the release step: rather
than granting `systemd-run` generally, extend `tc-deploy-release.sh` with a second fixed entry
point that launches the run, so the sudoers surface stays **one script** rather than two commands.
That keeps the property "exactly one escalation path" from criterion 2 intact.

**This is a recommendation, not a decision.** If the reviewer or owner prefers A for its
simplicity, the code works unchanged under either — `spawn_detached()` is one function and the
mechanism is not baked into the runner. What I want recorded is that A's cost is a standing
behaviour change to unrelated features, not merely a stylistic preference.

---

## Criteria 1, 4, 5, 6 — the execution work, once 3 is decided

**1. Production v6→v7 migration.** Same two-phase shape as U4c: app-checkout convergence runs the
migration, then the Console release. Pre-deploy evidence already exists
(`test_v6_store_migrates_to_v7_leaving_every_existing_record_intact`, against a *populated* store).
Live proof is the pre-migration `.backup` compared with the migrated database — and now that
`content_digest()` exists, that comparison can be a digest match rather than the count check I
used for U4c.

**4. The disposable proof.** A throwaway target — its own directory tree, its own store, its own
service unit — exercised end-to-end with the **real** executors: exact-SHA refusal, verified
backup, stop-on-failure, restart survival, durable reconnection, terminal Evidence. This needs a
target seam (the paths are module constants today). That seam is security-relevant and will be
designed so the override is unreachable from any HTTP request — a test will pin exactly that.

**5. Rollback exercised** against the disposable target, through the wrapper's `--rollback` entry.

**6. Secret inspection by eye.** The redaction tests prove four *anticipated* shapes do not
survive. They do not prove a real deployment's output is clean; `deploy-console.sh` output and
`systemctl show` are the realistic sources. The disposable run's stored Evidence gets read in full,
and "the tests pass" is not accepted as a substitute.

---

## Criterion 7 — the operation stays refused throughout

`deploy_release` remains `enabled=False`. The Console renders the Deploy page and its history, the
authorize control is absent, **and the server refuses the POST** — a control hidden from the HTML
is not a control that cannot be invoked. Pinned by
`test_authorizing_is_refused_at_the_server_while_disabled` and
`test_the_deploy_operation_is_registered_but_not_yet_offered`.

**The runner has still never executed a real deployment on any target.** Nothing in this document
changes that, and the first execution must be the disposable proof, never production.
