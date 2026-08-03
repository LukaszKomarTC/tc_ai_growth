# Operations Console — Acceptance Ledger

**Repository freeze:** `feature/operations-console` is FROZEN (2026-07-28) until VPS acceptance
completes. The freeze admits exactly one kind of change: **defect fixes recorded in the Defect
log below**, per the protocol (stop → record → fix in Git → redeploy cleanly). The stable check
at the box is: *working tree clean, release checkout pinned at the reviewed commit, and that
commit on `origin/feature/operations-console`.*

## Defect log (found in VPS preflight recon 2026-07-29 — before any deployment)

| ID | Defect | Fix (in Git) |
|---|---|---|
| D1 | Package defaulted to deploying from the live app checkout — which is dirty and drives `tc-weekly-report` / `tc-autodeploy`; switching it would have changed production-scheduled code and tainted the Monday gate | Release-directory deployment: the script deploys **the checkout it lives in**; preflight **refuses** an `APP_DIR` referenced by the production schedule units; identity check supports **detached worktrees pinned at the reviewed commit** (verifies the pin against `origin/feature/operations-console`) |
| D2 | Package assumed the service user could run the integrity scan; recon proved `tcgrowth` cannot read the WP docroot | One narrowly-scoped, **visudo-validated** sudoers drop-in: exact root-owned script path, **zero arguments**, NOPASSWD, shown verbatim in the deploy plan; CLI runs `sudo -n -- <script>` when `TC_INSPECTOR_SUDO=true`; sudo's `env_reset` pins the scan target against env override; scanner deployed 0755 root-owned (readable for provenance hashing, root-writable only); unit drops `NoNewPrivileges` (blocks setuid) and uses `ProtectSystem=full` (strict broke sudo's `/run` timestamps + the scanner log) — rationale in the unit comments |
| D3 | `--rollback` routed every restore through the dry-run wrapper with apply unset — **rollback printed instead of executing** (found by re-review) | Rollback sets apply mode explicitly, restores unit + inspector + sudoers state (or removes what a first install created), and still echoes every action |
| D5 | **Redeploy was structurally impossible** (found on the first real redeploy attempt, 2026-07-29): (a) preflight rejected port 8385 held by the *running Console itself*; (b) phase 4 used `enable --now`, which does not restart a running service — new code would never load. Also operator-procedural: root ran `git status` in the tcgrowth-owned worktree, root-owning the index and breaking the owner's fetch (recovery: `chown -R tcgrowth` the worktree + its `.git/worktrees/console` admin dir) | Preflight allows the port when `tc-console.service` itself is active (it gets restarted); phase 4 is `enable` + `restart` (covers fresh and redeploy); all identity-check git in the script now runs as the checkout's OWNER (`rgit` via `sudo -u`), so root deploys can no longer root-own the index | During acceptance: no feature work, no refactoring, no "while we're here,"
no "one quick fix." Only **observe · diagnose · record · decide**. If a package bug appears:
stop → record it here → fix in Git → redeploy cleanly. **Never patch the server directly.**

> The next artifact this project produces should be acceptance evidence from the real box, not
> another commit. — governance note, preserved verbatim: stop improving the implementation once
> implementation is no longer the bottleneck.

Fill the table in during the acceptance session. This document IS the acceptance record.

