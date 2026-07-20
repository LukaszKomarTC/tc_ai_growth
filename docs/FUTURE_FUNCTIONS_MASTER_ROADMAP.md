# AI Growth Platform — Future Functions & Implementation Master Roadmap

**Tossa Cycling / Tour de Girona**

> **Provenance:** consolidated by the owner + ChatGPT from the ChatGPT project memory;
> uploaded as `AI_Growth_Platform_Future_Functions_Master_Roadmap.docx`, prepared July 2026,
> captured into this repository 2026-07-20 during the Release 0.3 freeze (docs branch,
> merges post-gate). Content is a faithful conversion of the source document; the
> maintainer's review lives in `docs/reviews/FUTURE_FUNCTIONS_ROADMAP_REVIEW.md` — read
> them together. Where this document and the repository's existing constitution conflict
> (FORBIDDEN capabilities, financial-transfer prohibition), the constitution wins until an
> explicit owner decision amends it.

**Purpose:** This document consolidates the future capabilities previously defined for the
VPS / AI Growth platform into one implementation-oriented roadmap. It is designed as a
product specification, architecture guide, governance baseline, and sequencing plan.

## 1. Executive Recommendation

The platform should be developed as a modular, multi-profile AI operations system rather
than a collection of isolated automations. The core design goal is not maximum autonomy.
It is **controlled intelligence**: complete evidence, clear authority boundaries, reversible
execution, and measurable business value.

**Recommended operating model:** One shared orchestrator, many strictly isolated business
profiles, provider-agnostic AI roles, read-only evidence collection first, staging execution
second, and approved reversible production actions only after repeated proof.

The highest-value additions are not all equal. Communication intelligence, technical
inspection, backup verification, and AI FinOps can materially improve sales protection,
operational resilience, and decision quality. However, autonomous customer communication
and production repair actions create disproportionate legal and reputation risk and should
remain late-stage capabilities.

### Strategic priorities

| Priority | Capability | Business value | Risk | Dependencies | Phase |
|---|---|---|---|---|---|
| P0 | Core profile isolation | Prevents cross-site mistakes | Critical | Storage v3, registry | Foundation |
| P0 | Evidence / case / decision model | Makes all actions auditable | Critical | Profile isolation | Foundation |
| P1 | Technical Inspector | Finds site/server issues early | Medium | Read-only connectors | Early |
| P1 | Backup Guardian | Protects recoverability and cash flow | Medium | Plesk + Drive visibility | Early |
| P1 | AI FinOps | Controls cost and model allocation | Low | Usage telemetry | Early |
| P1 | IONOS email intelligence | Prevents missed enquiries | High privacy | IMAP + evidence model | Early-mid |
| P2 | WhatsApp Business intelligence | Captures primary sales channel | High | Official API, consent | Mid |
| P2 | Ringover voice intelligence | Closes communication loop | High | Pilot number, transcription | Mid |
| P2 | Availability / booking read layer | Improves customer support accuracy | Medium | Woo endpoints | Mid |
| P3 | Controlled production actions | Reduces manual work | Very high | Rollback + approvals | Late |
| P3 | Autonomous customer replies | Faster response | Very high | Mature evidence + policies | Late |

## 2. Platform Vision and Non-Negotiable Principles

- **Staging first:** Development and write testing occur on staging. Production writes are
  named, narrow, approved operations only.
- **Read-only before write:** Every connector starts with inspection and evidence collection
  before any modification capability.
- **Profile isolation:** Tossa Cycling, Tour de Girona, and future sites must have separate
  credentials, evidence, memory, cases, reports, and permissions.
- **Capability is broad; authority is constrained:** The system may understand any domain,
  but authority is limited by risk, environment, approval, rollback, and verification.
- **Evidence before conclusion:** Reports and decisions cite source systems, timestamps,
  environment, and confidence.
- **Snapshot and diff:** Everything observed by inspectors is dated, snapshotted, and
  compared with its predecessor.
- **No approve-equals-execute:** Approval authorizes a defined action; execution remains a
  separately logged step.
- **Reversibility:** Changes require backups, rollback instructions, or compensating actions.
- **Provider independence:** Business roles and workflows must not be hard-wired to one AI
  vendor.
