# TC AI Operations Platform — Roadmap & Operating Strategy

Living document. This is an **AI Operations Platform** (growth is its first specialist module),
not a bag of AI features. This file records where we are, the principles we build by, and the
sequenced next steps. **Progress and release gates live in `docs/STATUS.md`** — phases here map to
releases there (Phase 3 ≈ Release 0.3, Phase 4 ≈ 1.0/1.1, Phase 5 ≈ 2.0). The architecture is
FROZEN unless a fundamental flaw appears: every new capability strengthens the governance doors —
the phase gate, the store, the approval path — or it waits.

## Where we are (2026-07)

- **Phase 1 — autonomous loop: DONE.** read → reason → investigate → report → deliver, running on
  the VPS as a hardened non-root systemd timer (Mon 07:00 Europe/Madrid) via IONOS SMTP.
- **Phase 2 — persistence & operating system: built (slices 1–5, 7, 8).**
  - SQLite store (schema v2): `runs`, `cases` (opened_by/closed_by), `decisions` (made_by).
    Structure in columns, narrative in an append-only `body` journal.
  - Case #1 seeded = `INC-2026-02-01` (Merchant Center tobacco spam).
  - Token/cost captured and logged per run.
  - **Memory-aware coordinator** (reads known cases) + **memory-writing agent** (case_search /
    case_open with duplicate refusal / case_note / case_set_confidence / decision_log as proposals;
    case_set_status is ALWAYS_ASK — lifecycle changes need a human).
  - **Store repository interface**: callers depend on the `Store` protocol; SQLite is an
    implementation detail behind `open_store()`.
  - **Model policy**: task-kind → tier (weekly-report → Sonnet, investigate → Opus,
    monitoring → Haiku opt-in), overridable via `TC_MODEL_POLICY` JSON.
  - **Read-only dashboard v1**: GET-only stdlib server on 127.0.0.1 (SSH-tunnel access),
    overview + case pages. No write path by construction.
  - *Remaining to activate on the VPS:* pull main, `db-init`, updated systemd unit (data dir).
- **Slice 6 — act on live findings: OPEN (operational).** Spam re-verification `investigate` run,
  SEO draft text for the ES rental page + home canonicals, and the human WP task: fix the
  conversion-tracking gap (GA4 purchase event + Woo attribution) — the ROI blocker.

## Operating principles (the sequence that keeps risk down while value compounds)

1. **Staging first.** WordPress connector writes to staging only; production is read-only until a
   deliberate switch.
2. **Read-only first, then drafts, then controlled execution.** Enforced in code by the phase gate.
3. **Approval before writes.** Draft-only in Phase 1–2; `ALWAYS_ASK` tools need human confirmation.
4. **Evidence before conclusions.** Observations ≠ hypotheses ≠ conclusions; no compromise/causation
   claim without a verification step. (Calibration prompt.)
5. **Memory before more intelligence.** Continuity and context beat a sixth analytical tool.
6. **Production is sacred.** The agent grows revenue; it never risks rentals, checkout, or bookings.

## Architectural principles for the store (calibrated from review feedback)

The store is the source of truth for the operating system — hold two disciplines, and resist a third.

- **Hold: callers never touch SQL.** Everything goes through `store.create_case()`, `store.log_run()`,
  etc. Already true — SQL lives only in `store/records.py`. Keep it that way.
- **Hold (bake in soon): a backend-neutral repository seam.** Introduce a `Store` interface so a
  future `PostgresStore` is a drop-in for `SqliteStore`. The one thing genuinely painful to retrofit
  is SQL-dialect coupling (`?` vs `%s`) — isolating it early is cheap, so do it before the schema
  grows. Do **not** build `PostgresStore` itself until there's a real need (SQLite is right for a
  single-node VPS for a long time).
- **Resist: speculative schema.** Entities with stable identity and relationships — yes (we already
  have human `ref`s + foreign keys). But grow the schema *with the feature that writes it*, not ahead
  of it. Add `opened_by`/`closed_by` when the agent starts opening cases; add a `tasks` table when we
  build the approval queue; add numeric `confidence` when the agent starts updating it. Dead columns
  are a cost, not a head start.

## Phase 3 — VALIDATION MODE (current)