| Step | Expected | Actual | Evidence | Pass |
|---|---|---|---|---|
| Deploy dry run | Clean tree; pinned commit on origin; plan reviewed | Detached worktree `/opt/tc_ai_growth/console` @ `bda3111`, clean, "matches origin tip"; full plan reviewed incl. exact sudoers rule | dry-run output 2026-07-29 06:06 UTC | ✅ |
| Apply (once, no improvisation) | Service starts under `tcgrowth`; snapshot created first | All steps executed as printed; visudo "parsed OK"; unit enabled+started; zero improvisation | apply output 06:09 UTC; snapshot `/var/backups/tc-console/20260729-060924` | ✅ |
| Bind check | Loopback only | `LISTEN 127.0.0.1:8385` only; service `active (running)` | `ss -ltn` 06:11 UTC | ✅ |
| Tunnel | Console reachable at `http://localhost:8385` via SSH tunnel only | Login page served over `ssh -L 8385` from owner's laptop | owner session 06:17 UTC | ✅ |
| Auth | Bad token fails closed; real token admits | Invalid token rejected ("correctly rejected the login"); real token → Operations panel | owner confirmation | ✅ |
| SMTP Test | Steps stream; email arrives; `completed / success`; no password in stream | connect→starttls→auth→send all green; `COMPLETED — SUCCESS · run#1 · 0.201s`; email received at lukaszkomar@gmail.com 08:21 CEST; stream showed user, never password | `run#1`; Gmail receipt | ✅ |
| Integrity clean | `completed / clean` (exit 0); scanner sha+commit in evidence | `COMPLETED — CLEAN · run#2 · 97.631s`; first line `scanner: wp-integrity-scan.sh sha256=7368b48c5a536023 commit=bda3111` | `run#2` | ✅ |
| Controlled fixture | `completed / findings / attention` (exit 2) — **not** "failed" | Inert PHP fixture in uploads detected and named (`wp-content/uploads/tc-acceptance-fixture.php`); `COMPLETED — FINDINGS · run#3 · 100.18s`; exit step rendered informational, result amber | `run#3` | ✅ |
| Cleanup | Fixture removed → `completed / clean` again | `COMPLETED — CLEAN · run#4 · 98.214s` | `run#4` | ✅ |
| Script identity | Console and cron invoke the SAME deployed scanner | Every run logged identical `sha256=7368b48c5a536023 commit=bda3111`; cron (`17 4 * * *`) calls the same `/usr/local/bin/wp-integrity-scan.sh` the unit pins | runs #2–#4; root crontab | ✅ |
| Evidence in Logs panel | Runs visible with correct domain labels | `completed · success`, `completed · clean`, `completed · findings` (amber), `completed · clean` — in order, each with scanner provenance | Logs panel 06:41 UTC | ✅ |
| Redeploy (idempotency + session invalidation) | Second `--apply` no-op in effect; prior session rejected after redeploy | Redeploy to `94c945a` succeeded after the D5 fix (running-service port allowed; enable+restart loads new code); pre-redeploy session rejected (owner re-authenticated); second `--apply` produced an identical plan, fresh snapshot `20260729-071037`, replace-not-duplicate on unit/inspector/sudoers, health check OK | apply outputs 07:05 + 07:10 UTC; owner sign-out | ✅ |
| Fix-batch verification (D4/F1/F2/F3) | Button resets; 300s scan budget; PRODUCTION badge; paths reduced | Button ends on **Run again** (SMTP `run#5 · 0.179s` on production); badge renders PRODUCTION filled red; scan budget 300s in registry; stream redaction live | browser session 07:10 UTC; screenshot | ✅ |
| Rollback test (optional) | `--rollback` restores prior state | — deferred to a separately planned test window with defined expected results (per review: not casually on the live accepted Console) | | ⏳ planned |

**Acceptance decision (2026-07-29): the Operations Console MVP is OPERATIONALLY ACCEPTED.**
Both operations proven on the production VPS with correct outcome semantics, streamed evidence,
and provenance; positive AND negative detection demonstrated (clean → findings → clean). The two
deferred rows ride along with the first post-acceptance redeploy. Next: merge strategy
(Scenario A vs B) and the post-acceptance queue below.

## Defects & follow-ups found DURING acceptance (fix in Git, in this order)