- **Human control of customer commitments:** Prices, availability, bookings, refunds,
  complaints, and exceptions remain human-approved until proven safe.

## 3. Target Architecture

Shared runtime, isolated profile-scoped control planes. A profile switch must change every
relevant context source: credentials, environment, cases, evidence, site map, decisions,
reports, memory, jobs, and allowed actions.

| Layer | Main components | Design requirement |
|---|---|---|
| Experience | Dashboard, structured actions, approvals, reports, case views | Profile-scoped and role-aware |
| Orchestration | Coordinator, teams, policies, job scheduler, escalation | Provider-agnostic |
| AI Organization | Providers, models, roles, teams, agent instances | Configurable by admin |
| Evidence & Memory | Cases, observations, decisions, snapshots, provenance | Dated and immutable history |
| Connectors | WP, Woo, GA4, GSC, Plesk, SSH, IMAP, WhatsApp, Ringover | Read-only first |
| Execution | Staging tools, approved production named operations | Rollback and verification |
| Infrastructure | VPS, Plesk, database, queues, secrets, logs | Least privilege and resilience |

## 4. Complete Future Capability Catalogue

- **Multi-profile registry and switcher** — Create, edit, select and isolate independent
  business/site profiles. Profile ID, site identity, production/staging endpoints, locale,
  credentials, permissions, schedules, memory namespaces.
- **Environment truth model** — Prevent mixing production analytics with staging operational
  data. Every evidence item carries profile, source, environment, captured_at, validity
  window and authority rank.
- **Site map and content graph** — Complete understanding of menus, hubs, current/past
  events, languages and commercial state. Scheduled crawl, WP inventory, menu mapping,
  canonical graph, bilingual relationship mapping, diff history.
- **Investigation cases** — Investigations as first-class objects rather than transient
  chat. Case status, question, evidence, hypotheses, decisions, actions, approvals, outcome
  and follow-up date.
- **Decision ledger** — What was decided, by whom, why, with what evidence.
  Material/clarifying amendment type, approver, authority scope, effective date, cooldown.
- **Task and action registry** — Replace free-form execution with named, structured
  operations: action schema, preconditions, required approval, target environment, rollback,
  validation and audit trail.
- **Technical Inspector** — Inspect site structure, code, plugins, configuration, logs,
  cron, database, runtime and server. Read-only snapshots first; controlled staging tests;
  later reversible repairs.
- **Technical Memory** — Track drift over time rather than inventory only. Snapshot, hash,
  metrics, predecessor diff, date window, provenance and severity.
- **Backup Guardian** — Verify backup existence, integrity, off-site copies, retention and
  restore readiness. Plesk, Duplicator, Google Drive and restore-test evidence.
- **Communication Intelligence** — Unify email, WhatsApp and phone context around customer
  cases. Inbound evidence, thread summaries, commitments, confidence states and approved
  replies.
- **IONOS email connector** — Read and analyse business email without Gmail migration.
  IMAP read-only first; SMTP only for approved sending later.
- **WhatsApp Business connector** — Official API, inbound first, draft-only replies,
  template controls, consent and retention.
- **Voice connector / Ringover** — Transcribe and summarize phone calls, attach to cases.
  Temporary test number first; port the existing number only after validation.
- **Availability read API** — Non-PII, profile-scoped Woo Bookings resource calendar and
  conflict explanations.
- **Reservation summary and soft holds** — Internal non-binding holds, expiry, source,
  human confirmation and conflict checks.
- **Approved booking creation** — Named operation, payment status handling, customer
  confirmation and rollback/cancellation path. Only after mature validation.
- **AI Organization** — Admins configure providers/models/roles/teams: provider, model,
  role, team, instance and execution policy separation.
- **AI FinOps** — Token classes, cache, pricing versions, cost by profile/role/model/run,
  quality and latency.
- **Prompt caching telemetry** — Creation/read counters, cache-aware costing, stable-prefix
  validation, dashboard metrics.
- **Plesk/API integration** — Dedicated service account, scoped API tokens, named
  operations, no root by default.
- **SSH/WP-CLI inspection** — Allowlisted commands, read-only wrappers, command logs,
  timeouts, redaction.
- **Dashboard operating console** — Cases, reports, approvals and actions out of Bash.
  Structured UI before free chat, clear environment banner, audit trail and role controls.
