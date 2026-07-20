# WP-08 — Production DB Diagnostic Reader (technically read-only, PII-free)

**Status:** SPEC 2026-07-20 — owner decision: production read layer brought forward.
Supersedes the earlier "sanitized diagnostic replica only" position (record via decision,
see below). Build order: after WP-07. Merges after Release 0.3 signs off.

**Principle (to be added to VISION as a clarifying amendment):** *the agent may see broadly,
reason deeply, and verify independently; its ability to change anything remains narrow,
explicit and approved.* Corollary rule, encoded and tested: **personal data never enters
model context.**

## Enforcement layers (each independent; the tool is never the only guard)

1. **MySQL account** — dedicated user per database with `SELECT` privilege ONLY (created by
   owner in Plesk; grants verified by test that INSERT/UPDATE/DELETE/CREATE fail). The
   credential lives in `orchestrator/secrets/` (mode 600); the model never sees it.
2. **Sanitized views** for anything touching people or money — schema `tc_diag`:
   - `v_orders`: date, status, gross/net totals, currency, line items (product, qty),
     attribution meta (source/medium/referrer). NO name, email, phone, address, tokens,
     customer notes.
   - `v_bookings`: booking dates, resource/product, party size, status. NO customer fields.
   - `v_options_safe`: allowlisted `option_name`s only (active_plugins, template, blog
     settings, cron) — `options` at large stores API keys and credentials and is NEVER
     broadly readable.
3. **Raw-table allowlist** (structure, not people): `posts`, `terms`/`term_taxonomy`/
   `term_relationships`, `yoast_indexable`, Action Scheduler status columns, and `postmeta`
   **with sensitive-key exclusion enforced in the tool** — `_billing_%`, `_shipping_%`,
   `%token%`, `%secret%`, `%api_key%`, `%session%`, `_stripe%`, `%password%`. (Order PII
   lives in postmeta — the "SEO fields" table is the trap.)
4. **Query governor (the tool):** single statement; SELECT/EXPLAIN only (parsed, not
   regexed); LIMIT injected/capped (200 rows); response size cap; 5 s execution timeout
   (`MAX_EXECUTION_TIME` hint — the DB shares the box with the live shop); profile-bound
   DSN (staging tool cannot reach production DB and vice versa); every query + rowcount
   audit-logged. **Query-shape controls (reviewer additions, adopted 2026-07-20):** no
   `SELECT *` (explicit column lists only); `EXPLAIN` cost pre-check for free-form queries
   — deny unbounded joins over commerce tables and full scans beyond a scanned-row budget;
   concurrency limit of ONE diagnostic query per profile at a time. The timeout protects
   checkout after a query starts; shape controls stop it becoming expensive at all.
5. **Result screen (defense in depth):** returned column names/values screened for
   email/phone/name-shaped data; matches redact the column and flag the query in the log.
   Views (layer 2) are the PRIMARY privacy mechanism; this screen catches mistakes — it is
   never the main control.
6. **Audit hygiene:** logs record actor, profile, normalized query fingerprint, tables
   touched, row count, duration, and outcome — NEVER full result payloads. The audit trail
   must not become the PII leak it exists to prevent.

## Owner one-time setup

Plesk → Databases → add user `tc_diag_ro` with SELECT-only on the production DB; run the
repo-reviewed `scripts/wp08_views.sql` to create `tc_diag` views; store the credential per
SETUP.md. Same pattern for staging (separate user).

## Decision to record (CLI, owner)

```bash
tc-growth decision-add "Production read layer brought forward: Site Intelligence, source reader, and DB diagnostic reader run against production with technical read-only enforcement (MySQL SELECT-only user, sanitized PII-free views, path-scoped source reads excluding secrets). Supersedes the replica-only approach. Personal data never enters model context. Production writes remain release-gated (1.0 shadow, 1.1 drafts)." "Owner + reviewer convergence 2026-07-20: diagnosis must happen against reality; staging misleads (clone-frozen indexables, invalid revenue). Visibility is not authority."
```

## Acceptance

- [ ] Write statements fail at the MySQL layer (test against the real grant, not a mock).
- [ ] Views return zero PII columns (asserted against live schema).
- [ ] Governor rejects multi-statement, non-SELECT, LIMIT-less full scans over cap; timeout
      proven with a deliberate slow query on staging.
- [ ] Sensitive postmeta keys unreachable through any path; result screen catches a seeded
      email in a test table.
- [ ] Every query visible in the audit log with profile + rowcount; suite green.
- [ ] Live proof: the 2026-07-20 indexable diagnosis re-run end-to-end by the agent alone
      (stored meta vs indexable row, one turn, zero human relays).
