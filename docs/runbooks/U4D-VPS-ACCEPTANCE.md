# WP-U4d.1 — the VPS acceptance run

*Everything in PR #80 that a machine without a booted systemd can prove has been proven and is on
the PR. This document is the rest: the phases that need a real service manager, executed on the
host against a **disposable** target.*

**The owner does not run this by hand.** An earlier revision of this document instructed the
owner to run the acceptance over SSH; the head-`386f332` review corrected the record — the owner
rejected SSH as the owner workflow and authorized no manual run. The acceptance is launched from
the **Operations Console** (WP-U4d.2, the stacked successor to PR #80), which invokes the same
bounded chain through the same privileged entry point. This document describes **what that run
proves**, whoever launches it.

The bounded engine entry is:

```bash
sudo python -m tc_growth.cli deploy-vps-acceptance /srv/tc-u4d-acceptance/run1
```

— one program that refuses production rather than a paste-sequence that hopes every value was
disposable. Running it by hand is a development action on a disposable host, not the owner
workflow. `--keep` leaves the tree in place afterwards for inspection.

---

## Who runs what, and why

Issue #77 Decision 2 rejected giving the deployment agent a remote identity, so the agent cannot
reach any host with a booted systemd — the on-host gate is not the agent's, by design. And the
owner's requirement, recorded in `docs/workpackages/WP-U4D-ENABLEMENT-GATE.md`, is that the owner
operates from the Console, not over SSH. What remains for the owner on a terminal is the
**one-time governed setup event**: installing the root-owned machinery and updating the Console
code to the successor head. That event is named rather than hidden because pretending the
bootstrap does not exist is how trust anchors end up existing only in prose.

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

## What the run proves

The report separates what **executed** from what was **deferred** for want of a booted service
manager, rather than printing a single pass/fail. On a host with systemd booted, `deferred` must
be empty. The six phases that are deferred without it:

| phase | what it proves |
|---|---|
| `transient-unit` | `start-run` launches the runner as a transient unit, from immutable code |
| `daemon-reload` | root reloads the manager after writing the unit |
| `restart-service` | the service comes back on the regenerated unit |
| `health-check` | the restarted service answers on the disposable port |
| `failure-injection` | a release whose failure lives in **committed content** still fails, so unit regeneration cannot quietly remove the injected fault |
| `rollback-service-action` | rollback takes the service action from recorded prior state — restart when the unit existed, stop when it did not |

The report also carries the ownership split, the plan's target and repository, the import origin
under the exact service command, the rollback's per-artifact verdict, and a final check that
production is untouched.

## What is still outside the engine run itself

The Console's request surface — session, CSRF, approval, streaming, reconnection, the verdict —
is Acceptance B's criteria set, proven by driving the Console, not by this chain. Until WP-U4d.2
lands and runs, the browser path **must not be represented as tested**.

Commit-signature verification against a root-held key is deferred. Root authenticates the runtime
against the commit and refuses replaced objects, but the object store's own authenticity is a
residual — see `docs/workpackages/WP-U4D-ENABLEMENT-GATE.md`.

## After the run

The run's evidence is durable and the report is posted on PR #80 with the exact head and run
identifiers — Acceptance A's frozen criteria live in `docs/workpackages/WP-U4D-ENABLEMENT-GATE.md`.
A green run merges PR #80 as the *engine* increment; the Console surface (Acceptance B) is judged
on its own criteria. Merge and enablement remain owner decisions; a green acceptance run is
evidence for those decisions, not the decisions themselves.
