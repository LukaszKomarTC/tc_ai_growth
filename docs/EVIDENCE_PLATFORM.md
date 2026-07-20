# Evidence Platform v1.0 — specification

**Status:** SPEC 2026-07-20, written during the Release 0.3 freeze (docs branch, merges
post-gate). This is the designated design document for the platform's next architectural
layer. It subsumes audit work packages **WP-A** (store v3 evidence-grade persistence) and
**WP-B** (runtime evidence/traceability), and implements amendments 1–2 and 6 of the
Master Roadmap review (`docs/reviews/FUTURE_FUNCTIONS_ROADMAP_REVIEW.md`).

**Principle:** the platform's identity is an operational knowledge system that happens to
use AI. This spec is that identity's data layer: everything observed is snapshotted,
diffed, timestamped, provenance-linked, and queryable over time; everything acted on is
named, approved, executed, and verified as separate recorded events.

## Non-goals (binding)

Evidence Platform v1.0 does **NOT** introduce: multi-profile execution, connector
credential migration, customer communication ingestion, or production writes. It also does
not build dashboards, admin UIs, or the AI Organization. Anything in this spec that
touches those areas is a *reserved shape* (interface + constraints recorded now, built
when its release arrives).

## 1. Store topology (settles Conflict 1 / amendment 1)

**Decision: dedicated store per (profile, environment); NO shared database.**

- Each profile-environment pair owns one SQLite store file (today:
  `data/tc_growth_<site>.db` — kept). A missing WHERE clause can never leak across
  profiles because cross-profile joins are impossible by construction.
- The **shared layer is source-controlled configuration, not a database**:
  - **Profile Registry** — a declarative in-repo file (`profiles/registry.yaml`) listing
    every profile: id, display label, business identity, domains, locales, environment
    records (production + staging: base URL, store path, environment label, staging
    lifecycle mode), secrets *reference* (never values — credentials stay in
    `profiles/*.env` and `orchestrator/secrets/`, mode 600, gitignored), enabled flag.
  - **Pricing Registry** (FINOPS-001) — versioned in-repo data: provider → model →
    per-token-class rates (input / output / cache-creation / cache-read), currency,
    `version` id, `effective_date`, source. Git history IS the version audit trail.
- Runs reference `pricing_version` (string) so historical `cost_usd` stays tied to the
  price in force at execution; recalculation under a newer schedule must be explicit and
  produces a new derived value, never an overwrite.
- Rationale for files-over-shared-DB: per-profile backup/export/legal deletion for free;
  "never copy staging history into the production store" enforced by file boundaries;
  registry changes are code-reviewed like any other governance change.

## 2. Environment truth model

Every evidence-bearing row carries `environment` (production | staging) alongside its
existing site scoping, plus `captured_at` (already present) and, where meaningful, a
`validity_note` (e.g. SITE_PROFILE rule #7: staging rendered SEO output is frozen at clone
time). **Authority ranking** (generalizes the WP-06 lifecycle evidence ladder, higher
wins):

1. approved rule (human-approved, provenance-carrying)
2. direct runtime read (live system observed)
3. structured field (declared data: postmeta, config)
4. content-derived (parsed from slugs/titles/text)
5. inference (model judgment; must be labeled low-confidence)

Conflicting evidence at the same rank → `unknown`, both cited — never silent preference.

## 3. Evidence objects and mutability classes

The existing tables are kept and classified; new columns are additive only.

| Object | Class | Rules |
|---|---|---|
| Evidence/Snapshot (site_snapshots, future inspector snapshots) | **Append-only** | INSERT + retention pruning only; no UPDATE path exists in code |
| Run | **Append-only** | one row per execution; enriched at write time, never after |
| Case | **Controlled updates** | column updates via allowlist (`_CASE_UPDATABLE`) minus `body`; narrative ONLY via journal append (fixes R11) |
| Decision | **Append amendments** | status transitions + outcome events; amendments recorded, never rewritten |
| Action definition | **Code** (Action Registry) | versioned by git; not in the DB |
| Action execution | **State machine** (reserved, 1.1) | see §5 |
| Memory fact | **Versioned** (reserved, 2.0) | supersede, never overwrite (Memory 2.0 spec) |

**Transaction boundaries (fixes R10):** any operation that changes state AND appends
journal evidence does both in ONE transaction — a state change without its evidence, or
evidence without its state change, must be impossible. Update-style writes check rowcount
and raise on 0 (fixes R23).

**Forward-schema rejection (fixes R19):** a store whose `stored_version` is GREATER than
the code's `SCHEMA_VERSION` fails closed with a clear error — an old deploy must never
write into a newer store.

**Failure states (fixes R21, generalizes the site-intel pattern):** every context block
and evidence reader has three explicit states — content with identity (id + timestamp) /
"unavailable: <reason>, claims prohibited" / "failed to load: <reason>, claims
prohibited". Silent empty-string degradation is a defect class, banned platform-wide.
Persistence degradation never kills a run; it marks the run's output evidence-degraded.

## 4. Run identity and provenance (WP-B)

Every run row gains (additive columns at implementation):

