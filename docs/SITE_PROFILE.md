# Site Profile — Tossa Cycling WordPress

Human-maintained ground truth about the website setup. The agent's drafting/analysis mistakes so
far (untagged multilingual fields, double-branded titles) all came from not knowing this — keep it
current. When the automated read-only Site Inspector ships (post-0.3 backlog), its output is
validated AGAINST this file before it replaces it.

_Last verified: 2026-07-06 (staging wp-admin observation + owner input). Items marked ❓ need
owner confirmation._

## Environments

| | Production | Staging |
|---|---|---|
| URL | `tossacycling.com` | `dev.tourdegirona.com` |
| Hosting | IONOS **shared hosting** | IONOS VPS (Plesk), same box as the orchestrator |
| Connector | ❌ not installed (Phase 4 decision) | ✅ tc-growth-connector (draft-only writes) |
| GSC / GA4 | ✅ read-only (the production data source) | — |
| Drift | ❓ unknown — staging is a copy of production from ~2026-06; verify before trusting audits |

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

## Owner to-fill (❓ list)

- Exact WP core version · forms plugin · YITH modules · which items are CPTs
- Staging↔production drift status (when was staging last synced?)
- qTranslate enabled-language list beyond ES/EN (CA? FR? DE? — menu screenshots suggest ES/EN only)
