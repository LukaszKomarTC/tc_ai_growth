# WP-U4d.1 — the VPS acceptance run (owner-executed)

*Everything in PR #80 that a machine without a booted systemd can prove has been proven and is on
the PR. This document is the rest: the phases that need a real service manager, executed by the
owner on the host, against a **disposable** target.*

The previous version of this file was a long sequence of commands to paste, and review found five
blockers in it — two product defects (since fixed) and three defects in the commands themselves.
The commands are gone. What replaced them is **one bounded command**, so the owner runs a program
that refuses production rather than assembling store rows by hand and hoping every `--` value was
disposable.

```bash
cd /opt/tc_ai_growth/app/orchestrator
sudo python -m tc_growth.cli deploy-vps-acceptance /srv/tc-u4d-acceptance/run1
```

That is the whole run. `--keep` leaves the tree in place afterwards for inspection.

---

## Why the owner runs this and not the agent

Issue #77 Decision 2 rejected giving the deployment agent a remote identity. That decision is
being honoured: this build environment has no SSH client, no keys, no host credentials and no
booted systemd, so the systemd-dependent chain cannot be executed anywhere the agent can reach.
The gate is owner-executed **by design**, not by accident.

## What the command refuses before it creates anything

The refusals are ordered ahead of the first mutation, not merely documented. `run()` has a pure
resolution phase — resolve the target, check it, resolve (not create) the service account, check
the acceptance root — and only then does it mutate anything. A poisoned target is refused with
zero directories created and zero modes changed.

- Every production marker — `tc-console`, `/opt/tc_ai_growth/app`, `/opt/tc_ai_growth/releases`,
  the production store, port 8000, the production sudoers file — is refused by value, not by
  reading the operator's intent from a flag.
- The run directory must be empty and under `/srv/tc-u4d-acceptance`. An acceptance root the
  service account cannot traverse is **refused, naming the fix** — it is not silently loosened by
  chmodding somebody's ancestors.
- After materialisation, the target that was actually built is compared against the target that
  was approved. If they differ, the run stops.

`deploy_release` stays `enabled=False` and server-refused throughout. Nothing in this run touches
production paths, the production service, store, port or sudoers file.

## What it captures

Run it inside `script(1)` if you want a full transcript:

```bash
mkdir -p ~/u4d-evidence && cd ~/u4d-evidence
script -q -c 'sudo python -m tc_growth.cli deploy-vps-acceptance /srv/tc-u4d-acceptance/run1' \
  u4d-acceptance-$(date -u +%Y%m%dT%H%M%SZ).log
```

**Read the log before sending it** — it contains host paths, and `systemctl show` output can
contain environment lines.

The command prints a report that separates what **executed** from what was **deferred** for want
of a booted service manager, rather than a single pass/fail. On a host with systemd booted,
`deferred` should be empty. The six phases that are deferred without it:

| phase | what it proves |
|---|---|
| `transient-unit` | `start-run` launches the runner as a transient unit, from immutable code |
| `daemon-reload` | root reloads the manager after writing the unit |
| `restart-service` | the service comes back on the regenerated unit |
| `health-check` | the restarted service answers on the disposable port |
| `failure-injection` | a release whose failure lives in **committed content** still fails, so unit regeneration cannot quietly remove the injected fault |
| `rollback-service-action` | rollback takes the service action from recorded prior state — restart when the unit existed, stop when it did not |

The report also prints the ownership split, the plan's target and repository, the import origin
under the exact service command, the rollback's per-artifact verdict, and a final check that
production is untouched.

## What is still outside this acceptance

The browser-click / CSRF path is **not** covered here and must not be represented as tested. This
run drives the chain from the command line against a disposable target; it says nothing about the
Console's request surface.

Commit-signature verification against a root-held key is deferred. Root authenticates the runtime
against the commit and refuses replaced objects, but the object store's own authenticity is a
residual — see `docs/workpackages/WP-U4D-ENABLEMENT-GATE.md`.

## After the run

Send back the report and, if you used `script`, the transcript. This run is **Acceptance A** of
the two-acceptance exit structure in `docs/workpackages/WP-U4D-ENABLEMENT-GATE.md`: its criteria
are frozen there in advance, a green run merges PR #80 as the *engine* increment, and the
Console-driven owner experience (Acceptance B, WP-U4d.2) follows as a successor. Merge and
enablement remain owner decisions; a green acceptance run is evidence for those decisions, not
the decisions themselves.