The build is done; the objective changes. We are no longer adding capabilities — we are
validating that the architecture behaves correctly. Every change from here must answer YES to
at least one of:

1. **Does it increase trust?**
2. **Does it reduce operational risk?**
3. **Does it make production deployment safer?**

Anything answering "no" to all three is parked until after production is working.

Structure:
- **3A Polish** (done): run summaries, decision queue in memory context, confidence-evolution
  display, CLI approvals. No new intelligence.
- **3B Staging validation** — work through `docs/VALIDATION.md` until every box is green:
  content drafts at DRAFTS phase against staging, memory behaviors, approval round-trips,
  WordPress draft fidelity. Gate: ALL green + **two consecutive clean Mondays** (no calibration
  failures, no duplicate cases, no re-proposed decided items).
- **3C Approvals**: CLI only (`decision-approve` / `decision-reject`) — zero web attack surface,
  authenticated, audited. Dashboard buttons are a separate, deliberate decision LATER, because
  they turn a GET-only dashboard into a write path.

## Phase 4 — Production shadow mode, then drafts

**Standing requirement (agreed 2026-07-06):** even when a future production profile enables
writes (1.1+), write-capable operations against production require an EXPLICIT per-run human
confirmation on top of the profile cap, the phase gate, and ALWAYS_ASK — production writes are
never a default, only an answered question. Auto-deploy scope stays the orchestrator only:
DB migrations beyond additive ones, connector/plugin updates, and infra changes remain
intentional human deployments.

