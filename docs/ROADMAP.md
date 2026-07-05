# TC AI Growth — Roadmap & Operating Strategy

Living document. The agent is becoming a business operating system, not a bag of AI features. This
file records where we are, the principles we build by, and the sequenced next steps. Update it as
phases land (it is also the seed of the "Operating Strategy" the coordinator will eventually read).

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

## Longest-lead external items (start early)

- Google Ads developer token + Meta app review (needed before Ads analysis is real).
- Decide production write path: resync staging with production, or switch the connector to production
  read-only first — before any Phase 3 write capability.
