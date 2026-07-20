# Maintainer review — Future Functions Master Roadmap (2026-07-20)

Review of `docs/FUTURE_FUNCTIONS_MASTER_ROADMAP.md` against the repository as it exists
(frozen candidate 527fdea + feature branches + audit register R1–R35). Verdict up front:
**adopt as the umbrella roadmap**, with five named conflicts that must be resolved by
explicit owner decisions — not silently absorbed. Where the master roadmap and the
repository constitution disagree, the constitution wins until amended.

## Status map — what is already real

The document is strongest where it describes things this repo has already built or specced;
that is evidence the shared memory is accurate, and it means several "future functions" are
not future:

| Roadmap item | Repository state |
|---|---|
| Evidence/case/decision model | BUILT (store v2/v3; cases, decisions, runs, snapshots) |
| Site map and content graph | BUILT as WP-06 (feature branch, merges post-gate); "scheduled crawl" is a later extension |
| Investigation cases / decision ledger | BUILT (incl. amendment classes + cooldown in governance docs) |
| Technical Inspector + Technical Memory | SPECCED this week (4 slices; July investigations as acceptance fixtures) |
| Backup Guardian | CAPTURED (build order #3 matches our capture list) |
| Prompt caching telemetry | CODE-COMPLETE (`feature/prompt-caching`, protocol in docs/PROMPT_CACHING.md) |
| FinOps cache-aware costing + pricing registry | OPEN as FINOPS-001 (section 11's "critical known requirement" IS FINOPS-001) |
| SSH/WP-CLI + source inspection | WP-07 code-complete (source reader), WP-08 specced (DB reader) — the roadmap's allowlist/redaction/audit requirements are already implemented patterns |
| Dashboard operating console | SPECCED (Operations Console v2, incl. "structured actions before free chat" — same rule, earlier wording: "a task channel with memory, NOT a freeform chat that bypasses governance") |
| Acceptance-gates section (17) | Already our operating practice — it quotes this week's caching gate verbatim |

## Per-idea assessment (new capabilities)

### Multi-profile registry + isolation (P0) — AGREE, one design decision to make explicitly

Correctly ranked as the highest-risk architectural requirement, and it is the right P0:
Tossa Cycling + Tour de Girona are already two businesses in one platform, and every new
capability multiplies the contamination surface. One structural disagreement:

**CONFLICT 1 — `profile_id` column vs database-per-profile.** The roadmap assumes one
shared database with `profile_id` on every row. The platform today isolates by SEPARATE
per-site store files — which is structurally *stronger*: a missing WHERE clause cannot leak
across files, and "never copy staging run history into the production store" is enforced by
file boundaries, not query discipline. Recommendation: keep DB-per-profile + a profile
REGISTRY (the roadmap's profile object, pointing at each store), and reserve `profile_id`
columns for genuinely shared tables (pricing registry, audit log) if any. Decide at Store
v3 / Evidence Platform design time; do not let the shared-DB assumption slide in via a
migration.

The rest of section 5 is adopted as written — explicit profile+environment on every
connector call with no silent write defaults, profile-scoped secrets, banner invalidation
on switch, explicit logged cross-profile links.

### Environment truth model — AGREE; mostly formalization

`site_label`, SITE_PROFILE rule #7 (staging rendered SEO output is never evidence), and
snapshot provenance already implement most of this. New and worth adopting: explicit
`validity window` and `authority rank` per evidence item — that is the generalization of
the evidence-tier ladder WP-06 lifecycle already uses. Fits Evidence Platform v1.0.

### Task and action registry — STRONG AGREE; this is the 1.1 write-safety backbone

"Replace free-form execution with named, structured operations" is exactly the direction
R8 (content-bound approval) and R9 (compensated publication) already mandate as 1.1 gate
criteria, and the Console spec's "the dashboard never executes anything itself — it
enqueues NAMED operations only." Build the action schema (preconditions, approval,
environment, rollback, verification) ONCE and make publish_seo_draft its first migrated
operation — R8/R9 then become properties of the registry, not per-tool patches.

### Technical Inspector / Technical Memory / Backup Guardian — AGREE with sequencing

Matches existing specs. One new constraint the roadmap surfaces that our capture missed:

**CONFLICT 2 — restore tests collide with staging-as-write-lab.** "No backup is proven
until a staging restore test passed" is the right definition of Backup Guardian truth. But
staging is ALSO the platform's write laboratory: a restore test overwrites staging state,
including growth drafts awaiting approval and the connector's own data. Restore tests need
a scheduling/coordination rule (announced window, draft-state check before restore, or a
separate restore target) — record this in the Backup Guardian spec before slice 1.

### Communication Intelligence (email → WhatsApp → voice) — HIGHEST VALUE, and the
### hardest governance lift in the whole document

The channel sequencing (IMAP read-only → WhatsApp inbound official API → Ringover pilot
number) and the never-list (no autonomous confirmation of availability, discounts, refunds,
complaints, exceptions) are exactly right. Three named issues:

**CONFLICT 3 — "personal data never enters model context" (WP-08 rule) is incompatible
with communication intelligence as stated.** Reading a customer email IS personal data in
model context — there is no way to classify an enquiry without seeing it. The rule was
written for database reads and remains correct there. Communications need their OWN
data-class policy, decided by the owner as a material governance change: what may enter
context (message bodies from designated business mailboxes/channels), what never may
(payment data, ID documents), what is stored (references + minimized structured facts —
the roadmap already says this, adopt verbatim), and retention/erasure procedure.

**CONFLICT 4 — append-only evidence vs GDPR erasure.** The evidence model says append-only
and immutable; GDPR says erasable on request. For communication data, resolve by
REFERENCE-not-COPY: the mailbox/WhatsApp account remains the system of record; the evidence
store keeps message references plus minimized extracted facts; erasure = delete the facts
and dead-reference the pointers. This must be designed in before the first IMAP ingestion,
not retrofitted.

Voice additionally: Spain requires informing callers of recording/transcription; keep the
roadmap's "no emotion, personality, health, nationality or accent inference" as a
constitutional-class rule (it also tracks EU AI Act prohibitions); transcript-not-audio
retention is the right default. Temporary-number pilot before porting the real number is
non-negotiable — the business number is operationally sacred.

WhatsApp: official API requires Meta Business verification — start that early (it is the
communication channel's equivalent of the Google Ads developer-token long-lead item).

### Availability read / reservation summary / soft holds — AGREE with one boundary made explicit

Availability read (non-PII, environment+freshness-stamped) and reservation summaries are
ordinary read-layer work. Soft holds are the first write into the operational domain —
acceptable ONLY as internal objects in OUR store (expiry, source, staff owner), never
writes into WooCommerce. A hold that exists only in the platform's store has zero blast
radius on the booking system; conflict checks read Woo, never touch it. Adopt with that
constraint stated.

### Approved booking creation — FLAG: constitutional territory, not just "late phase"

**CONFLICT 5 — the sacred zone.** The repository constitution: booking/checkout logic is
FORBIDDEN capability territory; financial transfers are absolute (no tool, no amendment
path). Creating a booking is not literally `modify_booking_logic`, but it creates orders,
reserves inventory, and touches money state — it is the sacred zone by any honest reading.
If this capability is ever built, it requires: (a) an explicit owner constitutional
amendment (material class, full cooldown), (b) the action registry as its substrate, and
(c) a permanent carve-out: booking creation NEVER captures or moves payment — payment
remains Woo/human exclusively, per the financial-transfers-absolute rule. The roadmap's
placement at priority #9-of-11 is right; the review's job is to say it is not merely late,
it is gated on an amendment that today does not exist.

### AI Organization (providers/models/roles/teams) — AGREE on the model, caution on the build

The object model is correct, especially "tool permissions attach to roles, never to
models" (extends our phase-gate-by-tool with a role dimension) and "agent instances hold
no permanent authority." Two cautions: (1) build it as CONFIG TABLES first, admin UI last —
the dashboard audit (WP-D, stored XSS R17) showed UI is a liability surface; (2) the
platform's actual need today is one provider + a model policy table — build AI Organization
when the second provider is real, not before (the roadmap's own "grow schema with the
feature that writes it" discipline).

### AI FinOps + pricing registry — AGREE; already in motion

FINOPS-001 is this. The roadmap adds the quality dimension (acceptance rate, correction
rate, cost per resolved case) — right long-term, and the run/case/decision tables already
hold most raw data (the "reliability metrics first" backlog item). Self-optimization
progression (advisory → approval → policy for low-risk roles only) matches the platform's
progression discipline; adopt as written.

### Plesk API integration — AGREE; treat as WP-08's sibling

Scoped service account, narrowest API tokens, named operations, no root: same enforcement
pattern as WP-07/WP-08 (allowlist + reason codes + metadata-only audit + budgets). Build it
as another governed reader on the same chassis, not a new pattern.

### Scheduled reports / condition alerts — AGREE

Deduplication + severity thresholds + notify-on-exception is the answer to alert fatigue
(named in section 18 — correctly, as a real failure mode: an ignored alert system is worse
than none).

## Sequencing verdict

The recommended priority order (section 19) is accepted as-is. Item 1 is "finish the
current validation gate and preserve frozen-main discipline" — which is where we are.
The near-term winning combination named in the final recommendation (profile isolation,
Technical Inspector, Backup Guardian, FinOps, read-only email intelligence) matches the
post-gate capture list already recorded, with email intelligence as the one genuinely new
build commitment — and it is the right first communication channel: lowest platform
complexity, highest chance of immediately preventing a missed sale.

## Adopted amendments (review round 2, 2026-07-20 — owner + reviewer convergence)

The reviewer (ChatGPT) accepted this review's five conflicts (agreeing outright on four and
resolving Conflict 1 the same way from the SaaS-architecture direction), and the roadmap is
**accepted as the long-term architectural baseline with these six explicit amendments**
rather than a rewrite:

1. **Dedicated evidence stores per profile + a shared profile registry** — isolation by
   file/store boundary, not by `profile_id` WHERE-clause discipline. The registry is the
   only shared layer; cross-profile joins are impossible by construction. (Resolves
   Conflict 1; also yields per-profile backup/export/deletion and legal isolation.)
2. **Staging lifecycle policy** — staging carries a declared mode: `developer` /
   `validation` / `restore-test`. Only restore-test mode may be overwritten; Backup
   Guardian refuses a restore in any other mode, the same enforcement pattern as the phase
   gate on a new axis. This also protects pending drafts and validation state generally,
   not just from restores. (Resolves Conflict 2.)
3. **Communications governance policy as a first-class chapter** — email/WhatsApp/voice
   data gets its own policy (what may enter model context, what never may, storage,
   retention, erasure), NOT an exception carved out of the DB-read PII rule. Material
   governance change; owner approval + cooldown before any ingestion. (Resolves
   Conflict 3.)
4. **Reference-not-copy evidence model for communications** — the communication system
   (mailbox, WhatsApp account, telephony provider) remains the system of record; the
   evidence store holds references + minimized structured facts; erasure deletes facts and
   dead-references pointers. Designed in before the first IMAP ingestion. (Resolves
   Conflict 4.)
5. **Booking operations elevated to the financial governance tier** — constitutional
   safeguards, not merely "late phase": explicit owner amendment with cooldown before any
   booking-write capability exists; payment capture permanently excluded. (Resolves
   Conflict 5.)
6. **Capability as a future first-class object** — a reusable business function above
   tools/connectors declaring required connectors, executing role, and produced evidence.
   **Sequencing constraint (maintainer):** Capability is an abstraction OVER named
   operations and must be extracted, not designed up front — action registry ships first,
   real operations get composed by hand in investigations, and the repeating compositions
   become the first capabilities. Capability is the action registry's second major
   version, not a parallel object built speculatively.

On AI Organization, the reviewer stresses long-term durability (provider layer fully
swappable, nothing above it changes); this review's caution was build TIMING (config
tables first, admin UI last, second provider before the machinery). Both hold — recorded
as importance: high, build trigger: second real provider.

## Actions arising

1. ~~Resolve CONFLICT 1~~ RESOLVED (amendment 1): DB-per-profile + shared registry;
   implement at Evidence Platform v1.0 design.
2. ~~Restore-test/staging-collision rule~~ RESOLVED (amendment 2): staging lifecycle
   policy (developer/validation/restore-test modes) goes into the Backup Guardian spec.
3. Owner decision still required before any communication ingestion: the communications
   governance policy (amendment 3) + reference-not-copy design (amendment 4) exist as
   agreed DIRECTION; the policy document itself is the material change that needs formal
   approval + cooldown.
4. Booking creation gated on a constitutional amendment that does not exist (amendment 5);
   payment capture permanently excluded either way.
5. Start the two long-lead external items early: WhatsApp/Meta Business verification;
   Ringover trial account.
6. Action registry becomes the designated substrate for R8/R9 (1.1 write-safety) — and,
   later, the substrate Capability (amendment 6) is extracted from.
