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

## The trust boundary on the verdict (review of head `f40a20a`)

The durable phase rows live in the ordinary store, which the service account can write. The rows
alone cannot establish **who** produced the evidence, so a positive verdict must be attested by
**root** and be unforgeable by the application layer. The attestation is a **root-owned receipt
file** whose authenticity rests on filesystem ownership — the same anchor the whole chain uses,
not a shared secret (a secret `tcgrowth` could read to verify, it could also use to forge). Root
seals `<RECEIPTS_DIR>/<id>.receipt` (root-owned, not group/other-writable, outside any disposable
tree); the Console shows `PASS`/`FAILED SAFELY` only when a root-owned receipt for the run exists,
its phase digest equals a digest recomputed over the durable rows, and its verdict agrees with
what those rows imply. Anything else is `BLOCKED`. `tcgrowth` cannot create a root-owned file, so
it cannot manufacture a trusted positive verdict however freely it writes the store.

## Increments

1. **The durable run and the owner surface (done, PR #81 `f40a20a`).** Acceptance runs and phases
   as store tables; the registered operation with preview, CSRF/session protection and explicit
   two-step approval; the run page that streams phases and reconnects by id; the verdict function
   with `BLOCKED`-over-deferred pinned; launch through the privileged seam, honestly `BLOCKED`
   where machinery is absent.
2. **The privileged verb and the trust boundary (done, this increment).** `start-acceptance <id>`
   on the one privileged program, running the acceptance **as root from the root-owned runtime**
   (the harness is `tc_growth` code, so root must run it from code the service user cannot edit) —
   the sudoers surface extended by exactly that verb, `systemd-run` still never granted. The
   root-owned verdict receipt and the Console's attested-verdict display, with executed forgery,
   digest-substitution, cross-run, non-root-ownership and unattested-positive cases. The
   unprivileged launcher can only ever record a launch refusal and `BLOCKED`; it never finalises
   a positive verdict.
3. **The acceptance verifies itself; the owner never does terminal verification (done, this
   increment — review of `90ae12f`).** The runner performs its own adversarial and integration
   checks and records each as durable evidence, so the owner approves once in the browser and
   reads one verdict:
   - `check-attestation-resistance` — the forgery battery (forged rows + PASS column, wrong run
     id, digest mismatch, non-root receipt) runs against a **disposable** record on the host at
     run time, proving each yields `BLOCKED` without anyone editing the live store;
   - `check-receipt-binds-runtime-and-target` — root confirms the receipt binds the
     independently-resolved runtime SHA and a disposable, non-production target;
   - `check-store-ownership-preserved` — no root-owned db/WAL/journal is left behind, and (given a
     service account) it can reopen and write the store;
   - `check-console-restart-reconnect` — the runner restarts the Console and confirms the durable
     record survived.

   A positive verdict requires every engine phase AND every self-check `ok`; a failed check is a
   trust/integration failure and is `BLOCKED`, never `FAILED SAFELY`. The systemd-bound restart
   check defers off-host, so off-host every run is honestly `BLOCKED`.

4. **The on-host proof (outstanding).** The owner's browser session on the VPS: the full engine
   acceptance driven end-to-end through `start-acceptance` from a real root-owned runtime, with a
   booted service manager so the six systemd phases and the restart-reconnect check execute and
   the sealed receipt reads `PASS`. Off-host, `start-acceptance` refuses for want of a `current`
   runtime and every launch is `BLOCKED`. See `docs/runbooks/U4D2-CONSOLE-ACCEPTANCE.md`.

## Enablement (owner-authorized, committed — review of head `76a9fd3`)

`deploy_acceptance` is `enabled=True` as a committed, reviewed diff rather than a manual host edit,
so the installed head is an exact CI-green SHA. It is principled, not a blanket loosening:

- **`production_write`** distinguishes the production deployer (`deploy_release`) from the
  disposable acceptance. `validate_registry` refuses to enable any `production_write` operation
  (#77), so `deploy_release` stays `enabled=False` and server-refused and cannot be enabled by this
  change. A test pins the distinction.
- **`self_service=False`** keeps `deploy_acceptance` off the generic `/operations` page and refuses
  a crafted `/api/execute` naming it, so the only way to invoke it is its dedicated `/acceptance`
  surface — no second, argument-less path. The two foundational registry invariants are refined
  accordingly (production-writing ops stay disabled; a disposable-only, dedicated-surface op may be
  enabled), each re-pinned by tests.

## The acceptance sudo grant (defect found during on-host prep; reviewer-approved fix)

On-host prep exposed that the Console's `sudo -n start-acceptance` was ungranted on any host that
had not run a full production `apply` — `write_sudoers` is only called by `apply`. Requiring a
production deploy to launch a *disposable* proof is circular, and granting the whole deploy sudo
surface would be worse. Fixed (reviewer-authorised, least privilege): **`bootstrap` installs a
separate acceptance-only drop-in** granting `tcgrowth` exactly `start-acceptance <numeric id>` on
the fixed root-owned entry — never `apply`/`rollback`/`start-run`/`systemd-run`/a shell/Python.
Generated from internal constants, `visudo`-validated, `0440` root:root, separate from the
integrity-scan grant (left untouched) and from the future deploy grant.

Proven with a **real sudo hop** (unprivileged user → `sudo -n` → root entry), the gap the
direct-as-root tests missed: sudo permits only the `start-acceptance` verb on the exact entry and
denies `apply`/`rollback`/`start-run`, a missing id, a non-digit id and an alternate path. sudo's
trailing wildcard permits extra trailing args and digit-then-junk ids — the **program** refuses
those (strict argc + numeric check), pinned separately. bootstrap's documentation is updated from
"no sudoers" to this exact least-privilege behaviour.

## Held throughout

`deploy_release` stays `enabled=False` and server-refused. PR #80 stays draft until Acceptance A
is green. Merge and production enablement (`deploy_release`) remain owner-authorized.
