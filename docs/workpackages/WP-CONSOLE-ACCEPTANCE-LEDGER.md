# Operations Console — Acceptance Ledger

**Repository freeze:** `feature/operations-console` is FROZEN (2026-07-28) until VPS acceptance
completes. **Code is frozen as of `edce3c8`**; this ledger is the only commit on top of it and is
docs-only. The stable check at the box is: *working tree clean, tip matches
`origin/feature/operations-console`, no code changes since `edce3c8`.* During acceptance: no feature work, no refactoring, no "while we're here,"
no "one quick fix." Only **observe · diagnose · record · decide**. If a package bug appears:
stop → record it here → fix in Git → redeploy cleanly. **Never patch the server directly.**

> The next artifact this project produces should be acceptance evidence from the real box, not
> another commit. — governance note, preserved verbatim: stop improving the implementation once
> implementation is no longer the bottleneck.

Fill the table in during the acceptance session. This document IS the acceptance record.

| Step | Expected | Actual | Evidence | Pass |
|---|---|---|---|---|
| Deploy dry run | Clean tree; tip matches origin; code unchanged since `edce3c8`; plan reviewed | | | |
| Apply (once, no improvisation) | Service starts under `tcgrowth`; snapshot created first | | | |
| Bind check | Loopback only (`ss -ltn` shows 127.0.0.1:8385) | | | |
| Tunnel | Console reachable at `http://localhost:8385`; unreachable without tunnel | | | |
| Auth | Bad/missing token fails closed; login with token succeeds | | | |
| SMTP Test | Steps stream; email arrives; `completed / success`; **no password in stream or evidence** | | | |
| Integrity clean | `completed / clean` (exit 0); scanner sha256+commit in evidence | | | |
| Controlled fixture | `completed / findings / attention` (exit 2) — **not** "failed" | | | |
| Cleanup | Fixture removed → `completed / clean` again | | | |
| Script identity | Console and cron invoke the SAME deployed scanner (same hash + commit) | | | |
| Redeploy (idempotency) | Second `--apply` is a no-op in effect; prior session rejected after redeploy | | | |
| Rollback test (optional) | `--rollback` restores prior state | | | |

**Acceptance decision:** all rows pass (rollback row optional) → Console MVP **ACCEPTED**; then
revisit merge strategy (Scenario A vs B) and resume development (OP3 / registry decoupling).
Any row fails → recorded above as a **deployment-package defect**, fixed in Git, redeployed from
the start. Failures are evidence against the package, never a reason to improvise on the server.

**Recorded debt (post-acceptance):** the deployment package is now product code and deserves its
own version, changelog, regression tests, and acceptance history — hold it to the production
quality bar or it decays into another manual process.