- **Scheduled reports and condition alerts** — Per-profile schedules, deduplication,
  severity thresholds and escalation.

## 5. Multi-Profile and Environment Isolation

Profile isolation is the highest-risk architectural requirement. A multi-site dashboard
without hard isolation can create cross-environment contamination: a draft for one site,
evidence from another, or a production action executed against staging credentials.

**Minimum profile object:** Profile ID, display name, business identity, domains and
locales; production and staging environment records with explicit labels and visual banners;
connector credentials and scopes; profile-specific memory, evidence, cases, decisions,
reports, logs and scheduled jobs; profile-specific permissions and action policies;
profile-specific site map, content graph and commercial-state rules.

**Isolation controls:**

- Every database row containing operational data must include profile_id.
- Every connector call must require an explicit profile and environment; no silent defaults
  for write operations.
- Worker queues and scheduled jobs must carry profile_id and environment_id.
- Secrets stored under profile-specific identifiers, never injected globally.
- Dashboard profile switching invalidates cached evidence and visibly changes the banner.
- Cross-profile linking must be explicit, rare and logged (e.g. a deliberate relationship
  between Tossa Cycling and Tour de Girona).

## 6. AI Organization: Providers, Models, Roles, Teams and Policies

| Object | Owns | Must not own | Examples |
|---|---|---|---|
| Provider | Credentials, account health, budgets, endpoints | Business responsibility | Anthropic, OpenAI, Google, Moonshot |
| Model | Capabilities, context, pricing, tool support | Permissions | Claude Sonnet, GPT, Gemini, Kimi |
| Role | Mission, permissions, preferred/fallback model | API key | Boss, Coordinator, SEO, Inspector |
| Team | Hierarchy and collaborating roles | Raw provider credentials | Weekly Report Team |
| Agent instance | One execution of a role | Permanent authority | SEO-2 for one parallel run |
| Execution policy | Sequential, parallel, consensus, escalation | Business evidence | 2 reviewers + adjudicator |

**Admin controls:** multiple provider accounts/keys with health checks, spend caps,
enable/disable; multiple models per provider with capability metadata and pricing versions;
preferred model + ordered fallbacks per role; agent quantity and concurrency by role and
workflow; delegation rules between roles; **tool permissions attach to roles, never to
models**; cost/latency/quality thresholds per workflow; manual override preserving the
original policy and audit reason.

**Recommended initial hierarchy:** Boss / Executive Coordinator → Growth Coordinator →
SEO, Analytics, Content, Technical Inspector, Communication Manager, Backup Guardian.
Specialists can delegate to narrow sub-agents (Database Inspector, Booking Analyst) but
cannot expand their own permissions.

## 7. Technical Inspector and Technical Memory

Introduce as soon as read-only foundations are stable; generalizes the snapshot-and-diff
pattern already established for site structure and code hashes.

**Inspection domains:** WP core/plugin/theme inventory and update drift; custom snippets,
functions.php, mu-plugins, code registry with hashes; WooCommerce/Bookings configuration
relevant to availability and checkout; scheduled tasks (WP cron, Action Scheduler, system
cron); application/PHP/web-server logs and repeated exceptions; database health (size,
indexes, autoload, growth, orphaned metadata, slow queries); runtime (PHP version, limits,
OPcache, workers, extensions, service health); server (disk, inodes, backups, certificates,
DNS, package updates, resource pressure); security posture (exposed endpoints, weak
permissions, suspicious changes) — without becoming an autonomous security scanner initially.

**Technical Memory record:** observation ID, profile, environment; inspector version and
collection method; snapshot timestamp and predecessor; raw evidence reference plus
normalized metrics; diff summary and first/last-observed dates; severity, confidence,
business impact; associated case, decision, action and validation result.

**Progression:** read-only inventory → automated drift alerts and case creation →
controlled staging diagnostics → suggested repairs with rollback plans → approved named
repairs on staging → only later: narrow, reversible production repairs with post-action
verification.

## 8. Backup Guardian

Not merely "a backup job ran" — verify that **recovery is plausible**.

