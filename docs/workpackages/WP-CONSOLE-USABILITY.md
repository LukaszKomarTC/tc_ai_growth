# WP-CONSOLE-USABILITY — the owner can operate the platform

**Status: SPEC — awaiting owner review.** Adopted 2026-08-03 from the owner/reviewer direction:
the platform has proven it can run; this work package proves the owner can operate it. Scope is
the reviewer's **conservative option** — the owner-facing operational minimum. WP-07/WP-08
production reads, FinOps, connectors, and role administration are explicitly **out** until this
gate closes.

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
any browser surface: reports view, cases view, decisions view, approve/reject. And the store
does not persist weekly-report bodies at all — `runs` records carry only `summary`/`detail`
(verified in `store/records.py:log_run`), which is why the run #20 corpus fixture had to be
reconstructed from an email paste. So this package is a **build with increments**, not a cleanup;
each increment lands with its own acceptance.

## Increments

### U1 — Repair: Console redeploy from clean `main`

Redeploy tc-console from current `main` (registry = accepted operations only) using the existing
deployment package and its regression: login · SMTP test · integrity clean · fixture→findings ·
remove→clean. This closes OBS-1 structurally — "what a user can click == what passed acceptance."

**Acceptance is a button-by-button inventory, not "redeployed successfully":** every visible
control either works or is disabled with a label saying why ("not implemented", "requires
production read — disabled under D#7"). A control that looks active and silently fails is a
defect, full stop.

### U2 — Access: fixed HTTPS address + runbook

Target model (reviewer-set): fixed HTTPS address · authenticated · no public anonymous access ·
session logout · clear profile/environment banner · one-page access-and-recovery runbook. No
corporate identity system — a secure, simple owner login is enough.

Implementation direction: a Plesk-managed private subdomain with TLS + basic auth,
reverse-proxying to the loopback Console — the same pattern the dashboard unit was designed for.
Two auth layers (basic auth at the proxy + the Console's token session) in front of an
execute-capable UI; loopback binding unchanged; nothing listens publicly except Plesk's nginx.
Includes: TC_CONSOLE_TOKEN rotation (F4, folded in since sign-in is touched anyway), a logout
control, and verifying the unit survives reboot.

**Security review round is mandatory before DNS goes live** (exposing an execute-capable UI is a
larger authority than the read-only dashboard): rate limiting at the proxy, fail-closed on missing
auth, no secrets in rendered pages, CSRF/session hardening re-verified through the proxy path.

Deliverable the owner keeps: **RUNBOOK-CONSOLE.md** — the URL, how to sign in, how to log out,
how to rotate/revoke access, what to do after a server restart, who to call when it breaks (the
recovery path, not a person).

### U3 — Operating surface: one homepage, five questions

The homepage answers, in order:
1. Did the scheduled report run successfully? (last run, status, next timer firing)
2. What requires my attention? (open cases by status)
3. What decisions are waiting? (D#9/D#10/D#11-style queue with age)
4. Are there any infrastructure or data problems? (failed runs, unavailable sources)
5. What was executed recently? (operations history with outcomes)

Prerequisite build item: **persist the weekly-report artifact** (body) at generation time so
"read the latest report" is a page, not an email search. Policy: store validated bodies with the
run record (size-capped, path-redacted per the existing redaction rules); this also grows the
validator's real-corpus regression set — two birds.

**Environment truth is a panel, never one label.** The current mixed state (profile STAGING,
analytics production read-only, WP/Woo staging) is technically explainable but operationally
dangerous if compressed to a single badge. The surface shows source truth separately:

> **Profile:** Tossa Cycling · **Operating environment:** Staging · **Analytics:** Production
> read-only · **WordPress:** Staging · **WooCommerce orders:** Staging / not production truth ·
> **Production writes:** Disabled

The existing red/amber badge stays for at-a-glance identity; the panel is the authority.

### U4 — Decision workflow: approve / reject / defer in the browser

The capstone: a pending decision (like D#9) can be approved, rejected, or deferred from the UI,
routed through the origin-agnostic Execution Service exactly like any operation — server-side
phase/approval/environment enforcement, evidence recorded, result visible in the UI (gate items
6–8). Approval stays THE control point of the whole platform, so this increment gets the same
review rigor the Execution Service itself got. Only decision types whose apply-path is accepted
are approvable; everything else renders as visible-but-disabled with the reason.

## Order and gating

U1 → U2 → U3 → U4, each with its own acceptance before the next starts. U1 needs no owner
decision and can start immediately. U2 needs the owner once (create the subdomain + basic auth in
Plesk from written instructions). The package closes only on the product gate: one weekly cycle,
no Bash.

## Out of scope (deliberately)

WP-07/WP-08 production reads · WooCommerce order matching · profile administration · FinOps ·
infrastructure controls · communication connectors · role systems. Each returns to the queue only
after the owner has comfortably used the Console for at least one full weekly cycle.

## Standing constraints

Owner is release authority · freeze protocol (all changes through Git) · all production-checkout
Git as `tcgrowth` (D5) · autodeploy stays disabled (separate review) · deploys are deliberate,
evidence-gated, with rollback points.
