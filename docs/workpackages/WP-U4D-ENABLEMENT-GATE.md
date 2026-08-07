# WP-U4d — the enablement gate

*U4d is merged and **disabled**. This document is the work between "merged" and "usable": the
seven post-merge criteria from issue #77 / PR #78, and the two host decisions that gate the rest.*

**Status:** criterion 3 is DECIDED. **Criterion 2 is NOT satisfied** — five review rounds, five
defects, work withdrawn to a successor PR rather than merged behind a description that claims
otherwise. Criteria 1, 4, 5, 6 follow it. Criterion 7 holds throughout — `deploy_release` stays
`enabled=False` and the Console keeps refusing the POST, not merely hiding the control.

---

## Criterion 2 — NOT SATISFIED. Withdrawn from PR #79, deferred to a successor PR.

**Status: open.** Five review rounds produced five defects, all mine, and the fifth showed the
boundary was still wrong. The work is withdrawn rather than merged behind a description that
claims otherwise.

### The five defects, in order

1. **Over-escalation** (merged in #78). The runner wrapped git, `python -m tc_growth.cli` and the
   deploy script in `sudo`. Every `sudo -u tcgrowth` was a **no-op** — `tc-console.service` sets
   `User=tcgrowth` and the runner is its detached child — but the sudoers rule they required is a
   general command path, which #77 forbids.
2. **The fix relocated the defect.** The wrapper still `exec`'d `deploy-console.sh` from the
   release worktree, which `tcgrowth` owns. `git rev-parse HEAD == <sha>` proves which commit was
   *checked out*, not that the files still match it — and `git status` cannot be the witness
   either, because the worktree's `.git` is writable by the same account. **Any check whose
   inputs the adversary owns is not a check.**
3. **The trust anchor was referenced but never written.** `/usr/local/lib/tc-deploy/deploy-console.sh`
   appeared in the code, the docs and the PR description as the thing making the boundary safe,
   and existed in none of them.
4. **The permission guard accepted what it claimed to reject.** `"root:root "[0-7][0-57][0-57]` —
   `[0-57]` is the set `{0,1,2,3,4,5,7}`, so `0777`, `0775`, `0757`, `0733` and `0702` all passed.
   *This is the one part that is now fixed and proven.*
5. **The boundary ended one process too early.** The installed helper is the existing
   `deploy-console.sh`, which reads `TC_APP_DIR` (line 47) — a variable the wrapper never set, so
   the apply path **dies in preflight** (line 138) and was non-functional. Worse, when it does
   run it executes `$VENV/bin/python -m tc_growth.cli` (line 154) and installs
   `$APP_DIR/scripts/wp-integrity-scan.sh` into `/usr/local/bin` (line 262) — root running Python
   from, and laundering a script out of, the service-user-writable tree.

### The honest cause

**I never executed this path.** Every claim across four rounds came from reading code I had
written and reasoning about it. That is how a path that dies in preflight passed my own review and
four PR descriptions calling it working. The recurring shape: *the explanation of a security
property shipped before the property existed, and the tests were written to check the
explanation.*

### What is left BROKEN on `main` by this reduction — stated, not buried

Withdrawing the privileged surface meant reverting `tc_growth/deploy.py` to its merged state, so
that nothing in PR #79 references a program the PR does not ship. The direct consequence:

> **Defect 1 (over-escalation) is UN-FIXED on `main`.** The merged runner still wraps git,
> `python -m tc_growth.cli` and the deploy script in `sudo -u tcgrowth` — no-ops that would
> nonetheless require a sudoers rule wide enough to run `python -m <anything>`.

**Why that is acceptable right now, precisely:** `deploy_release` is `enabled=False`, the Console
refuses the POST server-side, and the runner has never executed on any target — so no code path
reaches those calls, and no sudoers rule granting them has ever been installed. The defect is
latent in source, not live on the host.

**Why it is not fixed here:** the privilege reduction and the helper redesign touch the same
code. Landing half of it would leave `main` in a state whose safety argument depends on which
half — exactly the "explanation outruns implementation" failure this reduction exists to end.

**It returns with the successor PR**, as part of the single reviewed chain. Anyone reading this
document before then should assume the runner's privilege surface is the merged one, not the one
described in PR #79's withdrawn rounds.

### What survives, and where it lives

`orchestrator/scripts/lib/permission-guard.sh` — the numeric write-bit predicate, alone, with
tests that build real directories at each mode and run the actual shell function against them.
Nothing else. The helper, its installer and the sudoers surface are withdrawn.

### Successor: WP-U4d.1 — the privileged chain, reviewed as one unit

**Tracked in PR #80.** This section is the durable scope; the PR description carries the same
criteria.

**Status: increments 1–3 are implemented and executed off-host; the six systemd-bound phases have
never run.** The exit structure below says exactly what closes this work package and what does
not. Stated with that precision because the whole reason #79 was reduced is that descriptions
here ran ahead of code.

#### Increment 1 — the target seam and the disposable harness (implemented, executed)

The paths, store, service, unit prefix and evidence namespace are a `Target` value
(`tc_growth/deploy_target.py`) instead of module constants. Production is the default and the only
target that exists unless a command-line gate is open; `Target` refuses to construct at all
otherwise. Any process that binds or serves the Console latches that gate shut for its whole life,
so the Console cannot select a target — proven by driving a **real Console in its own process**
with target-injection attempts across form fields, query strings, headers and cookies, with a
control step showing the same process could open the gate *before* it served anything.

**Two claims of different strength, kept apart on purpose.** That `tc_growth.cli` is the only
caller of `open_cli_target_gate()` is a **convention**: it is an ordinary public function and
Python has no capability binding that would make it callable from one module only, so "CLI-only"
names the only caller that exists today. The **latch** is the enforced half — it holds against any
caller in any module, because it is a property of the process rather than of who is asking. None of
this defends against arbitrary code execution inside the Console process; the boundary being proven
is the *request* boundary.

`tc_growth/deploy_harness.py` builds a genuine throwaway target — its own git repository and
remote, store, backup directory, service and unit names, evidence namespace — and runs the
**production executors** against it as real subprocesses. A new `stage` step hashes every file in
the staged release worktree and compares it against a manifest read from the **committed
objects**, so a release edited after checkout is refused. That is PR #79 defect 2 answered: the
worktree's own `.git` is never the witness.

Executed, not described: `python -m tc_growth.cli deploy-harness <dir> --tamper` substitutes
content into the release worktree after checkout and the chain ends **refused** at `stage`, with
the privileged stand-in never started and the substituted payload never executed. A control run
with the content check — and only the content check — disabled shows that payload really does
execute, so the refusal is the check doing work rather than the harness's shape.

**Defect 1 is partly fixed.** The `sudo -u tcgrowth` no-ops are gone from `preflight`, `converge`
and `migrate` — the runner already runs as `tcgrowth`, so they bought nothing and cost a sudoers
rule wide enough to run `python -m <anything>`. `ex_release` still calls `sudo install` and
`sudo ./scripts/deploy-console.sh`; those are the real escalations and they belong to increment 2.

**What increment 1 does NOT establish**, listed so no later reader has to reconstruct it:

- The manifest comes from the app checkout's object store, which the same unprivileged account can
  write. It proves the release tree matches the commit; it does **not** give root a trust anchor.
  That needs a root-owned manifest.
- `health`, rollback and restart survival are not in the disposable chain, and nothing here claims
  them.
- The disposable run produces no secret-bearing output — no `.env`, no `systemctl show` — so
  criterion 10 (inspection by eye of real secret-bearing output) is untouched by it.
- Production's child processes still inherit their environment. Overrides are now bounded to the
  target's allowlist, which is a tightening, not the constructed environment criterion 5 asks of
  the privileged program.

#### Increment 2 — the privileged program (implemented; systemd phases deferred to the host)

`orchestrator/scripts/tc-deploy-privileged.sh` is the **one** escalation entry point, and
`install-tc-deploy.sh` is the installer that actually writes the trust anchor PR #79 defect 3 only
ever referenced. The installer copies the reviewed program, the merged permission guard and the
target's reviewed inspector into a root-owned prefix **outside every service-user-writable tree**,
bakes that target's constants into `target.conf`, records `manifest.sha256`, and then runs the
installed program's `self-check` — an installer that does not exercise what it installed is how a
path that dies on first use passes review four times.

The interface is verbs: `self-check`, `apply <sha>`, `rollback`, `start-run <id>`. The **only**
caller-supplied value in the whole surface is the SHA. No path, user, service, unit, port or
environment variable is ever accepted; root re-derives all of them from `target.conf` and verifies
owner, mode and digest of every file it trusts on **every** invocation.

**The laundering defect is inverted into a property.** Root installs the inspector from *its own
copy* and refuses when the release's copy disagrees with the root-owned manifest — so release
bytes can neither be installed nor executed, and the unprivileged `stage` verdict is not something
root inherits.

Executed as root, not inspected: the trust anchor written and self-verified; altered program,
guard, `target.conf` and inspector each refused; a manifest with an entry *dropped* refused;
prefix modes 0777/0775/0757/0733/0702 refused; a non-root caller refused by the program itself
rather than by filesystem permissions; thirteen non-verb argv shapes refused; eleven bad SHAs
refused; a forged environment naming `sshd`, `/etc/sudoers.d/pwn` and `/usr/bin/id` changing
nothing; rollback restoring from root-owned state and refusing a poisoned pointer; and the
**post-`stage` TOCTOU substitution** — `stage` passes, the release is substituted in the window,
and root refuses with nothing installed.

The bootstrap predicate the program needs before it can source the guard is duplicated on
purpose; a test runs **both** implementations over all 512 modes and requires identical verdicts,
turning the duplication into a proven equivalence rather than a second place to be wrong.

**Not proven anywhere off-host, and reported as `unavailable` rather than claimed:** daemon-reload,
service restart, restart survival, health, and the transient unit. The program exits 3 for that
case and the runner treats it as a **failed** step — a deployment that did not restart the service
did not deploy. Those phases are the owner-run VPS acceptance, against disposable paths, unit
names, port and evidence namespace.

**CI does not prove increment 2.** The boundary tests require root and *skip* on CI's unprivileged
runner. Their verbatim root-run output is attached to PR #80; a green badge means they were
skipped.

#### The design constraint that broke the first attempt

`orchestrator/scripts/deploy-console.sh` was written to run **from** a release checkout: it
derives `APP_DIR` from `TC_APP_DIR` or its own location (line 47), executes
`"$VENV/bin/python" -m tc_growth.cli` (line 154), and installs
`"$APP_DIR/scripts/wp-integrity-scan.sh"` into `/usr/local/bin` (line 262). **No wrapper makes
that safe to run as root** — wrapping only moves the boundary one process further along, which is
exactly what review round 5 found.

So the script must be **split**, not wrapped:

- **Unprivileged part**, runs as `tcgrowth`: preflight, ancestry, worktree staging, the test
  suite, `db-init`, and computing the *declarative inputs* the privileged part will need
  (release path, target SHA, the inspector's bytes and their digest).
- **Privileged part**, root-owned and installed outside the repository: performs only fixed host
  mutations — write the systemd unit, install the inspector from **verified bytes**, install the
  sudoers drop-in, restart the service, create the transient deployment unit. It reads
  declarative inputs; it executes nothing from `/opt/tc_ai_growth`.

The inspector install is the subtle one: copying a script out of a `tcgrowth`-writable tree into
a root-executed location launders the trust. Its bytes must be verified against a root-owned
manifest produced at install time from the reviewed source, not taken from the release.

#### Acceptance criteria (issue #77 Decision 2 + PR #79 rounds 1–6)

1. Defect 1 fixed: no `sudo -u tcgrowth` no-ops; the runner escalates once, through one entry point.
2. Root performs only narrow fixed host mutations.
3. No root process imports Python or executes scripts/modules from a `tcgrowth`-writable checkout.
4. Apply and rollback use only root-owned code and root-controlled state; rollback selects nothing
   through `WorkingDirectory` or any other caller-influenced value.
5. The privileged program re-derives every path/user/service from internal constants, re-validates
   the SHA, and starts children with a constructed minimal environment.
6. It verifies its own machinery at every invocation — owner, mode (via
   `scripts/lib/permission-guard.sh`, already merged and proven) and digest.
7. The transient per-deployment unit is created through that **same** single privileged entry
   point; `tc-console` `KillMode` stays unchanged.
8. An end-to-end **disposable run** proves apply, restart survival, durable Evidence completion
   and rollback. **No description in that PR may assert the boundary until this run has executed.**
9. Adversarial cases fail closed: forged environment, modified release content, unsafe
   permissions, altered helper bytes, path traversal, non-verb arguments.
10. Secret-bearing output from the disposable run is **inspected by eye** — unit tests proving
    anticipated shapes are explicitly insufficient.
11. `deploy_release` remains `enabled=False` and server-refused until 1–10 pass.

#### Method, adopted from six defects

Build the disposable target harness **first**, and let it be what proves each property, rather
than writing the property into a description and testing the description. The recurring failure was
never a missing check; it was a check whose inputs I controlled, or a claim about code I had never
executed.

### What the successor PR must do

Review the **complete privileged chain as one unit**: root performs only narrow fixed host
mutations; no root process imports Python or executes scripts from a `tcgrowth`-writable
checkout; apply and rollback use only root-owned code and root-controlled state; the transient
unit is created through the same single entry point; an end-to-end **disposable run** proves
apply, restart survival, evidence completion and rollback; forged environment, modified release
content, writable state and unsafe permissions all fail closed.

### The exit structure — two acceptances (DECIDED, owner + reviewer, PR #80 thread, 2026-08-05)

The review loop between builder and reviewer has no natural terminus — either side can always
find one more improvement. Safety-critical engineering exits on **agreed acceptance criteria**,
not on "review until nobody has another idea", so the exit is fixed here, in advance of the run,
where a post-run finding cannot quietly extend it.

The owner's product requirement is also recorded so it cannot be argued away again: **the owner
operates deployments from the Operations Console, not over SSH.** A one-command SSH workflow is a
reasonable engineering milestone and is *not* the requested product. U4d is "owner-operated
deployment", and the finish line does not move to wherever the engine happens to stop.

#### Acceptance A — the engine (closes PR #80)

**Correction (head-`386f332` review):** an earlier revision of this section instructed the owner
to run the acceptance by hand over SSH, and the PR thread described that as owner-endorsed. It
was not. The owner rejected SSH as the owner workflow from the start and authorized no manual
run; the reviewer's decision is that the acceptance executes **through the Console operation**
(WP-U4d.2 below), which launches the same bounded chain through the same privileged entry point.
The manual `deploy-vps-acceptance` CLI remains the engine's bounded entry — what the Console
invokes across the privileged boundary, and a development tool on disposable hosts — never the
owner workflow.

Frozen criteria — all of them, and only them (unchanged by the correction; only the launch
vehicle changed):

1. The acceptance run completes and its report lists **zero deferred phases**: `transient-unit`,
   `daemon-reload`, `restart-service`, `health-check`, `failure-injection` and
   `rollback-service-action` all **executed**.
2. The injected failure (committed content, not an editable file) fails the deployment, and
   rollback's per-artifact verdict is `complete`, with the service action taken from recorded
   prior state.
3. Evidence for the run is durable, redacted, and **read by eye** — including `systemctl show`
   output, the realistic leak source that cannot be produced off-host.
4. The report's production-untouched check is green: production paths, service, store, port and
   sudoers unchanged.
5. The run identifiers, the exact head SHA, and the full report are posted on PR #80.

On green, **PR #80 merges as the engine increment** — explicitly *not* as "U4d complete".
A finding made after Acceptance A passes goes to Acceptance B's criteria or to the
parked-residuals list below; the one exception, deliberately narrow, is a defect showing the
privileged boundary itself unsafe, which reopens A.

**Sequencing (decided at the head-`386f332` review):** WP-U4d.2 is built first, as a **stacked
successor PR** based on this branch, because its Console operation is the vehicle that executes
Acceptance A. One owner session on the VPS then proves both sets of criteria — A's about the
engine, B's about the owner surface — with the owner touching only the browser. The one-time
host setup (installing the root-owned machinery, updating the Console code to the successor
head) remains a separate, explicitly governed owner setup event; naming it is honesty about
bootstrapping, and it never becomes the recurring workflow.

#### Acceptance B — the owner experience (WP-U4d.2, stacked successor PR)

The Operations Console launches the **same** bounded disposable acceptance chain through the
**same** reviewed privileged entry point. The Console is another *caller* of the engine — never
a second implementation path, never a place where paths, units, ports, users or command
fragments originate. The reviewer's criteria (PR #80 thread, head `272e05b` and `386f332`
reviews) are the acceptance bar, headline items:

- a registered **Run deployment acceptance** operation with preview, CSRF/session protection and
  explicit owner approval; the browser selects only the closed operation, supplying no values;
- progress streamed in the Console, every phase written to durable Evidence;
- the operation survives the Console restart it causes and reconnects to durable run state;
- the final verdict distinguishes `PASS`, `FAILED SAFELY` and `BLOCKED`, and never reports
  success while a required phase is deferred;
- the complete owner acceptance runs with **no SSH, no terminal, no pasted instructions**.

#### Held throughout both acceptances

`deploy_release` stays `enabled=False` and server-refused. Enablement is a third, separate owner
decision after B — a green acceptance is evidence for that decision, not the decision itself.

#### Parked residuals (documented, not scheduled)

- Commit-signature verification against a root-held key — the object-store authenticity anchor.
  Root's comparison defeats post-`stage` substitution and replace refs; a consistent rewrite of
  objects *and* tree still passes.

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
backup, stop-on-failure, restart survival, durable reconnection, terminal Evidence.

*Partly done (increment 1, PR #80).* The target seam exists and the harness runs the real
executors for `preflight`, `backup`, `converge`, `suite`, `migrate` and `stage` against a genuine
disposable target; substituted release content is refused before any privileged mutation. Restart
survival, rollback and the health check are **not** covered — they need the privileged program.

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