- Inventory Plesk backup chains, Duplicator packages, off-site Google Drive copies.
- Check latest successful backup timestamps against policy.
- Validate retention: local, off-site, full/incremental chain depth.
- Detect abnormal size changes, missing parts, broken chains, stalled uploads.
- Verify checksums or archive readability where technically possible.
- Track disk space; forecast when retention could fill local or Drive storage.
- Require periodic restore tests to staging, recording duration, errors, validation.
- Alert only when policy is breached or recoverability confidence drops.

**Example rule set:** daily Plesk incremental backups with defined full-chain retention;
Duplicator on a separate schedule; limited local retention; more off-site retention; **no
successful backup is considered proven until a scheduled staging restore test has passed.**

## 9. Communication Intelligence: Email, WhatsApp and Voice

One of the highest-value commercial additions (primary evidence of customer intent often
exists outside WooCommerce) and the highest privacy/reputation exposure.

### 9.1 IONOS email

IMAP read-only ingestion; SMTP outbound only. Start with a dedicated business mailbox or
tightly scoped folders, not unrestricted personal mail. Classify enquiries, bookings,
workshop jobs, events, suppliers, complaints, spam. Detect unanswered/overdue enquiries.
Extract dates, bike types, sizes, quantities, delivery requirements, stated commitments.
Link threads to cases and WooCommerce records. Generate reply drafts; human approval
before SMTP sending. Retain original-message references; store only necessary structured
facts in long-term memory.

### 9.2 WhatsApp Business

Official WhatsApp Business Platform/API only; no browser scraping or unofficial automation.
Inbound ingestion and case linking first; draft replies for approval; later narrowly
defined approved templates (payment reminders, pickup confirmation, height request, ready
notification). **Never autonomously confirm availability, discounts, refunds, complaints
or exceptions.** Explicit customer consent, retention rules, template governance, delivery
audit.

### 9.3 Voice / Ringover

Evaluate Ringover first, keeping a provider-neutral Voice Connector. Test with a temporary
number before porting the existing Tossa Cycling business number. Validate call quality,
mobile workflow, Spanish/multilingual transcription, summaries, API/webhook access, cost.
Prefer transcript without long-term audio retention where legally and operationally
acceptable. Extract tasks and proposed facts, but never convert ambiguous call language
into a confirmed booking automatically.

### Unified communication evidence model

| Field | Purpose | Example |
|---|---|---|
| channel | Source channel | email / WhatsApp / phone |
| thread_id | Preserves conversation grouping | provider reference |
| message/call timestamp | Timeline and SLA | 2026-09-03 10:14 |
| extracted fact | Structured operational claim | 2 road bikes, sizes M/L |
| status | Prevents false confirmation | requested / proposed / confirmed / paid |
| confidence | Controls automation | 0.84 |
| source reference | Audit and review | message/call ID |
| linked case/booking | Unified customer timeline | CASE-... / order ... |

## 10. Booking, Availability and Customer Operations

Booking capabilities mature in small steps. The agent must never infer operational truth
from analytics or from an unconfirmed conversation.

- **Availability read:** non-PII resource calendars, sizes, conflicts, booking rules;
  results identify environment and freshness.
- **Reservation summary:** Woo records + communication evidence in a human-readable
  operational view.
- **Internal soft hold:** non-binding hold with expiry, source, staff owner, explicit
  conflict behavior.
- **Approved booking creation:** named operation with customer identity, product/resource,
  dates, price, payment status, confirmation message.
- **Approved modification/cancellation:** reason, policy checks, customer impact,
  rollback/compensating action.

## 11. AI Operations / FinOps Dashboard

Build early — multiple providers, models, roles are coming. Purpose is model allocation
and quality economics, not just billing display.

**Metrics:** spend by provider/profile/team/role/model/connector/workflow/run; input,
output, cache-creation, cache-read tokens; cache hit rate, savings estimate, stable-prefix
performance; runtime, retries, failure rate, timeout rate; quality score, human acceptance
rate, correction rate, escalation rate; cost per report/investigation/draft/successful
action/resolved case; budget utilization, forecast, anomaly detection.

**Pricing registry:** provider and model identifier; input/output/cache-creation/cache-read
prices; currency, effective date, source; versioned price record referenced by every run;
historical costs remain tied to the price effective at execution — recalculation must be
explicit.

**Self-optimization policy:** the platform may recommend a cheaper or faster model only
when quality and governance thresholds are met. Automatic reassignment begins as advisory,
then requires approval, and only later becomes policy-driven for low-risk roles.