- `commit_id` — `git rev-parse HEAD` of the deployed tree + `last_deploy.json` reference
  (closes R13's deploy-evidence overclaim: "deployed" means *this* commit, verified).
- `pricing_version` — from the Pricing Registry (§1).
- cache counters — already landing via `runs.detail` (feature/prompt-caching); promoted to
  columns here.
- `trace` — the tool-call transcript (tool, ok, durations; **metadata only, never
  payloads** — R20 redaction discipline). Closes R7a/R15: `persist_run` stops discarding
  `result.tool_calls`, and the case_read observer script becomes unnecessary — the
  platform self-evidences.

## 5. Action Registry (amendment 6 substrate; skeleton built THIS WEEK)

**Definitions are code; executions are evidence.** Two halves, built at different times:

**5a. Definitions (`core/actions.py`, feature branch now).** A declarative catalogue of
the operations that genuinely exist — id, name, category, minimum phase, allowed
environments, approval class, tool/CLI binding, preconditions, `enforced_by`,
`rollback_description`, `verification_description`, enabled flag.

- **Registry entries describe reality, not roadmap intent** — an entry exists only if the
  operation is callable today, and consistency with the enforcement layer
  (`TOOL_MIN_PHASE`, `ALWAYS_ASK`) is asserted by tests, so the catalogue cannot drift
  from the code that actually gates dispatch.
- **Documentation is not enforcement.** Descriptive fields are named `*_description`
  precisely because they are documentation; the `enforced_by` field lists the code layers
  that actually enforce (phase gate, profile write cap, connector approval guard,
  ALWAYS_ASK confirmation). A field is renamed (`rollback_description` →
  `rollback_handler`) ONLY when a machine-executed handler exists.
- No dispatch changes, no DB table, no UI, no approval-workflow changes in the skeleton.

**5b. Executions (reserved — built as the Release 1.1 write-safety substrate).** An
`action_executions` table: action id, parameter hash, **content-bound approval reference**
(approval covers the exact content hash, closing R8's TOCTOU), executor, state machine
(proposed → approved → executing → verified | failed → compensated), verification outcome,
compensation record (closing R9). `publish_seo_draft` is the first operation migrated onto
it; every later write capability starts here instead of as a bare tool.

Capability (roadmap amendment 6) is extracted FROM this registry after real operations
compose in practice — it is the registry's v2, not a parallel object.

## 6. Staging lifecycle modes (amendment 2)

The Profile Registry's staging environment record carries `mode`:

- `developer` — normal build/test state.
- `validation` — a validation protocol is in flight; state is evidence, treat as frozen.
- `restore-test` — Backup Guardian may overwrite; nothing unrecoverable may live here.

Mode is data now, enforcement later: Backup Guardian's restore operation (when built)
refuses unless mode == `restore-test`, exactly as the phase gate refuses tools — same
pattern, new axis. Mode changes are logged decisions, not silent edits.

## 7. Communication evidence (reserved shape — gated on the owner's comms policy)

Recorded so the first IMAP build cannot improvise: **reference-not-copy** (amendment 4).
The communication system (mailbox / WhatsApp / telephony) remains the system of record;
the store holds channel, thread/message references, timestamps, minimized structured
facts, status (requested/proposed/confirmed/paid), confidence, linked case. Erasure =
delete facts + dead-reference pointers; the append-only class is preserved because
payloads were never copied in. **Nothing here is buildable until the communications
governance policy (amendment 3) is formally approved with cooldown.**

## 8. Dashboard contract

Read-only against the stores, enforced structurally: GET never creates a database (fixes
R16 — `_open_ctx_store` opens existing-only), all interpolated values escaped (fixes R17
stored XSS), event chronology uses the correct per-event timestamps (fixes R22). The
dashboard reads evidence; it never manufactures it.

## 9. Migration plan (all additive)

1. **v3 → v4 (first implementation batch, post-gate):** run columns (`commit_id`,
   `pricing_version`, cache counter columns, `trace`); rowcount checks; forward-schema
   rejection; journal transaction fix; `body` out of `_CASE_UPDATABLE`;
   `profiles/registry.yaml` + loader; pricing registry data + cache-aware `estimate_cost`
   (FINOPS-001).
2. **v4 → v5 (with Technical Inspector slice 1):** generalized inspector snapshot table
   (superset of site_snapshots' shape: inspector id, scope, metrics, predecessor ref).
3. **v5+ (Release 1.1):** `action_executions` (§5b) — schema lands WITH the write-safety
   feature that uses it, per the no-speculative-schema principle.

Each step ships with migration tests: old store opens, new columns nullable, forward
version refused.

## 10. Acceptance (v1.0 implementation, graded per batch)

- [ ] Profile Registry file + loader; orchestrator resolves site/store/environment through
      it; a profile absent from the registry cannot run.
- [ ] Runs carry commit identity, pricing version, cache counters, and a metadata-only
      trace; a scheduled run self-evidences its tool calls (case_read visible in the
      ledger without an observer script).
- [ ] Forward-schema store refused with a clear error (test).
- [ ] Journal append + state change atomic (crash-injection test).
- [ ] Zero-rowcount update raises (test).
- [ ] Every context block exhibits the three-state absence contract (tests per block).
- [ ] cost_usd cache-aware and pricing-version-stamped; the known-underestimate caveat in
      PROMPT_CACHING.md retired.
- [ ] Staging mode present in the registry and surfaced in reports' environment labels.
- [ ] Suite green throughout; every batch independently revertable.