| ID | Item | Severity |
|---|---|---|
| D4 | Execute button stays "Running…" after completion (both ops): the event stream never signals termination — server holds the connection open after the final frame, so the client read loop never resolves. Fix: close the connection after the result frame; button lifecycle Preview → Running… → **Run again** | minor UX, systematic |
| F1 | Executor `cli_timeout_s` 120s vs observed ~98–100s scan runtime — margin too thin; make timeout a per-operation registry field | package limitation |
| F2 | Environment badge says STAGING (profile `env_kind` unset) while operating production-adjacent services — set `env_kind` explicitly and give the header an unmistakable color-coded badge | config + UI polish |
| F3 | Scanner's own header line prints the absolute docroot path into the browser stream (finding paths themselves are WP-relative) — redact stream detail like log summaries, or print the docroot relative | polish |
| F4 | Console token was displayed in a pasted terminal session during acceptance — rotate token + restart service now that acceptance is done | hygiene |
| F5 | `tc-autodeploy.timer` is `enabled` (inactive) and the box shows "System restart required" — decide autodeploy's fate BEFORE any reboot | ✅ RESOLVED 2026-07-29: disabled (`systemctl disable --now`) until its role is deliberately reviewed — an auto-deployer must not alter a commit-pinned accepted surface outside the reviewed process |
| F6 | Operation cards read `targets staging/production` (the op's *availability*) while the header states the actual environment — reword to `available in: staging / production` or show the current target, so card and badge can't be misread together | minor wording polish |
| OBS-1 | Live demonstration of the recorded registry debt: clicking `Refresh site-structure snapshot` (WP-06, NOT accepted) returned `404 rest_no_route` → correctly classed **EXECUTION ERROR** (`run#6`), but the op should never have shown as runnable — its backing WordPress route isn't present on the target. The phase gate covers *phase*, not *backing-capability presence*. This is exactly the "operations a user can click == capabilities that passed acceptance" invariant, unmet. Direct evidence FOR the Scenario-B registry decoupling (declared-but-disabled operations without their impl being present/accepted). Not a Console bug; a registry-availability gap. Do NOT fix under freeze — it is the merge-architecture work. | design (feeds Scenario B) |
| U1-1 | **Stream death on silent operations** (U1 acceptance, 2026-08-03, deploy `d260726`): a CLEAN integrity scan writes ~nothing to stdout for its whole ~2-min run (progress goes to its log; only findings `tee` mid-stream) → the execute stream carried ZERO bytes and the idle connection was silently dropped on the operator's NAT/tunnel path. Both ends waited forever: UI stuck on "Running…" while the backend completed and recorded evidence (`run#2`). July acceptance never caught it because findings fixtures stream chattily. Fix: server keepalive pulse every 10s (SSE comment, client-invisible) + client liveness indicator with an explicit "NO DATA — stream may be lost" state. OBS-1's cousin: a UI that says Running when the work is done is a truth defect | systematic (fixed this round) |
| U1-2 | "Evidence" and "Logs" nav tabs both pointed at `/logs` — the operator experienced "Evidence sends me to Logs". One tab per destination; page retitled Evidence | UX truth defect (fixed this round) |
| U1-3 | **Per-release evidence store**: the store path follows the code checkout (`BASE_DIR`), so every release worktree gets a FRESH database — Console evidence silently dies at each redeploy (July evidence `run#1–#6` stranded in the old release dir; new deploy restarted at `run#1`). Evidence that does not survive a deploy is not evidence. Fix: deploy script pins `TC_DB_PATH` to the durable shared store (weekly-ledger DB) via `TC_STORE_DB`; the plan states the store location either way | systematic (fixed this round) |
| U1-4 | Console emits nothing to journald (request/stream errors invisible; only sudo lines appear) — diagnosing U1-1 required client-side inference. Minimal app-level logging for stream lifecycle wanted; parked for U2 security-review round, not fixed here | observability debt (open) |

Row-failure protocol unchanged: recorded here → fixed in Git → redeployed from the start. Never
patch the server directly.

**Recorded debt (post-acceptance):** the deployment package is now product code and deserves its
own version, changelog, regression tests, and acceptance history — hold it to the production
quality bar or it decays into another manual process.