**Critical known requirement:** cost estimation must be cache-aware. Anthropic cache
creation and cache read token classes cannot be omitted from cost_usd. The existing ledger
detail field can store cache counters without schema changes, but the cost engine needs a
provider-aware pricing model. *(= FINOPS-001 in this repo.)*

## 12. Dashboard, Cases, Decisions and Human Approval

Profile selector with prominent site and environment identity. Home dashboard: system
health, scheduled reports, open cases, backup status, communication backlog, budget.
Cases: evidence, hypotheses, discussions, recommended actions, outcomes. Decisions:
approved/rejected/deferred, authority scope, evidence, amendment class. Actions: named
operation, target, dry run, approval, execution, rollback, verification. AI organization:
providers, models, roles, teams, budgets, permissions. Technical Inspector: current state,
drift timeline, severity. Communications: unanswered threads, customer timelines, drafts
awaiting approval. FinOps: costs, tokens, cache, allocation recommendations. Audit log:
immutable history of human and agent operations.

**Interface rule — structured actions before free chat:** the dashboard makes common
operations explicit and typed. Free chat can explain, investigate and prepare actions, but
must not be the only way to execute sensitive operations.

## 13. Plesk, SSH, WordPress and Infrastructure Automation

- Dedicated Linux service account (not root) for the orchestrator.
- Plesk API credentials with the narrowest available scope.
- WP-CLI and shell commands wrapped in named allowlisted operations.
- Read commands separated from write commands.
- Target profile and environment required on every call.
- Capture command, arguments, stdout/stderr, exit code, duration, operator/agent.
- Timeouts, output size limits, sensitive-data redaction.
- Write operations on staging first; production requires explicit approval and rollback.
- Git branches, review, merge gates and deployment protocols for code changes.

## 14. Data Architecture and Evidence Model

Reports, memory and actions derive from evidence objects, not untraceable model context.

| Object | Core fields | Mutability | Purpose |
|---|---|---|---|
| Evidence | profile, environment, source, captured_at, payload/ref, confidence | Append-only | Ground truth |
| Snapshot | inspector, scope, metrics, predecessor | Append-only | Technical memory |
| Case | question, status, owner, evidence links | Controlled updates | Investigation lifecycle |
| Decision | choice, rationale, authority, approver | Append amendments | Governance |
| Action | operation, target, preconditions, approval | State machine | Safe execution |
| Run | role, model, tokens, cost, latency, output | Append-only | AI operations |
| Memory fact | fact, source, validity, confidence | Versioned | Reusable context |

**Memory promotion rules:** raw communications and logs are not automatically permanent
memory; only stable, useful facts are promoted, with source and validity; a fact can be
superseded but not silently overwritten; sensitive personal data minimized and subject to
retention/deletion rules; profile and environment mandatory on every memory fact.

## 15. Security, Privacy, Legal and Governance Controls

- Secrets encrypted at rest; never exposed in prompts or logs.
- Least-privilege credentials per connector and profile; read-only preferred.
- GDPR purpose limitation, data minimization, retention, access/deletion procedures for
  communication data.
- Human approval for outbound customer communication during initial phases.
- **No emotion, personality, health, nationality or accent inference from voice.**
- Production action authorization separated from action execution.
- Material governance changes require full approval and cooling-off; clarifying changes
  require approval and statement of no authority change.
- Every action records actor, model/role, time, evidence, target, result.
- Emergency stop and connector disable controls available to the owner.

## 16. Phased Delivery Plan

| Phase | Scope | Exit condition |
|---|---|---|
| 0 – Foundation | Profile registry, environment identity, evidence/case/decision stores, action registry, secrets, audit log | No cross-profile leakage; all writes explicit |
| 1 – Read-only intelligence | Site map, Technical Inspector snapshots, Backup Guardian inventory, FinOps telemetry, production analytics reads | Stable scheduled runs and correct provenance |
| 2 – Operational dashboard | Cases, approvals, actions, reports, role configuration, profile-scoped schedules | Bash no longer required for routine validation |
| 3 – Communication ingestion | IONOS IMAP, unanswered email, drafts; then WhatsApp inbound/drafts | Privacy controls and zero unauthorized sends |
| 4 – Voice intelligence | Ringover test number, transcription, summaries, case linking; later number port | Call quality and transcript accuracy accepted |
| 5 – Booking operations | Availability read, summaries, soft holds, approved booking creation | No double-booking and complete audit |
| 6 – Controlled technical actions | Staging repairs, approved production named operations | Rollback and verification proven |
| 7 – Bounded autonomy | Low-risk auto-routing, template messages, model self-optimization | Quality and governance thresholds sustained |

