# WP-05 — Production connection prep (dormant read-only environment)

**Status:** READY for human execution — all steps 0.3-legal (configuration + human plugin
install + read-only smoke tests; no platform capability changes, no scheduling changes).
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
