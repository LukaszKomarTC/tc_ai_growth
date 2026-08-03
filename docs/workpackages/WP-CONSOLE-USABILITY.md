# WP-CONSOLE-USABILITY — the owner can operate the platform

**Status: U1 + U2 ACCEPTED · U3a MERGED to main (f0e5a50), production convergence pending ·
next: U3b.** U3a review round (2026-08-03): approved after four conditions — rebase onto main,
delivery bound to the artifact ROW (id identifies, hash verifies; twin-artifact regression
proven), one-artifact-many-delivery-attempts (`report-redeliver`), 205 tests green. Immutability
is constitutional in the Store protocol, storage-layer enforced. Accepted debt: split report.py
into builder/validator/delivery/artifacts after U3.

**U2 acceptance record (owner-run, 2026-08-03).** https://ops.tossacycling.com live from any
device: IONOS A record + Plesk subdomain + Let's Encrypt TLS + 301 → Apache basic auth →
proxy to loopback :8385 (this Plesk is Apache-only — NO nginx, so no proxy rate limit;
deviation + compensating controls recorded in docs/RUNBOOK-CONSOLE.md). Verified through the
URL: SMTP test and a full 114.9s integrity scan streamed to completion (evidence run#27 —
keepalives survived the proxy). TC_CONSOLE_TOKEN rotated (F4 CLOSED). Sign out control built,
e2e-tested (194 green), deployed as Console release `ab9afa4` and verified in-browser.
RUNBOOK-CONSOLE.md delivered (access, rotation, troubleshooting, security model). Basic auth
remains transitional per the retirement criteria above. Gate items now satisfied: 1, 2, 9, 10
(restart), plus 3 partially (badge; the full source-truth panel is U3b). Remaining for the
package gate: 4–8 (U3a/U3b/U4).