## 17. Acceptance Gates and Validation

- Every capability has a written verification protocol before deployment.
- Feature branches stay isolated until the applicable release gate.
- Staging deploy confirms dependency versions, service restart, runtime identity.
- At least one positive and one negative/invalid-path test.
- Scheduled behavior requires consecutive clean runs before promotion.
- Production reads and production writes have separate gates.
- A successful API response is not enough; business outcome and persistence must be
  verified.
- Post-action checks confirm the intended change and absence of collateral damage.

**Prompt caching example gate:** run 1: cache_creation_tokens > 0; run 2 within one hour:
cache_read_tokens > 0; do NOT require cache_creation_tokens == 0 on run 2; compare
pair-wise cost using cache counters and versioned list pricing until cost_usd is
cache-aware.

## 18. Risks, Failure Modes and Mitigations

| Risk | What could go wrong | Impact | Mitigation |
|---|---|---|---|
| Cross-profile contamination | Wrong site data or action | Severe | Mandatory profile/environment IDs, isolated secrets |
| False customer commitment | Proposal treated as confirmed | Severe | Status hierarchy and human approval |
| Autonomous wrong reply | Pricing/availability mistake | Severe | Draft-only first, templates later |
| Production damage | Agent changes live site incorrectly | Severe | Named operations, staging, backup, rollback |
| Backup false confidence | Backup exists but cannot restore | Severe | Periodic staging restore tests |
| Provider lock-in | Workflow tied to one model | High | Provider/model/role separation |
| Cost under-reporting | Bad FinOps decisions | Medium | Versioned pricing and cache-aware costing |
| Credential exposure | Mailbox/server compromise | Severe | Vault, least privilege, redaction, rotation |
| Data retention excess | GDPR exposure | High | Retention policy and memory promotion rules |
| Dashboard complexity | Staff stop using system | Medium | Structured flows, progressive disclosure |
| Alert fatigue | Important issues ignored | Medium | Severity thresholds, notify-on-exception |
| Transcription errors | Wrong dates/sizes/prices | High | Confidence, source review, no automatic confirmation |

## 19. Recommended Priority Order

| # | Action | Why |
|---|---|---|
| 1 | Finish current validation gate; preserve frozen-main discipline | Do not destabilize the working foundation |
| 2 | Complete profile isolation, evidence, case, decision, action foundations | Everything else depends on clean context and auditability |
| 3 | Build Technical Inspector snapshots and Backup Guardian | Highest resilience value, limited customer-facing risk |
| 4 | Build AI FinOps and provider/model/role admin | Needed before multi-provider scaling; low operational risk |
| 5 | Build IONOS email read-only intelligence + unanswered-enquiry dashboard | Likely immediate sales impact |
| 6 | Add WhatsApp Business inbound and draft-only workflows | High value; greater privacy and platform complexity |
| 7 | Pilot Ringover with a temporary number | Validate before touching the established business number |
| 8 | Add availability read and reservation summaries | Improves response accuracy without booking writes |
| 9 | Add soft holds and approved booking operations | Only after availability truth is reliable |
| 10 | Introduce controlled staging repairs and narrow production actions | Requires mature rollback and verification |
| 11 | Consider bounded autonomous communication and self-allocation | Last, after long shadow operation and measured quality |

## Final Recommendation (verbatim)

In the owner's position, I would resist the temptation to make the system look autonomous
too early. I would build a trusted evidence and control system first, then add intelligence
by channel, and only afterward add execution authority. The near-term winning combination
is: strict profile isolation, Technical Inspector, Backup Guardian, AI FinOps, and
read-only communication intelligence. That combination protects the website, protects
recoverability, reduces missed sales, and creates the data needed for later automation
without putting the Tossa Cycling reputation at unnecessary risk.

*End of Master Roadmap.*
