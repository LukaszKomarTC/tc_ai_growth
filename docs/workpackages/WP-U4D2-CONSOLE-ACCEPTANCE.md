# WP-U4d.2 — the Console-driven acceptance (Acceptance B)

*Stacked successor to PR #80, based on `feature/u4d-privileged-chain`. The engine is PR #80; this
work package is the owner surface: the Operations Console launching the bounded disposable
acceptance through the reviewed privileged boundary, with no SSH, no terminal, and no pasted
instructions.*

**The design constraint that rules everything here:** the Console is another **caller** of the
engine, never a second implementation path. No path, unit name, port, user, service or command
fragment may originate in the browser or in the Console process; the browser selects only the
closed, registered operation, and everything else is derived where it already lives — in the
engine and in root-owned configuration.

## Acceptance criteria (reviewer, PR #80 thread, head `272e05b` and `386f332` reviews, merged)

1. A registered **Run deployment acceptance** operation exists in the Operations Console, with
   preview, authenticated session, CSRF protection, and explicit owner approval.
2. The browser supplies **no** paths, service names, units, ports, users or command fragments; it
   selects only the closed registered operation.
3. The server launches the **same** bounded disposable acceptance chain through the **same**
   reviewed privileged entry point — no second implementation path.
4. Progress is streamed in the Console and every phase is written to durable Evidence, including
   restart survival, health, injected failure and rollback.
5. The operation survives a Console service restart and reconnects to the durable run state.
6. The final UI verdict distinguishes `PASS`, `FAILED SAFELY` and `BLOCKED`; it never reports
   success when a required phase is deferred or unavailable.
7. Stored output is redacted and inspected for secrets; production paths/service/store remain
   unchanged.
8. The complete owner acceptance can be performed without SSH, terminal commands or pasted
   instructions.
9. The disposable VPS acceptance, failure handling, rollback and production non-impact are proven
   **through the Console path** — this is how Acceptance A (PR #80's frozen engine criteria)
   executes.
10. `deploy_release` remains `enabled=False` and server-refused until a separate owner enablement
    decision, after both acceptances.

## The verdict model, fixed before implementation

- **`PASS`** — every required phase executed and succeeded; zero deferred; production untouched.
- **`FAILED SAFELY`** — a phase failed, and the safety properties held: the failure was refused
  or rolled back, rollback's per-artifact verdict is complete, production untouched.
- **`BLOCKED`** — the run could not execute its required phases (machinery not installed, systemd
  not booted, launch refused). Deferred is BLOCKED, never PASS: a phase that did not run is not a
  phase that succeeded.

## The privilege rule this surface must not break

The Console runs as the service user. The service user must **never** hold a sudoers grant that
runs root Python from a service-user-writable tree — that grant would be the whole compromise.
So the Console launches the acceptance only through the root-owned privileged program's fixed
verb surface, and the privileged program runs acceptance code only from root-owned copies it has
verified, exactly as `start-run` already does for the deploy runner. Extending the sudoers
surface is part of this work package's review, not a side effect.

## Increments

1. **The durable run and the owner surface** — acceptance runs and phases as store tables (the
   channel that makes streaming and restart-reconnection durable); the registered operation with
   preview, CSRF/session protection and explicit approval; the run page that streams phases and
   reconnects by id; the verdict function with `BLOCKED`-over-deferred pinned by tests; launch
   through the privileged seam, honestly `BLOCKED` where machinery is absent.
2. **The privileged verb** — `start-acceptance <id>` on the one privileged program, running the
   bounded acceptance from root-owned verified code as a transient unit; the sudoers surface
   extended by exactly that verb; boundary tests through the real root program.
3. **The on-host proof** — the owner's browser session on the VPS executing Acceptance A and B
   criteria in one run.

## Held throughout

`deploy_release` stays `enabled=False` and server-refused. PR #80 stays draft until Acceptance A
is green. Merge and enablement remain owner-authorized.
