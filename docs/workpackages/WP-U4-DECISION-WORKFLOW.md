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

**Approval binds to a target-bound ENVELOPE, not bare payload bytes** (review #69 pt 1): an
identical SEO payload approved for the wrong site/profile must be impossible by construction.

```json
{"schema_version": "u4/1",
 "profile": "<site profile id>",
 "environment": "staging|production",
 "kind": "seo_meta_update",
 "target": {"object_type": "wp_post", "post_id": 13699,
            "expected_urls": {"es": "https://…/alquiler_bicicletas/",
                              "en": "https://…/en/alquiler_bicicletas/"}},
 "payload": {"title_es": "…", "meta_es": "…", "title_en": "…", "meta_en": "…"}}
```

**Canonical serialization (pt 2), pinned:** `envelope_sha256 = sha256(json.dumps(envelope,
sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))` — UTF-8, stable
key order, no insignificant whitespace, `schema_version` inside the hashed bytes. Same logical
envelope always hashes identically; any material change (including target or environment) never
does. A canonicalization unit test with byte-exact fixtures ships with U4a.

`decisions` gains: `kind` · `envelope` (canonical JSON text) · `envelope_sha256` · `revision`
(INTEGER, optimistic concurrency) · `evidence` · `impact` · `confidence` (both structured — see
provenance below) · `approved_at/by` · `executed_at` · `execution_evidence`. All nullable;
legacy decisions render as today and are NOT approvable via U4 controls (no envelope = nothing
to bind to — visible, with that reason).

**Impact/confidence carry provenance (pt 6)** — structured, never a bare number:
`{"value": "+200–500 visits/mo", "label": "estimate", "method": "GSC position/CTR heuristic",
"source": "report artifact #N", "as_of": "2026-08-03"}`. The UI renders the `estimate` label
visibly; a missing field renders **unknown** — unknown beats invented precision.

`report_artifacts` gains nullable `recommendations_count` (pt 7): best-effort parse at persist
time; parse failure stores NULL and renders **"unknown"**, never zero; it can never affect
report validity or the validator. Structured recommendation metadata at generation time is the
better long-term source — recorded as a candidate improvement, introduced only via its own
reviewed change to the generation path.

`report_artifacts` gains nullable `recommendations_count` (best-effort parse of the Recommended
Actions section at persist time) — feeds the business-review homepage block.

## Approval semantics + state machine (constitutional; review #69 pts 1–4, 9)

**Allowed transitions — exhaustive; anything not listed is refused loudly:**

| From | Action | To | Notes |
|---|---|---|---|
| proposed | approve | approved | records envelope_sha256, approved_at/by; requires confirmation step |
| proposed | reject (reason required) | rejected | reason stored |
| approved | unapprove | proposed | explicit human act; approval fields cleared |
| approved | envelope edit | proposed | automatic void: storage guard refuses envelope/hash change while approved — edit requires unapprove first (v3-trigger style) |
| approved | verify/apply FAILED | approved | attempt recorded with evidence; decision does NOT close |
| approved | verify/apply SUCCESS | executed | executed_at + execution_evidence stored; leaves the queue |
| rejected | re-propose | proposed | new revision; new envelope allowed |
| executed | (terminal) | — | immutable outcome; corrections are NEW decisions |

**Concurrency (pt 3):** every mutation carries the expected `revision`; a mismatch fails
visibly (stale-tab guard), never silently merges. Mutations are idempotent where safe (approve
of an already-approved identical hash = no-op success) and loud everywhere else.

**Authority + audit identity (pt 9):** the Console is single-operator by design today — actor
is recorded as `owner` with the session-issued timestamp and decision revision in every audit
row. Approve requires an explicit confirmation step (two clicks); reject requires a reason.
When the U2 basic-auth retirement lands a named Console login, the actor field carries the
username with no schema change. Until then, "who approved" is unambiguous because exactly one
human holds the token — and that assumption is written here so the retirement review must
revisit it.

**Approvable = registered path exists:** only `kind`s with a registered verify/apply path show
enabled controls; everything else renders visible-but-disabled with the reason. Every act is
logged as a run — approvals are governance evidence like everything else.

## Verification + apply (the U4b loop)

**Control naming (pt 4):** production decisions get a **"Verify live change"** control — the
platform is NOT executing anything there; the owner edits WP, the platform verifies and closes.
"Apply" appears only where the platform genuinely applies (staging, once its dependency below
is met). No control may overstate its authority.

**Verification semantics for `seo_meta_update` (pt 5), exact and fail-closed:**

- Fetches BOTH `target.expected_urls` (ES and EN — each language variant is its own URL under
  the site's qTranslate routing; language-correct values must appear on their own URL).
- Requirements per URL: final HTTP 200; redirect chain permitted only if the FINAL URL equals
  the expected canonical; the page's `<link rel=canonical>` must equal the expected URL.
- Comparison: `<title>` and `meta[name=description]` vs the approved payload — Unicode NFC
  normalization, whitespace collapsed, then exact match.
- Cache policy: requests sent with cache-bypassing headers; **two consistent reads ≥ 60s apart**
  are required before marking executed (a cached page must not close a decision).
- Evidence stored either way: both URLs, final status/redirect chains, fetched title/meta
  verbatim, response body hashes, timestamps of both reads.
- **Fail-closed:** ALL languages must match on BOTH reads. One language matching is a MISMATCH —
  recorded, surfaced, decision stays approved-not-executed. This workflow is exactly what the
  lead did by hand for D#9/D#10, now with rules instead of judgment.

**Staging apply is a DEPENDENCY, not an available path (pt 8 — corrected from spec v1).**
Verified on current `main`: the connector path exists as phase-gated TOOLS
(`wp_create_seo_draft` @ Phase.DRAFTS; `publish_seo_draft` @ Phase.CONTROLLED_EXECUTION,
ALWAYS_ASK — `core/approval.py:44,50`), NOT as an Action Registry operation, and the Console
runs READ_ONLY. Registering an apply operation (with environment=staging binding, ALWAYS_ASK
confirmation flow, and its own acceptance) is a distinct dependency milestone. **U4 therefore
ships production-verify first (U4b); staging Apply arrives only when its dependency passes
acceptance** — the workflow needs no redesign either way.

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
