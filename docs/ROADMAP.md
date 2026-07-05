# TC AI Growth — Roadmap & Operating Strategy

Living document. The agent is becoming a business operating system, not a bag of AI features. This
file records where we are, the principles we build by, and the sequenced next steps. Update it as
phases land (it is also the seed of the "Operating Strategy" the coordinator will eventually read).

## Where we are (2026-07)

- **Phase 1 — autonomous loop: DONE.** read → reason → investigate → report → deliver, running on
  the VPS as a hardened non-root systemd timer (Mon 07:00 Europe/Madrid) via IONOS SMTP.
- **Phase 2 — persistence: core DONE (slices 1–3).**
  - SQLite store: `runs`, `cases`, `decisions` (+ `schema_version`). Structure in columns, narrative
    in a `body` text field.
  - Case #1 seeded = `INC-2026-02-01` (Merchant Center tobacco spam), resolved.
  - Token/cost captured per run (can't be backfilled).
  - **Memory-aware coordinator**: known cases injected into the task; the agent references a resolved
    case instead of re-raising it.

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

## Next steps (sequenced)

- **Slice 4 — Store repository interface.** Wrap the SQLite implementation as `SqliteStore` behind a
  `Store` protocol; callers hold a store object. Locks the seam above. Pure refactor, tests unchanged.
- **Slice 5 — the agent writes to memory.** Case-write tools (draft/propose only, human-confirmed for
  status changes): open a new case, append observations, update status/confidence, record a decision.
  Adds `opened_by`/`closed_by` and numeric confidence *with* this feature. Target behavior: a Monday
  line like *"INC-2026-02-01 · monitoring · no recurrence · confidence 0.82→0.96 · no action."*
- **Slice 6 — act on the live findings (read/draft-only).** Production-safe **SEO draft text** for the
  Spanish `/alquiler_bicicletas/` page + home canonical fix; **spam re-verification** `investigate`
  (day-by-day 90-day timeline to confirm decay). Fix the **conversion-tracking gap** (human task in WP)
  — the blocker for all ROI measurement.
- **Slice 7 — model policy.** Config map task-type → model (monitoring→Haiku, weekly→Sonnet,
  strategy→Opus); measure cost/quality before trusting the cheap tier.
- **Slice 8 — private web dashboard.** Thin, read-first view over the store (reports, cases, decisions,
  runs/costs, health). Isolated hosting + its own auth; approvals added only after the read side is
  trusted. Never a new write path into the booking system.
- **Slice 9 — new specialists.** Pricing, advanced SEO, reservations, workshop, inventory, forecasting —
  each inheriting memory, strategy, and prior decisions rather than starting cold.

## Longest-lead external items (start early)

- Google Ads developer token + Meta app review (needed before Ads analysis is real).
- Decide production write path: resync staging with production, or switch the connector to production
  read-only first — before any Phase 3 write capability.
