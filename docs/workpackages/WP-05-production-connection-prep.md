# WP-05 — Production connection prep (dormant read-only environment)

**Status:** EXECUTION IN PROGRESS — infrastructure complete and verified (see Execution record
at the bottom); remaining: five seed decisions + completion decision in the production store.
**Goal:** `tossacycling-production` exists as a **dormant, read-only, isolated** environment so
Release 1.0 (production shadow mode) activation is a one-line timer change, not a build.

## Identifier scheme (established NOW, before anything connects)

```
property_id:     tossacycling
environment_id:  production | staging
profile_id:      tossacycling-production · tossacycling-staging
```

Profiles are named `<property>-<environment>` from here on (examples renamed in repo).
Scheduled units must always name their profile explicitly — an automated run may never fall
back to the generic `.env`. (Migration of the current staging profile/scheduler to the new
name happens at Release 1.0 activation, not now.)

## Human steps (production WordPress)

1. **Install the connector plugin** (same code as staging — includes the write kill-switch).
2. **In production `wp-config.php`, BEFORE activation, add:**
   ```php
   define( 'TC_GROWTH_DISABLE_WRITES', true );
   ```
   With this constant the write routes (create-seo-draft, create-draft-asset,
   create-product-revision, publish-seo-draft, log-agent-action) are **never registered** —
   read-only on the server side, independent of any platform-side setting or credential leak.
3. **Create a dedicated WP user** `tc-agent-prod` (lowest role that satisfies the read
   endpoints; NOT the staging user), and a **fresh application password** for it.
4. **Generate a NEW HMAC signing key** (never reuse staging's):
   `openssl rand -hex 32`

## Platform steps (VPS, as tcgrowth)

5. `cp profiles/tossacycling-production.env.example profiles/tossacycling-production.env`
   and fill in:
   ```
   TC_SITE_NAME=Tossa Cycling
   TC_ENV_KIND=production
   TC_ALLOW_WRITES=false
   TC_WP_BASE_URL=https://tossacycling.com
   TC_DB_PATH=data/tc_growth-tossacycling-production.db   # separate store — never staging's
   # + the new WP credentials and signing key; GA4/GSC creds may reference the same
   #   production data sources already in use (they were always production).
   ```
   `chmod 600` the file.
6. **Memory seed (reviewed copy, provenance-marked — never the staging run history):**
   after `db-init --site tossacycling-production`, re-create by hand (or via CLI) the
   policy decisions and active cases with an origin note "migrated from tossacycling-staging
   store 2026-07-XX": D#2 (410 spam), D#4 (qTranslate tags), D#5 (Yoast title), D#6 (noindex
   order pages), D#7 (staging Woo ≠ production evidence — REVIEW its wording at Release 1.0:
   the production profile's connector IS production), plus cases INC-2026-02-01 and
   TRK-20260706-050158 (current status + confidence, one-line origin note each).

## Activation tests (ALL must pass; profile stays dormant regardless until 0.3 closes)

