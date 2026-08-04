# WP-U4 — Controlled Decision Workflow (spec)

**Status: SPEC — for review on the PR thread (charter: issue #68).** U4 is the increment that
converts the platform from *reporting* to *operations*: a decision is understood, approved, and
verified-executed in the browser, then disappears. Boundary per the charter: U3b answers *what
needs my attention*; U4 answers *why should I approve this, what happens if I do, and can the
platform close the loop safely.*

## The auditable acceptance core: the eliminated-actions table

Reviewer requirement (#68): state what disappears and what stays manual on purpose. U4
acceptance checks this table row by row, like U1's button inventory.

| Current owner action | After U4 |
|---|---|
| Approving/rejecting decisions via copied CLI (`decision-approve …`) | **DISAPPEARS** (U4a: browser Approve/Reject with evidence in view) |
| Telling the store what happened after acting in WP admin (the D#9/D#10 sync chore, done twice this week) | **DISAPPEARS** (U4b: the platform verifies the live page against the approved content and marks executed itself) |
| Reading "why should I approve this" out of a long email report | **DISAPPEARS** (U4a: evidence, impact, confidence on the decision itself) |
| Applying approved SEO changes in production WP admin by hand | **REMAINS MANUAL for now** — production writes are a separate capability (WP-08 class) with its own acceptance; when it lands, connector apply slots into this same workflow with no redesign. Until then: approve in browser → apply in WP → platform verifies + closes |
| Staging apply for draft-class decisions | Connector apply via the existing approved-apply path (already accepted, staging-only per D#7) |
| Release authorization, merges, deploys | **INTENTIONALLY MANUAL** — human by governance, not by limitation |

## Schema (store v4 — additive migration, same pattern as v3)

`decisions` gains: `kind` (e.g. `seo_meta_update` — selects the apply/verify path) ·
`payload` (the EXACT actionable content, e.g. JSON `{post_id, title_es, meta_es, title_en,
meta_en}`) · `content_sha256` (hash of payload — what approval binds to) · `evidence` (pointers +
key numbers: report artifact id, GSC figures) · `impact` (estimate, honestly labeled as
estimate) · `confidence` (label) · `approved_at/by` · `executed_at` · `execution_evidence`
(run/artifact ref). All nullable; legacy decisions render as today (title+rationale) and are
NOT approvable via U4 controls (no payload = nothing to bind to — visible, with that reason).

`report_artifacts` gains nullable `recommendations_count` (best-effort parse of the Recommended
Actions section at persist time) — feeds the business-review homepage block.

## Approval semantics (constitutional, from the WP + charter)

1. **Content-bound:** Approve records `content_sha256` of the exact payload. Any payload edit
   reverts status to `proposed` and voids the approval (storage-layer guard, v3-trigger style:
   payload/hash immutable while status is `approved` — change requires un-approval first).
2. **Approve ≠ execute:** two separate recorded events, two separate controls. Execute is
   enabled only while stored hash == approved hash.
3. **Approvable = accepted path exists:** only `kind`s with a registered verify/apply path show
   enabled controls; everything else renders visible-but-disabled with the reason.
4. **Every act is logged** as a run (actor=human, decision id, hashes) — approvals are
   governance evidence like everything else.

## Execution + verification (the U4b loop)

For `seo_meta_update` (the first and only kind in U4):

- **Staging decisions:** Execute runs the existing accepted connector apply (staging-only, D#7
  intact) through the Execution Service, then verifies.
- **Production decisions (D#9-class):** Execute is a *verification* act — a read-only registry
  operation `verify_decision_execution` fetches the live page(s), compares title/meta against
  the approved payload (normalized), and on match marks executed + stores the evidence (URLs,
  matched values, fetch hash). On mismatch: honest failure, decision stays approved-not-executed.
  This makes "owner applies in WP, platform closes the loop" a verified workflow instead of a
  trust-me workflow — and it is exactly what the lead did by hand for D#9/D#10 this week.

## UI (U4a + U4c)

- **Decision detail** (`/decision/<id>`): evidence, impact, confidence, exact payload preview,
  hash, history (proposed→approved→executed with timestamps/actors), Approve / Reject buttons
  (CSRF POST; Console-session auth). Reject asks for a one-line reason.
- **Homepage smart card** (upgrade of the U3b.1 simple card, now that the data exists): top
  decision with impact + confidence + "Review →" to the detail page.
- **Business-review report block** (charter gap 1): date, one-line result, recommendations
  count, Read → ; run ids/hashes move to the detail page only.
- **Labels** (charter gap 3): 🔴 Action required / 🟡 Keep an eye on. **Recent operations**
  collapses to secondary (charter gap 2).

## Explicitly out of scope

Production WP writes (WP-08, own acceptance) · new decision kinds beyond `seo_meta_update` ·
notifications (post-U4, per roadmap) · multi-user/roles.

## Exit conditions

1. Eliminated-actions table verified row by row in the owner's browser.
2. One real decision completes the full loop: proposed (with evidence) → approved in browser →
   applied (staging: connector; production: WP admin) → verified + auto-marked executed →
   disappeared from the queue, evidence retrievable.
3. Package-gate items 5–8 close (see WP-CONSOLE-USABILITY product gate).
4. **U2 basic-auth retirement review triggers** — criterion (b) "U4 approval authority goes
   live for daily use" is met at U4 acceptance; the Console-native single login gets scheduled.

## Build order

**U4a** schema v4 + decision detail + approve/reject (eliminates the CLI chore) →
**U4b** `verify_decision_execution` + executed lifecycle (eliminates the sync chore) →
**U4c** smart card + business-review block + labels/collapse. Each phase: tests + CI + review
on its PR + owner-authorized merge; deploys via the release runbook as always.
