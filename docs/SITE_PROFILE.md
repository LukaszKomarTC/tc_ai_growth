# Site Profile — Tossa Cycling WordPress

Human-maintained ground truth about the website setup. The agent's drafting/analysis mistakes so
far (untagged multilingual fields, double-branded titles) all came from not knowing this — keep it
current. When the automated read-only Site Inspector ships (post-0.3 backlog), its output is
validated AGAINST this file before it replaces it.

_Last verified: 2026-07-09 (production incident PERF-2026-07-09 + owner input). Items marked ❓
need owner confirmation._

## Environments

| | Production | Staging |
|---|---|---|
| URL | `tossacycling.com` | `dev.tourdegirona.com` |
| Hosting | **IONOS VPS (Plesk)** — migrated from IONOS shared 2026-07-10 (PERF-2026-07-09); same box as staging + orchestrator, separate Plesk subscription | IONOS VPS (Plesk), same box as the orchestrator |
| Connector | ❌ not installed (Phase 4 decision) | ✅ tc-growth-connector (draft-only writes) |
| GSC / GA4 | ✅ read-only (the production data source) | — |
| Drift | ❓ unknown — staging is a copy of production from ~2026-06; verify before trusting audits |

> **Single-box risk (accepted 2026-07-10):** production, staging, and the agent platform share
> one VPS. Mitigations: separate Plesk subscriptions/DB users per site; offsite backups (❓ owner
> to configure in Plesk); old shared hosting kept as DNS-rollback for 2–4 weeks post-migration.
> The agent's production profile stays read-only by construction — co-location changes blast
> radius, not permissions.

## CMS & stack (observed in staging wp-admin)

- **WordPress** ~latest (version ❓ exact)
- **Theme:** Shopkeeper + **child theme** (license notice visible — key not active on staging; cosmetic)
- **Page builder:** WPBakery Page Builder (Classic Mode editing)
- **SEO:** **Yoast SEO** — owns SERP snippets. Meta description key `_yoast_wpseo_metadesc`;
  Yoast **appends the site title** to page titles (policy: no brand suffix in draft titles).
- **Multilingual:** **qTranslate XT** — ES/EN inside the SAME post fields as `[:es]…[:en]…[:]`
  tagged strings; `/en/` URLs are language views of one post. NEVER write untagged
  single-language strings into multilingual fields. ❓ whether the qTranslate↔Yoast integration
  module is enabled (checked at first approved apply).
- **Commerce:** WooCommerce (products, payments) + **Bookings** (rentals/tours) — the
  sacred, never-touched-by-the-agent zone.
- **Forms:** "Forms" menu present — ❓ which plugin (Gravity Forms?).
- **Other plugins observed:** Popup Maker, TablePress, Duplicator Pro, YITH (❓ which),
  Social Feed Gallery, Strava Challenges, Google Reviews, Snippets, Git Plugins (❓),
  Under Construction, Yoast SEO (3 notices), WPBakery.
- **Custom areas observed (❓ CPTs vs plugin pages):** Bikes, Repair Jobs, Workshop, Events,
  Growth Drafts (ours — the connector's CPT), Marketing, Analytics.
- **Agent user:** `tc-agent` (Contributor — can create drafts, cannot publish).

## Known behaviours that shape agent work

1. **qTranslate XT storage** → all user-facing draft fields must be bilingual tagged strings
   (policy decision D#4).
2. **Yoast owns snippets** → meta descriptions only take effect via the connector approval flow;
   empty Yoast box on a draft is expected; no brand suffix in titles (policy decision D#5).
3. **WPBakery content** → page body is shortcode-built; content edits must preserve builder
   markup, not raw-HTML rewrite it.
4. **Order attribution** → WooCommerce order IDs observed in the 50–53k range; GA4 purchase
   event currently not firing (case TRK-20260706-050158).
5. **Permalinks** → ES pages at root (`/alquiler_bicicletas/`), EN under `/en/`. Slugs use
   underscores historically — do NOT "fix" slugs without an explicit task + redirect plan.
6. **Shared hosting has a thin PHP-worker budget** → one misbehaving plugin can take every
   uncacheable page (cart, checkout) to 20s+. WP Fastest Cache masks this on cached pages, so
   slowness reports must always be checked against UNCACHED endpoints (`/wp-json/` is the probe).

## Performance incident PERF-2026-07-09 (resolved)

- **Symptom:** production front-end "very slow" — measured 8–29s TTFB on every uncached request
  (`/wp-json/`, cart, product/category pages); cached pages 0.5s; static files ~1s.
- **Ruled out by measurement:** GA4 tracking plugin (wp-json carries no tracking), Action
  Scheduler bloat (purging 77,605 dead actions + 237,108 orphan log rows changed nothing),
  autoload options (0.3 MB — healthy), Woo sessions (261 rows), PHP version (8.2.31).
- **Root cause:** the **MailChimp for WooCommerce** plugin (broken install, recurring PHP fatals
  visible in Action Scheduler failure logs) stalling every request. Deactivating it (together
  with GF MailChimp) dropped bootstrap from 19–29s to **2.5–3.4s** instantly; cart 20s → 2.7s.
- **State after fix:** both MailChimp plugins **deactivated (not deleted)** on production,
  2026-07-09. ❓ owner decision pending: delete them, or reinstall the current MailChimp for
  WooCommerce release if the mailing-list sync is actually wanted (re-measure after reconnect).
- **Residual:** ~2.5–3s uncached TTFB is the shared-hosting baseline (staging VPS: ~2–4s);
  acceptable, but an argument for the eventual production-on-VPS decision.
- **Update 2026-07-09/10:** the "MailChimp fix" did NOT hold — slowness returned (flat 20–22s).
  Query Monitor then found the true shape: **24.7s of 29.4s page time was database time across
  468 queries** (~53 ms/query on the shared host's remote MySQL, which flapped between fast and
  slow). Contributing software habits (ride along, now cheap on local DB, tune later):
  `wp_load_alloptions()` re-executed 2,834×/request, Gravity Forms Stripe feed queried 61×,
  YITH wishlist 12×/button. Shared host also ran **no OPcache** and `memory_limit 0`.
- **Resolution:** owner migrated production to the VPS on **2026-07-10**. Measured result:
  bootstrap 20.4–22.7s → **1.8–2.3s** (stable across runs), cart 22.2s → 1.8s, EN homepage
  36.9s → 0.7s. Old shared hosting retained as DNS rollback during the observation window.

## Owner to-fill (❓ list)

- Exact WP core version · forms plugin · YITH modules · which items are CPTs
- Staging↔production drift status (when was staging last synced?)
- qTranslate enabled-language list beyond ES/EN (CA? FR? DE? — menu screenshots suggest ES/EN only)
