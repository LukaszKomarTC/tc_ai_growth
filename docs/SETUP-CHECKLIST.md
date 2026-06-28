# Setup checklist — staging, read-only, smoke test

A copy-paste path to a **live read-only smoke test** of the SEO → revenue lever, with zero risk
to production. Do every step on **staging**, with **read-only** scopes, in the default
`READ_ONLY` phase (no drafts, no writes, no ad spend).

## Golden rules

- **Staging only.** Point everything at a staging clone, never production, until the smoke test
  is green and you've reviewed the audit log.
- **Read-only scopes.** Grant the Google service account read-only access only (scopes below).
- **The agent user cannot publish.** Give it `edit_posts` but **not** `publish_posts` — this is
  what keeps the Phase 3 approval gate honest (the agent can draft, only a human can approve).
- Secrets live in `orchestrator/secrets/` and `.env` — both git-ignored. Never commit them.

---

## 1. WordPress connector (staging)

1. Copy `wordpress-plugin/tc-growth-connector/` into the staging site's `wp-content/plugins/`
   and activate it (Plugins → Activate). This is independent of the booking plugin and removable.
2. Add a signing key to staging `wp-config.php` (generate 32+ random bytes):
   ```php
   define( 'TC_GROWTH_SIGNING_KEY', 'PASTE_A_LONG_RANDOM_SECRET_HERE' );
   ```
   Generate one with: `python3 -c "import secrets; print(secrets.token_hex(32))"`
3. Create a dedicated agent user with a **draft-but-can't-publish** capability set. Simplest:
   create a user with the **Contributor** role (has `edit_posts`, lacks `publish_posts`). If you
   need it to also draft edits to existing pages/products later, add a small custom role instead:
   ```php
   // one-time, e.g. in a mu-plugin on staging
   add_role( 'tc_growth_agent', 'TC Growth Agent', array(
       'read' => true,
       'edit_posts' => true, 'edit_others_posts' => true, 'edit_published_posts' => true,
       'edit_pages' => true, 'edit_others_pages' => true, 'edit_published_pages' => true,
       // intentionally NO publish_posts / publish_pages — agent can draft, never publish/approve
   ) );
   ```
4. For that user: **Users → Profile → Application Passwords → Add New** ("tc-agent"). Copy the
   generated password (spaces and all).
5. Confirm WooCommerce is active on staging (for `woo_revenue_attribution`). WooCommerce 8.5+
   stores Order Attribution meta automatically; no extra config needed.

---

## 2. Google service account (Search Console + GA4, read-only)

Run with the `gcloud` CLI (replace `PROJECT_ID`):

```sh
# Enable the read APIs we use
gcloud services enable searchconsole.googleapis.com analyticsdata.googleapis.com \
  pagespeedonline.googleapis.com --project PROJECT_ID

# Create the service account
gcloud iam service-accounts create tc-growth-readonly \
  --display-name "TC Growth (read-only)" --project PROJECT_ID

# Create + download a key into the git-ignored secrets dir
gcloud iam service-accounts keys create orchestrator/secrets/google-service-account.json \
  --iam-account "tc-growth-readonly@PROJECT_ID.iam.gserviceaccount.com"
```

Then grant the service-account **email** read access to the data (this is per-property, done in
each product's UI — IAM roles alone don't grant Search Console / GA4 data access):

- **Search Console** → Settings → Users and permissions → Add user →
  `tc-growth-readonly@PROJECT_ID.iam.gserviceaccount.com`, permission **Full** or **Restricted**
  (read is enough).
- **GA4** → Admin → Property Access Management → add the same email as **Viewer**.

Scopes the tools request (read-only, already set in code — listed here for review):
- Search Console: `https://www.googleapis.com/auth/webmasters.readonly`
- GA4: `https://www.googleapis.com/auth/analytics.readonly`

> Google Ads and Google Business Profile are intentionally **not** part of this smoke test —
> they need the developer-token / app-review approvals that take days–weeks. Start those in
> parallel; until granted, those tools report "not provisioned" and the report lists them under
> *Pending integrations*.

---

## 3. `.env`

```sh
cd orchestrator
cp .env.example .env
```

Fill in (staging values):

```ini
TC_WP_BASE_URL=https://staging.tossacycling.com
TC_WP_USER=tc-agent
TC_WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx
TC_WP_SIGNING_KEY=<same value as wp-config.php>

TC_GSC_SITE_URL=sc-domain:staging.tossacycling.com   # or the URL-prefix property
TC_GA4_PROPERTY_ID=<numeric GA4 property id>
TC_PAGESPEED_API_KEY=                                 # optional; PageSpeed works keyless but rate-limited

TC_AI_PROVIDER=anthropic
TC_AI_MODEL=claude-opus-4-8
ANTHROPIC_API_KEY=sk-ant-...

TC_REPORT_CHANNEL=email        # or telegram
TC_REPORT_RECIPIENT=lukaszkomar@gmail.com
```

---

## 4. Run the smoke test

```sh
cd orchestrator
python -m venv .venv && . .venv/bin/activate
pip install -e ".[anthropic,google]"

# 4a. Offline sanity — no creds needed (lists tools, runs guardrails):
python -m tc_growth.cli list-tools
make -C .. check          # build + 24 tests + php lint

# 4b. Per-tool read-only smokes (these hit the real read APIs):
python -m tc_growth.cli smoke gsc_search_analytics '{"start_date":"28daysAgo","end_date":"today","dimensions":["query"],"row_limit":5}'
python -m tc_growth.cli smoke ga4_report          '{"start_date":"28daysAgo","end_date":"today"}'
python -m tc_growth.cli smoke woo_revenue_attribution '{"days":28}'
python -m tc_growth.cli smoke pagespeed_check     '{"url":"https://staging.tossacycling.com/"}'
python -m tc_growth.cli smoke wp_list             '{"kind":"rentals"}'

# 4c. Full read-only coordinator run (Phase READ_ONLY — cannot write anything):
python -m tc_growth.cli weekly-report
```

> Note: `smoke` runs a single tool **without** the AI runtime — the fastest way to surface
> OAuth/credential problems. Each `smoke` exits non-zero and prints a structured `error` if a
> credential is missing or a scope is wrong, so you can fix them one at a time.

---

## 5. What success looks like

- `gsc_search_analytics` returns rows with `clicks/impressions/ctr/position`.
- `ga4_report` returns channel rows with sessions/conversions/revenue.
- `woo_revenue_attribution` returns `by_source` totals.
- `pagespeed_check` returns scores + Core Web Vitals.
- `weekly-report` prints/sends a digest with **SEO Opportunities / Ads Efficiency / Revenue
  Insights / Recommended Actions**, with Google Ads & Meta & GBP under *Pending integrations*.
- The connector audit table (`wp_tc_growth_audit`) shows only `read-*` rows — **no writes**.

If all green on staging: review the audit log, then repeat steps 1–3 against production with the
**same read-only posture** (still `READ_ONLY` phase). Move to drafts (Phase 2) only when you're
ready to review what the agent proposes.
