# Setup

> Critical path: **start the Google Ads developer-token request and Meta app review on day one.**
> Google Ads access review ≈ 5 business days (Basic) / ≈ 10 (Standard); productionization can take
> days–weeks. Everything else can be wired in parallel.

## 1. WordPress connector

1. Copy `wordpress-plugin/tc-growth-connector/` into `wp-content/plugins/` and activate it.
2. Add a signing key to `wp-config.php`:
   ```php
   define( 'TC_GROWTH_SIGNING_KEY', '<32+ random bytes>' );
   ```
3. Create a dedicated WordPress user (e.g. `tc-agent`) with the `edit_posts` capability and
   generate an **Application Password** for it.
4. Confirm WooCommerce REST API keys exist (read-only) for product/order/report data.

## 2. Orchestrator

```sh
cd orchestrator
python -m venv .venv && . .venv/bin/activate
pip install -e ".[anthropic,google,dev]"
cp .env.example .env   # then fill in values
```

Set in `.env` (prefix `TC_`):

| Var | Meaning |
|---|---|
| `TC_WP_BASE_URL`, `TC_WP_USER`, `TC_WP_APP_PASSWORD`, `TC_WP_SIGNING_KEY` | WordPress connector |
| `TC_GSC_SITE_URL` | Search Console property (e.g. `sc-domain:tossacycling.com`) |
| `TC_GA4_PROPERTY_ID` | GA4 numeric property id |
| `TC_GOOGLE_ADS_CUSTOMER_ID` | Google Ads customer id (no dashes) |
| `TC_META_AD_ACCOUNT_ID` | `act_<id>` (token via `TC_META_ACCESS_TOKEN` env) |
| `TC_PAGESPEED_API_KEY` | PageSpeed Insights key |
| `ANTHROPIC_API_KEY` | Claude API key (runtime only) |

Credential files (git-ignored, under `secrets/`):
- `secrets/google-service-account.json` — for Search Console + GA4 (read-only scopes).
- `secrets/google-ads.yaml` — Google Ads developer token + OAuth (after access is granted).

## 3. Verify (do this before any agent run)

```sh
python -m tc_growth.cli list-tools
python -m tc_growth.cli smoke gsc_search_analytics '{"start_date":"2026-05-01","end_date":"2026-05-28"}'
python -m tc_growth.cli smoke pagespeed_check '{"url":"https://tossacycling.com/"}'
pytest -q
```

`smoke` exercises a single tool **without** the AI runtime — the fastest way to surface
OAuth/credential problems (the usual first failure point).

## 4. Managed Agents (runtime)

```sh
ant beta:environments create < agents/environment.yaml
ant beta:agents create < agents/coordinator.agent.yaml
# store the returned env + agent ids; reference them in the deployment.
ant beta:deployments create < orchestrator/deployments/weekly_report.yaml
ant beta:deployments run --deployment-id <id>   # test now
```

Provider-portable fallback (no deployment needed):
```sh
python -m tc_growth.cli weekly-report
```

> Verify which vault / MCP-OAuth-auto-refresh features your Anthropic account actually has before
> relying on them. We default to host-side custom tools, so this is not blocking.
