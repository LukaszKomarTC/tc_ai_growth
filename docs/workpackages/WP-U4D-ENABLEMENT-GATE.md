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
sudo -n /usr/local/bin/tc-deploy-release.sh apply <40-hex-sha>
```

`test_the_runner_escalates_exactly_once_and_only_through_the_wrapper` parses the module's AST and
fails if a second `sudo` argv list ever appears, or if this one gains an argument.

### The privileged program (`orchestrator/scripts/tc-deploy-release.sh`, installed root-owned 0755)

- **Two fixed verbs and nothing else**: `apply <40-hex-sha>` and `rollback`. An unknown verb, a
  missing SHA, an extra argument, or a SHA passed to `rollback` are all refused.
- Validates the SHA **itself**. Root-owned code does not trust its caller: anything that can reach
  `sudo` can pass any string, so this program — not the runner — decides what is meaningful.
- Refuses a SHA with **no existing release worktree**. It never creates one, so it cannot be
  talked into materialising an arbitrary tree.
- Checks that the worktree's `HEAD` equals the requested SHA — a cheap sanity check that the
  caller staged what it claims, **explicitly not** a content-integrity or clean-worktree
  guarantee (see the blocker below).
- **Ignores the caller's environment.** Every path, user and service name is an internal
  constant; the child starts via `env -i` with a constructed minimal environment, so exported
  `TC_*` values are noise rather than authority.
- `rollback` takes **no argument at all** — nothing to choose, so nothing to get wrong — restores
  from the root-owned snapshot directory, and never discovers a script through systemd state.

### The blocker found in review, and what actually fixes it

The first version of this wrapper still failed criterion 2, and the reviewer was right about why.

It `exec`'d `deploy-console.sh` **from the release worktree**. That worktree is created by, and
writable by, `tcgrowth`. I had reasoned that checking `git rev-parse HEAD == <sha>` made the
content trustworthy. It does not: **HEAD proves which commit was checked out, not that the files
still match it.** `tcgrowth` can edit the script after checkout and leave HEAD untouched.

Nor can git be made the witness. The obvious patch — also require `git status --porcelain` to be
empty — fails for the same reason one level down: the worktree's `.git` is writable by the same
account, so any verification computed from it can be forged by whoever we are trying to detect.
**Any check whose inputs the adversary owns is not a check.**

The rollback branch had the identical defect in a different costume: it read `WorkingDirectory`
from `systemctl show` and exec'd a script from that path — using systemd state to *select
executable code* that lives in a writable directory.

**The fix is structural, not another check.** The privileged machinery lives outside the
repository, root-owned:

```
/usr/local/lib/tc-deploy/deploy-console.sh    root:root 0755
```

The wrapper executes only that, on both branches, and verifies ownership and mode **at every
invocation** rather than trusting the install. The release worktree is *data* to the privileged
step — the deploy script reads it to publish the unit's `WorkingDirectory`, and the Console later
runs that code **unprivileged as `tcgrowth`**, which is the normal accepted arrangement. What must
never happen is root executing it.

**The consequence, stated rather than hidden:** a change to the deployment machinery itself is no
longer picked up by running a deployment. Updating `/usr/local/lib/tc-deploy/` is a deliberate host
action with its own review. That asymmetry is correct — *the thing that performs deployments must
not be silently replaceable by a deployment.*

### Round 2: the trust anchor was referenced but not written

The structural fix above pointed root at `/usr/local/lib/tc-deploy/deploy-console.sh` — and **no
such file existed in the repository**. I described a trust anchor without building one, which
moved the most security-sensitive code outside the review boundary. A root-owned file can still
be unsafe: it can execute release content, trust its environment, accept arbitrary paths, or keep
rollback state somewhere the service user can rewrite. None of that was reviewable, because none
of it was written.

**Now in-repo and auditable:**

- `orchestrator/scripts/tc-deploy-release.sh` — the single privileged program. Fixed verbs
  (`apply <40-hex-sha>` / `rollback`), every path and name an **internal constant**, the SHA
  re-validated here rather than accepted, and the child started via `env -i` with a constructed
  minimal environment. **Caller-supplied `TC_*` values are ignored entirely** — they are not
  authority, they are noise.
- `orchestrator/scripts/install-tc-deploy.sh` — the deterministic host install. Refuses unsafe
  parent directories (a root-owned file inside a writable directory can be replaced wholesale),
  installs `root:root 0755`, writes a root-owned `MANIFEST.sha256`, and **verifies what actually
  landed** rather than assuming the copy worked.
- The privileged program checks, at **every invocation**: `$ROOT_LIB`, the helper and the
  manifest are `root:root` and not group/other writable, and the helper still matches its
  recorded digest. A swapped helper is caught before it runs; the manifest is root-owned, so the
  service user can neither swap the helper nor rewrite the digest that would betray the swap.
- Rollback restores from `/var/backups/tc-console`, root-owned and ownership-checked, and takes
  no argument at all.

### The sudoers rule

```
tcgrowth ALL=(root) NOPASSWD: /usr/local/bin/tc-deploy-release.sh
```

**A known limitation, stated rather than hidden:** sudoers cannot express "the verb `apply` plus one argument matching
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

### DECIDED: Option B — transient per-deployment unit (reviewer, PR #79)

The reviewer's verdict: *"Recommend the transient per-deployment systemd unit. Reject
`KillMode=process`. … Fold creation of that transient unit into the same root-owned helper so
there remains one privileged entry point, not a second general capability."* `KillMode` for
`tc-console` stays unchanged.

### The original recommendation, kept for the record

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