**Memory review gate (agreed 2026-07-08):** memory can go stale — some policies are
environment-dependent (e.g. "the connector reads staging" is false the day it points at
production). Therefore every release/phase transition includes a MEMORY REVIEW before it
completes: walk the decision log and every `approved` decision is explicitly re-affirmed for the
new era or superseded; open/monitoring cases re-checked for still-true framing. The per-site
store split makes the production cutover itself a curation moment: production either shares the
business memory deliberately or starts from a reviewed subset — never inherits staging's memory
by accident. Writing discipline: phrase policies as timeless where possible ("label every data
source with its environment"), date-and-scope them otherwise. First-class Knowledge/Strategy
objects with versioning and active flags remain the 2.0 answer.

Shadow mode is already implemented by the phase gate: point the connector at production and keep
runs at READ_ONLY — the agent documents what it *would* do (drafts as text, cases, proposals) and
nothing executes. Gate to leave shadow mode: **N consecutive clean cycles of judgment** (reports +
investigations on production data with zero calibration failures and drafts the human would have
approved) — cycles, not raw recommendation counts. Then: resync staging↔production → production
DRAFTS phase → publishing stays human-approved permanently.

## Memory 2.0 spec (agreed 2026-07-08 — build in Release 2.0, when its readers exist)

Current memory (statuses + append-only journal + bounded recency injection + per-site stores +
the human memory-review gate) is accepted for 0.x/1.x. Its known weakness: it relies on humans
remembering to govern. Memory 2.0 makes staleness machine-readable:

1. **Split operational facts from timeless principles.** Operational memory = keyed, typed facts
   that change (`connector.target = staging`, plugin versions, migration status) with
   environment metadata and review triggers. Principles = versioned Knowledge records that
   rarely change ("label every evidence item with its source environment").
2. **Environment metadata on every environment-specific item**, so applicability is computed
   (`item.env == active profile env`), not remembered.
3. **Review-on-event** (preferred over dates for this project): `review_after:
   production-migration` — at injection time, past-due items are WARNED about, never silently
   dropped.
4. **Confidence on decisions** (cases already have it) so uncertainty is expressible.
5. **Contradiction detection** — tractable BECAUSE of (1): two facts with the same key and
   different values is a mechanical conflict, flagged before any human review. Free-text cannot
   be reliably contradiction-checked; keyed facts can.
6. **Knowledge provenance** — every knowledge item carries its derivation chain (source case,
   evidence items with their environments, human reviewer, approval). "Why do we believe this?"
   becomes a query, not archaeology. (The primitive form exists today — decision→case links,
   basis/rationale text — 2.0 makes it structural.)

**Promotion criteria (brake on the graduation path):** not every lesson deserves to become a
hard rule — a system that encodes every mistake as a mechanical constraint calcifies. A
principle graduates only through: observed independently ≥3 times → survived one release →
no contradictions → human approval → constitution; and only after a further release →
runtime enforcement.

**North star for Memory 2.0 (verbatim, agreed 2026-07-08):** the goal is not to make the AI
remember more — it is to make memory less necessary, by progressively moving verified
operational rules into deterministic runtime enforcement. The model reasons; the platform
guarantees the critical invariants.

**Memory hierarchy & graduation path (design principle):** code gates > constitution (VISION) >
structured knowledge > journal narrative. Principles that prove permanent graduate UPWARD —
e.g. "never corroborate production claims with staging data" lives today as a policy decision;
its 2.0 destination is mechanical: every tool result carries an environment label and the
runtime flags cross-environment inference itself. The strongest memories are the ones the model
cannot forget because they are enforced, not recalled.

## Phase 5 — Business Operating System (parked until the action loop is boring)

Memory grows from three objects (cases, decisions, runs) toward five: + **Knowledge** (persistent
facts: "the Scott Addict 50 is the standard rental road bike") and **Strategy** (business policy
the coordinator consults: "never publish automatically", "never overbook"), and eventually
**Assets** (an index of pages/products/tours so the agent knows what exists instead of
rediscovering it). Discipline unchanged: each object gets its table when the feature that READS
it is built — the agent should end up with a business model, not just a memory, but not by
speculative schema.

## Next steps (sequenced)

- ~~**Slice 4 — Store repository interface.**~~ DONE (PR #11).
- ~~**Slice 5 — the agent writes to memory.**~~ DONE (PR #12). Target Monday behavior now reachable:
  *"INC-2026-02-01 · monitoring · no recurrence · confidence 0.82→0.96 · no action."*
- **Slice 6 — act on the live findings (read/draft-only). ← CURRENT.** On the VPS: activate the
  store (`db-init`), run the **spam re-verification** `investigate` (day-by-day 90-day timeline to
  confirm decay), generate production-safe **SEO draft text** for the Spanish `/alquiler_bicicletas/`
  page + home canonical fix. Human task in WP: fix the **conversion-tracking gap** (GA4 purchase
  event + Woo Order Attribution) — the blocker for all ROI measurement.
- ~~**Slice 7 — model policy.**~~ DONE (PR #13). Weekly→Sonnet, investigate→Opus, monitoring→Haiku
  (opt-in); per-run cost logging makes tier choices verifiable.
- ~~**Slice 8 — private web dashboard (v1).**~~ DONE (PR #14) as read-only loopback + SSH tunnel.
  v2 (later): approvals/actions — only after the read side is trusted in daily use.
- **Slice 9 — new specialists.** Pricing, advanced SEO, reservations, workshop, inventory, forecasting —
  each inheriting memory, strategy, and prior decisions rather than starting cold. Gated on the
  long-lead credentials below.

## Next structural slice (admitted under the 0.3 filters) — DONE 2026-07-06

**Multi-site profiles (portability + safe production gateway).** Passed filters 2 and 3
(reduces operational risk; makes production deployment safer): today Phase 4 would mean
hand-editing `.env` in place — the exact "wrote to production thinking it was staging" hazard.
Requirements (agreed 2026-07-06):
- No hardcoded URLs (already true — audit confirmed all site facts come from Settings).
- Every command resolves a site profile: `--site staging|production|<name>` or `TC_SITE`,
  loading `profiles/<name>.env`.
- Profiles define: base/connector URL, environment name, credentials/signing key, language/SEO/
  builder plugins, db_path, and **allowed capabilities** — a profile-level `allow_writes=false`
  blocks draft tools in code BENEATH the phase gate (production defaults read-only).
- Separate credentials, signing keys, and logs per profile; dashboard and every report/log line
  display the active profile (STAGING / PRODUCTION) unmistakably.
- Same codebase runs against dev, production, or any other WordPress site by adding a profile.

## Post-1.0 backlog (captured, deliberately NOT now)

Good ideas that fail the Release 0.3 filters; recorded so they aren't lost and aren't built early:

- **Reliability metrics as a first-class feature (build FIRST post-0.3, before new capabilities):**
  false-positive rate, duplicate-case rate, missed detections, average investigation cost,
  decision-reuse rate. The runs/cases/decisions tables already carry the raw data. Trust comes
  from being predictably correct over months, not from features.
- **Operations Console (dashboard v2) — full CLI parity, owner request 2026-07-12:** the goal is
  that routine operation NEVER requires SSH/bash; the terminal remains for sysadmin work only.
  Everything the CLI does becomes a governed UI control:
  - **Decision queue:** approve / reject with a required basis text field; add decisions;
    record outcomes (worked / didn't / partial).
  - **Cases:** status select (open / monitoring / resolved — ALWAYS_ASK-class transitions get an
    explicit confirmation step), add case notes, set confidence with basis.
  - **Run launchers via the Execution API (below):** investigate-with-question box, draft test
    with target picker, on-demand report, smoke test. The dashboard never executes anything
    itself — it enqueues NAMED operations only.
  - **Agent communication channel:** a task/question box per case (and global) — each submission
    becomes a normal governed run (phase gate, cost log, audit) whose result attaches to the
    case journal + notifies. A task channel with memory, NOT a freeform chat that bypasses
    governance. (Proven manually 2026-07-12: the blind re-examination run was exactly this
    workflow over SSH.)
  - **Hard prerequisites before ANY write control ships:** session auth + CSRF (Basic Auth is a
    read-gate, not a write-gate), actor recorded on every journal/decision entry ("who clicked"),
    per-action confirmations, loopback+reverse-proxy topology unchanged. The GET-only v1 is a
    security wall; v2 replaces it deliberately in one reviewed step, not by accretion.
  - Plus the earlier v2 items: case impact scores (revenue at risk / SEO / urgency), evidence
    deep-links (GA4/GSC/Woo), lifecycle timeline (detected → investigated → proposed → approved →
    executed → verified → closed).
  - Sequencing inside 1.x: reliability metrics first, then decision-queue buttons (highest
    daily value), then case controls, then run launchers + task channel.
  - **Rev 2 (2026-07-12, after external review — artifact "TC Operations Console" rev2):**
    two-layer navigation (owner "Business" layer: Today / Sales & Bookings / Approvals is the
    default landing; "Technical" layer beneath); new sections **Backups**, **Integrations
    health**, **Changes/drift feed**, **Permissions**; business-impact fields required on every
    case and decision (severity, revenue/customer impact, rollback, verification) — a broken
    checkout and a stale sitemap must not queue as equals. Access philosophy reworded: "full
    diagnostic sight, constrained hands, explicit escalation" — capability registry (id, class,
    risk, approval, timeout, rollback, verification probe, state) defined BEFORE more screens;
    escalation modes: standard probes → staging read-only SQL (limits, audit, expires) →
    **sanitized diagnostic replica** read-only SQL (PII AND secrets removed, scrub verified by
    probe, inert — no mail/webhooks/cron, owner-approved per investigation, snapshot age on
    every result; verifies the DB backup layer only — NOT full disaster recovery; build only
    after ordinary probes prove insufficient) → guarded registered actions (⛉ per-run). Free-form
    SQL on the LIVE production DB stays out (masking arbitrary SQL is not reliably solvable).
    Bookings/availability READS are ordinary gated 1.x capabilities (the constitution restricts
    writes, not reads); booking/price WRITE capabilities can only ever be created via an
    explicit owner amendment of VISION.md at a dedicated gate — never via a spec revision.
    Anti-goal recorded: the dashboard is a thin layer over working CLI/API capabilities, shipped
    slice-by-slice where it replaces real recurring manual work — it must not become the project.
- **Post-generation report validator (reject-and-regenerate; the 0.3-legal subset already
  ships as warning-only lint + mechanical masking + injected dates):** before a report is
  stored/delivered as valid, deterministic code rejects violations — unmasked transactional
  IDs, future dates, robots.txt-as-noindex, past-event CTR recommendations (needs Site
  Intelligence lifecycle states), purchase claims missing required fields, scheduled-report
  headers on manual runs. On failure: regenerate once with violations attached; still failing →
  withhold + record a report-quality failure. Lesson from 2026-07-13: prompt tests prove rules
  EXIST; only deterministic post-processing proves mechanical rules are OBEYED; semantic rules
  are validated by graded live runs. Related Memory 2.0 field (review round 4): cases carry a
  keyed `fix_date` fact so the platform can COMPUTE incident-contamination percentages of a
  report window and inject them — until then, the model omits percentages and states dates.
- **External Reviewer Council (post-Site-Intelligence; spec agreed 2026-07-13):** owner-registered
  external AI reviewers independently challenge the primary agent's PROPOSALS (decisions/drafts —
  not whole reports; review the diff, not the world) before synthesis. Design, validated by a
  week of running it manually (Claude primary · ChatGPT adversarial · owner adjudicating):
  - **Controlled council, not a chatroom:** independent first pass on the same sanitized
    evidence packet (no anchoring — the reviewer never sees the primary answer first), ONE
    challenge round, one synthesis. Stop on: factual dispute needing new evidence, repetition,
    cost cap, or owner-judgment questions.
  - **Adjudication by experiment, not rebuttal:** the challenge round must yield TESTABLE
    claims; the orchestrator runs them against the diagnostic probes and synthesis cites test
    results. (Every real dispute this week was settled by a curl/source-read/measurement —
    never by argument quality.)
  - **Preserve disagreement:** output = primary recommendation · reviewer objection · evidence
    each way · remaining uncertainty · what evidence resolves it · owner decision required.
    Agreement is NOT truth: provider diversity ≠ error diversity (all three reasoners committed
    the same findings→causes error this week — correlated failure is the default).
  - **Registry entries = capability-registry rows:** provider, connection (native adapter
    first; MCP context exposure later; A2A only on proven need), role (evidence verifier /
    commercial / risk / contrarian), profile + environment scoping, sanitized data access (no
    PII, no credentials, no cross-profile memory), can-propose-never-execute, cost cap,
    timeout, mandatory-for classes. Reviewer output is UNTRUSTED EVIDENCE (prompt-injection
    surface); only the platform writes memory/cases/decisions.
  - **Reliability scores from adjudication records:** every reviewer claim gets a disposition
    (adopted / rejected-with-basis / already-fixed) — the decision-queue pattern; the score is
    the measured adopt-rate, not a configured number.
  - **Scope discipline:** start with ONE second-provider reviewer on high-impact items only
    (production recommendations, low-confidence findings, owner-requested second opinions);
    implementation is thin — a second runtime adapter + a governed run type over the existing
    task-channel/evidence plumbing. Build order: Site Intelligence FIRST (more intelligence
    without shared facts amplifies confusion; a shared world model is what makes added
    intelligence valuable).
- Notifications for high-priority cases and completed on-demand runs (email exists; push later).
- **Property & Environment Control Plane (2026-07-13; NOT a separate build — it is the
  Operations Console's context selector + capability-registry rows):** the hierarchy is
  Property → Environment (`tossacycling` → production/staging; later `tourdegirona`), never a
  flat profile list. Identifiers (`property_id`, `environment_id`, `profile_id =
  <property>-<environment>`) are established BEFORE production connects (WP-05); profile
  examples renamed accordingly. Context is request-scoped in any future dashboard
  (`/properties/<p>/environments/<e>/…`), never a mutable global. Memory: environment-scoped
  operational facts vs property-level business knowledge = Memory 2.0's `scope` field; first
  production store is fully separate with a reviewed, provenance-marked seed of policy
  decisions + active cases (never staging run history). Fail-closed rules: unknown profile,
  cross-property visibility, credential reuse, profile-less scheduled unit, banner/hostname
  mismatch. Production connector installs with the server-side write kill-switch
  (`TC_GROWTH_DISABLE_WRITES` — write routes never registered). Add-property wizard: far
  future; two properties are safer with hand-authored, human-reviewed profile files.
- **Execution API / task queue (instead of SSH, ever):** the agent requests NAMED operations
  (run validation, refresh site profile, smoke test, generate report); the orchestrator executes
  only whitelisted commands locally and returns structured results. The agent never holds shell
  credentials. Complements GitOps auto-deploy for operational (non-deploy) actions.
- **Site Intelligence module (Type A — FIRST capability of the next release; absorbs the
  earlier "Site Inspector"). Origin: 2026-07-13 owner insight** — the first scheduled report
  recommended CTR-optimising an EXPIRED Tour de Girona edition because the agent had analytics
  for URLs but no model of the site: it didn't know `/tour_de_girona-listado/` is the menu-linked
  hub that already routes demand to future editions. Analytics without structure = confident
  wrong recommendations. Merged design (owner + external review + our refinements):
  - **Four connected maps:** technical URL map (status, final URL, canonical, hreflang, language,
    title/meta/H1, indexability, template, in/out links, menu+sitemap presence) · content
    structure (hub → edition, category → product, ES ↔ EN pairs) · business-role map (hub /
    category / product / upcoming event / past event / info / transactional / legal / archive —
    role determines allowed recommendation types) · conversion-path map (where each page's
    traffic is supposed to go next).
  - **Lifecycle states, mechanically derived, BUILT FIRST** (cheapest, kills the whole
    error class): events draft→upcoming→closed→ongoing→past→cancelled from event dates;
    products active/temporarily-unavailable/seasonal/discontinued from Woo status. Rule:
    a past event can never receive a CTR recommendation — only route-to-hub improvements.
  - **Storage = Memory 2.0 keyed facts:** graph rows (page, role, state, language pair, hub
    parent, relationships) live in the existing SQLite store as additive schema, every fact
    carrying environment + snapshot timestamp + source (API vs crawl) provenance. NOT a new
    parallel system — this completes Site Inspector + SITE_PROFILE + Memory 2.0 as one build.
  - **Three scan levels — never a full crawl per report:** (1) baseline discovery once
    (WP REST + menus + Woo + events + Yoast sitemap + GSC URL set + controlled public crawl
    with deny-list: cart/checkout/order-*/account/add-to-cart params, rate-limited, staging-
    proven before production); (2) incremental diff before each report — which IS the console's
    Changes feed ("Event X moved upcoming→past, product Y disappeared, page Z changed
    canonical, page A published but orphaned"); (3) mandatory recommendation-time LIVE fetch of
    any page the agent proposes changing, even when the cached map has an answer.
  - **Human classification pass:** owner approves the load-bearing roles (primary hubs, money
    pages, current-vs-historical, intended funnels, never-auto-redirect pages) — agent infers,
    human ratifies, exactly like SITE_PROFILE today.
  - **Report integration:** weekly report opens with map version + changes since last sync;
    every recommendation must cite the target page's role, lifecycle state, parent hub, and
    conversion destination. Recommendation rubric: search opportunity × business relevance ×
    availability × conversion-path quality × technical confidence × cost — never impressions ×
    position × CTR alone.
  - **Site Architecture Advisor** (monthly/on-demand, after the map is stable): navigation,
    taxonomy, orphans, duplicate intent, expired content, weak funnels, ES/EN inconsistencies,
    consolidation opportunities — the owner's "organize and present the content" workstream.
  - Retained from Site Inspector: whitelisted fields only, never raw wp_options, never customer
    PII; staging↔production structure DIFF doubles as the Phase-4 resync check. Principle
    unchanged: the agent may know everything about HOW the business works; it does not
    automatically see everything the database CONTAINS.
- **qTranslate-aware connector fields (Type A):** the site uses qTranslate XT — both languages
  live inside the same post fields as `[:es]…[:en]…[:]` tagged strings (NOT WPML/Polylang
  separate posts). The connector should expose and accept per-language values (or validated raw
  tagged strings) for title/meta/content so a draft can never ambiguously overwrite both
  languages. Until then the prompt-level safety rule holds: preserve tags, write both language
  blocks, never untagged single-language strings (validation findings, 2026-07-06 draft test —
  draft 50455 wrote untagged fields).
- Business-operations tiles (unanswered inquiries, bike utilization, failed payments, review
  responses, workshop delays) — this is Release 2.0 territory: it requires the Assets/Knowledge
  objects and new read integrations.
- **Execution / Work-Package object (2.0, part of Tasks):** first-class tracking of
  case → decision → approved → executed → verified → closed. v1 covers this today with existing
  pieces: decisions.outcome (`decision-outcome` CLI) + case journal entries + docs/workpackages/
  checklists — build the table when the workflow outgrows them.

## Longest-lead external items (start early)

- Google Ads developer token + Meta app review (needed before Ads analysis is real).
- Decide production write path: resync staging with production, or switch the connector to production
  read-only first — before any Phase 3 write capability.