- [ ] Hostname identity: connector site-map returns tossacycling.com URLs (not staging's)
- [ ] GA4/GSC identities match the configured property
- [ ] Production credentials ≠ staging credentials (user, app password, HMAC key)
- [ ] Production store path ≠ staging store path; `cases` list shows ONLY the seeded set
- [ ] `TC_ALLOW_WRITES=false` in the profile (platform-side cap)
- [ ] **Write attempt rejected TWICE**: (a) platform side — `draft-test` refuses at the
      gate; (b) server side — a signed POST to `/tc-growth/v1/create-seo-draft` returns
      **404 (route not registered)** thanks to TC_GROWTH_DISABLE_WRITES
- [ ] Report header shows `Tossa Cycling · PRODUCTION` (red banner on dashboard)
- [ ] No customer PII in ordinary read endpoints (spot-check pages/products/site-map;
      orders-attribution returns aggregates only)
- [ ] No scheduled unit references this profile yet (`systemctl list-timers`)
- [ ] Smoke test: `tc-growth --site tossacycling-production smoke`

## Fail-closed rules (these are errors, never warnings)

Unknown profile name → hard exit (already implemented). Cross-property case visibility,
credential reuse across environments, a scheduler without an explicit profile, or a banner
that disagrees with the connector hostname → treat as incidents, stop, investigate.

## Explicitly NOT in this work package

- No scheduling against production (Release 1.0 gate decision).
- No draft creation on production (Release 1.1 gate + constitutional path for anything more).
- No dashboard profile switcher (Operations Console scope; the control plane = the console's
  property/environment selector + registry, not a separate build).
- No Tour de Girona property yet (add as a SECOND property only after the control-plane
  pattern is proven on one).

## Record-keeping after execution

```bash
tc-growth decision-add "tossacycling-production connected as dormant read-only environment: separate credentials/HMAC/store, server-side write kill-switch (TC_GROWTH_DISABLE_WRITES), activation tests passed, NOT scheduled until Release 0.3 closes."
```

---

## Execution record (2026-07-13)

Executed across two sessions: VPS-side infrastructure by Claude Code on the VPS (per
`WP05_CLAUDE_CODE_HANDOFF.md`); repository verification, external checks, and this record by
the repo session (which has no VPS access by design).

### Completed and verified

| Criterion | Evidence |
|---|---|
| Connector installed + active on production | v0.1.0, home + REST 200 before/after (VPS session) |
| `TC_GROWTH_DISABLE_WRITES=true` in wp-config | PHP lint clean; wp-config backups taken (VPS session) |
| **Write routes NOT registered (server-side)** | **Externally re-verified from an independent network**: POST `create-seo-draft` and `publish-seo-draft` → `404 rest_no_route`; read route `site-map` → `401 tc_growth_forbidden` (registered, auth-guarded); namespace `tc-growth/v1` present |
| Dedicated identity | `tc-agent-prod` (Contributor) + own application password + own HMAC key; secrets in `orchestrator/secrets/tossacycling-production-*`, tcgrowth:tcgrowth 600; values never printed |
| Profile | `profiles/tossacycling-production.env` (600): `TC_ENV_KIND=production`, `TC_ALLOW_WRITES=false`, prod hostname, GA4 256544830, GSC sc-domain:tossacycling.com |
| Separate store | `data/tc_growth-tossacycling-production.db` (distinct path/inode from staging; pre-seed backup exists) |
| Platform gate | `wp_list` allowed at READ_ONLY; draft/publish tools denied via write cap (VPS session) |
| Signed write attempts | all five endpoints → 404 rest_no_route (VPS session; matches external check) |
| PII spot-check | site-map/pages/products/orders-attribution: no customer PII (VPS session) |
| Scheduler | `tc-weekly-report.timer` untouched; nothing references tossacycling-production |
| Memory seed (cases) | exactly 2 reviewed cases migrated with origin notes: INC-2026-02-01, TRK-20260706-050158 — no staging run history |
| **Banner identity** | unit test added (`test_dashboard.py::test_production_banner_identity_is_red_and_read_only`): "Tossa Cycling · PRODUCTION" on red `#b32d2e` + "READ-ONLY PROFILE"; staging renders amber |
| No secrets in repo/logs | this record contains references only |

### Remaining — run on the VPS as tcgrowth (paste-ready)

```bash
cd /opt/tc_ai_growth/app/orchestrator
P="/opt/tc_ai_growth/app/.venv/bin/python -m tc_growth.cli --site tossacycling-production"

# 0) Pre-write verification: expect exactly 2 cases, 0 decisions, 0 runs
sudo -u tcgrowth $P cases; sudo -u tcgrowth $P decisions; sudo -u tcgrowth $P runs

# 1) Five reviewed policy decisions (texts reviewed 2026-07-13; origin-marked)
sudo -u tcgrowth $P decision-add "Origin D#2 — Serve 410 for verified tobacco/vape spam URL patterns and submit targeted GSC removals" "Reviewed 2026-07-13. Confirm the affected URL pattern and live serving behavior before implementation. Spam URLs must return 410 and must never redirect to legitimate content. Current state: approved; execution not yet verified. Origin: staging decision D#2; reviewed summary only; no staging run history copied." "INC-2026-02-01"
sudo -u tcgrowth $P decision-add "Origin D#4 — Preserve qTranslate XT ES/EN language blocks in the same WordPress post" "Reviewed 2026-07-13. Multilingual ES/EN content is stored with [:es]...[:en]...[:] tags in one post. Preserve all tags, update both language blocks in parallel, optimise each language independently, never replace a multilingual field with an untagged single-language value, and do not assume WPML or Polylang separate posts. Origin: staging decision D#4; reviewed summary only; no staging run history copied."
sudo -u tcgrowth $P decision-add "Origin D#5 — Do not add a manual Tossa Cycling suffix to Yoast SEO titles" "Reviewed 2026-07-13. Yoast appends the configured site title automatically, so drafted SEO titles must not include a duplicate brand suffix such as \"| Tossa Cycling\". SEO meta descriptions take effect through the controlled connector approval flow. Origin: staging decision D#5; reviewed summary only; no staging run history copied."
sudo -u tcgrowth $P decision-add "Origin D#6 — Apply noindex protection to order-received and order-pay URL patterns" "Reviewed 2026-07-13. Order confirmation and payment URLs must not be indexed. Confirm production implementation for /pedido/order-received/ and /pedido/order-pay/ patterns. Current state: approved; implementation not yet verified. Origin: staging decision D#6; reviewed summary only; no staging run history copied." "TRK-20260706-050158"
sudo -u tcgrowth $P decision-add "Origin D#7 — Environment-labelled evidence policy for WordPress, GA4 and GSC" "Reviewed and corrected 2026-07-13 for the multi-environment architecture. Every source must be labelled by property and environment. WordPress connector evidence is valid only for the environment selected by the active profile: tossacycling-staging WordPress data is staging evidence and must never support production revenue claims; tossacycling-production WordPress data is production evidence. GA4 and GSC configured here are production sources. Never combine environments without an explicit comparison. Origin: staging decision D#7; wording corrected during migration; no staging run history copied."

# 2) Verify: exactly 5 decisions, 2 cases, 0 runs
sudo -u tcgrowth $P decisions; sudo -u tcgrowth $P cases; sudo -u tcgrowth $P runs

# 3) Completion decision (SIXTH) — only after step 2 matches expectations
sudo -u tcgrowth $P decision-add "tossacycling-production connected as dormant read-only environment" "Separate production WordPress user, Application Password, HMAC key and SQLite store are configured. TC_ALLOW_WRITES=false and TC_GROWTH_DISABLE_WRITES=true are independently verified. Authenticated production reads, hostname identity, analytics identities, credential isolation, PII checks, production banner and signed write-route rejection passed. The production profile is dormant and not referenced by any scheduler. Completed 2026-07-13 under WP-05."
```

If step 0 shows anything other than 2 cases / 0 decisions / 0 runs: STOP and reconcile —
do not create duplicates.

### Non-blocking follow-ups

- CLI `smoke` without a positional tool raises `IndexError` — usability bug, fix separately
  (Type B), not mixed into WP-05.
- `/mnt/data/VPS_Migration_AI_Infrastructure_Master_Log.md` (on the VPS) is stale and
  predates the migration — repository docs are the source of truth.