**U1 acceptance record (owner-run, in-browser, 2026-08-03).** Deployed release `63448f3`
(three dry-run/fix/redeploy rounds surfaced and fixed four truth defects: stale review-branch
check + `TC_BUILD_COMMIT=unknown` provenance in the deploy script, stream death on silent
operations U1-1, duplicate Evidence/Logs nav U1-2, per-release evidence store U1-3 — see
WP-CONSOLE-ACCEPTANCE-LEDGER.md). Final sheet, all PASS: wrong token fails closed · sign-in with
PRODUCTION badge · exactly two operations, no dead controls (OBS-1 closed by construction) ·
SMTP test streams + emails · integrity scan survives its ~2-min quiet stretch on keepalives and
resolves on-screen (`COMPLETED — CLEAN · evidence run#24 · 113s`) · Evidence tab opens the
operation log reading the SHARED durable ledger (#23+, alongside weekly report runs) · Cases is
a labeled placeholder · service restart keeps working (sessions survive restart by design —
stateless signed cookies; only a redeploy/new-commit or token rotation invalidates; the
acceptance script's "restart signs you out" expectation was wrong, not the system) · all judged
in the owner's actual browsers on two machines. Open wording debt: scan card promises "each
check streams as output" but a clean run is quiet by design — truth-polish alongside F6. The platform has
proven it can run; this work package proves the owner can operate it. Scope is the reviewer's
**conservative option** — the owner-facing operational minimum. WP-07/WP-08 production reads,
FinOps, connectors, and role administration are explicitly **out** until this gate closes.

## The product gate (single acceptance criterion for the whole package)

> **Can Łukasz open the dashboard without technical assistance and complete the main weekly
> workflow without using Bash?**

Made concrete — the milestone is complete only when the owner can personally:

1. Open a bookmarked HTTPS URL.
2. Sign in without SSH.
3. See exactly which profile and data sources are active.
4. Read the latest weekly report.
5. See pending decisions.
6. Approve, reject or defer a supported decision.
7. See whether the resulting action happened.
8. View evidence or an understandable failure message.
9. Log out.
10. Repeat the process after a server restart.

No terminal. No asking where the dashboard is. No mystery buttons. Final proof: **one full weekly
report cycle operated end-to-end without Bash.**

## Honest current state (verified in code, 2026-08-03)

What exists: the Operations Console (loopback, token sign-in, TWO accepted operations with
preview/execute/stream/evidence) and a separate read-only status dashboard (loopback :8383,
designed for a Plesk reverse-proxy that may never have been configured). What does NOT exist in
any browser surface: reports view, cases view, decisions view, approve/reject. The store does not
persist weekly-report bodies at all — `runs` records carry only `summary`/`detail` (verified in
`store/records.py:log_run`). This package is a **build with increments**, not a cleanup; each
increment lands with its own acceptance before the next starts.

## U1 — Console integrity (repair; no new features)

Redeploy tc-console from current `main` (registry = accepted operations only) via the existing
deployment package. Closes OBS-1 structurally — "what a user can click == what passed acceptance."

**Acceptance (all five, not just the first):**

1. **Button-by-button inventory** — every visible control either works or is disabled with a
   label stating why ("not implemented", "requires production read — disabled under D#7"). A
   control that looks active and silently fails is a defect, full stop.
2. **Fresh deployment test** — deploy from a NEW detached release worktree pinned at the reviewed
   `main` commit, never from existing working-directory state (release-directory rule, D1).
3. **Restart test** — `systemctl restart tc-console` and confirm the Console returns correctly
   (sign-in works, operations render, prior sessions invalidated as designed).
4. **Negative-path test** — at least one invalid/unauthorized attempt (bad token at sign-in;
   POST without CSRF) verifies a useful failure with NO execution.
5. **Browser reality test** — accepted in the browser the owner actually uses, not via curl or
   automated tests alone.

## U2 — Secure owner access (fixed HTTPS + runbook)

Target model: fixed HTTPS address · authenticated · no public anonymous access · session logout ·
clear profile/environment banner · one-page access-and-recovery runbook. No corporate identity
system — a secure, simple owner login is enough.

Implementation: a Plesk-managed private subdomain (TLS) reverse-proxying to the loopback Console,
with basic auth at the proxy in front of the Console's token session.

**Basic auth is TRANSITIONAL, not architecture.** It is accepted for the owner-only phase ONLY
under all of these conditions:

- HTTPS mandatory (no plaintext path exists);
- the Console keeps listening on loopback only; the reverse proxy is the sole external path;
- the Console is never exposed directly to the internet, even behind an obscure URL;
- rate limiting applied at the proxy;
- access logs exclude tokens and session cookies;
- the raw token-entry endpoint is not reachable externally except through the authenticated proxy;
- credentials rotate through a documented process (runbook);
- **retirement criteria stated here:** basic auth is replaced by a single Console-native owner
  login (one auth layer, per-user credential, proper logout/rotation) no later than the first of:
  (a) any second person needs access, (b) U4 approval authority goes live for daily use, or
  (c) the end-of-package review. The double layer must not survive into multi-user operation.

Also in U2: TC_CONSOLE_TOKEN rotation (F4, folded in since sign-in is touched), a logout control,
reboot-survival verification. **Mandatory security review round before DNS goes live** (this
exposes an execute-capable UI — a larger authority than the read-only dashboard).

Deliverable the owner keeps: **RUNBOOK-CONSOLE.md** — URL, sign-in, logout, credential
rotation/revocation, what to do after a server restart, and the recovery path when it breaks.

## U3a — Immutable report persistence (data model only; no UI)

Persist the exact validated weekly-report artifact — not "add a TEXT column." The stored record
carries: profile · reporting window · generated timestamp · validator version + result · run ID ·
model + cost · **content hash** · artifact format/version · delivery status · the **immutable
original body**.

**The trust chain is the requirement:**

> generation → validated immutable artifact → hash → persisted artifact → email delivery →
> dashboard display

The body that is hashed is byte-identical to the body that is emailed; the dashboard later
displays that artifact by hash, provably the same one that passed validation. Delivery status is
mutable metadata AROUND the immutable core — the body itself is never updated. (This also grows
the validator's real-corpus regression set with every Monday run.) Acceptance: for one real
report, prove email content and stored artifact match by hash.

## U3b — Minimal operator homepage (presentation only; brutally minimal)

**Hard acceptance criterion (reviewer, 2026-08-03): no routine SSH for the owner.** Routine
report access and re-delivery become browser actions in U3b (re-delivery is a natural registry
operation — read-only body, existing governed execute path). Routine *deploys/rollback* from the
browser are explicitly NOT U3b: they require root-level authority the Console deliberately does
not hold (tcgrowth + one sudoers line), so browser-deploys are their own reviewed increment
after U4, not a side effect of a homepage.

One homepage answering five questions, in order: **1.** Did the scheduled report run
successfully? **2.** What requires my attention? **3.** What decisions are waiting? **4.** Any
infrastructure/data problems? **5.** What was executed recently?

Content is EXACTLY: current profile + source/environment truth panel · latest report status and
link (to the U3a artifact) · pending decisions · open cases requiring attention · recent
operation results. **No charts unless they directly improve a decision. No decorative KPIs. No
analytics dashboard. No provider settings. No navigation tree.** The purpose is to shorten the
owner's Monday workflow, not demonstrate frontend capability.

**Environment truth is a panel, never one label:**

> **Profile:** Tossa Cycling · **Operating environment:** Staging · **Analytics:** Production
> read-only · **WordPress:** Staging · **WooCommerce orders:** Staging / not production truth ·
> **Production writes:** Disabled

The red/amber badge stays for at-a-glance identity; the panel is the authority. A single label
would hide the mixed-source reality and invite trusting staging Woo data as production evidence.

## U4 — Controlled decision workflow (capstone)

Approve / reject / defer a supported decision from the browser, routed through the
origin-agnostic Execution Service like any operation — server-side phase/approval/environment
enforcement, evidence recorded, result visible (gate items 6–8).

**Decision semantics are precise or the feature is dangerous.** For every approval the browser
shows: exact proposed content/operation · profile and environment · target object · consequences ·
whether approval executes immediately or only authorizes later execution · expiry/invalidation
conditions · the evidence supporting the proposal.

**Approvals are content-bound:** the approval records the hash of the exact draft; editing the
draft after approval INVALIDATES the approval (consistent with the existing production-write
safety requirement). Approval and execution are separate recorded events. Only decision types
whose apply-path is accepted are approvable; everything else renders visible-but-disabled with
the reason. First candidates: D#9/D#10-class title/meta drafts — narrow, visible, and bindable to
an exact draft. This increment gets the same review rigor the Execution Service itself got:
approval is THE control point of the platform.

## Order and gating

**U1 → U2 → U3a → U3b → U4**, each with its own acceptance before the next starts. U3 is split
deliberately: persistence (data model) and presentation (UI) fail differently and must be
isolatable. U1 needs no owner decision and is authorized. U2 needs the owner once (subdomain +
basic auth in Plesk from written instructions). The package closes only on the product gate: one
weekly cycle, no Bash.

## Out of scope (deliberately)

WP-07/WP-08 production reads · WooCommerce order matching · profile administration · FinOps ·
infrastructure controls · communication connectors · role systems · charts/KPIs. Each returns to
the queue only after the owner has comfortably used the Console for at least one full weekly
cycle.

## Standing constraints

Owner is release authority · freeze protocol (all changes through Git) · all production-checkout
Git as `tcgrowth` (D5) · autodeploy stays disabled (separate review) · deploys are deliberate,
evidence-gated, with rollback points.
