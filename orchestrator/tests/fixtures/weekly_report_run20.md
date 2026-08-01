# Tossa Cycling — Growth Report (2026-08-01)
**Profile:** Tossa Cycling · STAGING · **Analytics source:** production GSC/GA4 (read-only) · **WP/Woo connector:** staging
**Report mode:** MANUAL VALIDATION — does not count toward the acceptance gate

# 🚴 Tossa Cycling — Weekly Growth Report
**Run date:** 2026-08-01 · **Reporting window:** 2026-07-05 → 2026-08-01 (28 days, ±1 day for timezone boundaries)

---

## Data Source Provenance

| Source | Environment | Status |
|---|---|---|
| Google Search Console | Production `tossacycling.com` (Pacific Time) | ✅ |
| GA4 (G-NCQ75TTKKR) | Production (property timezone) | ✅ |
| WooCommerce attribution tool | **STAGING** `dev.tourdegirona.com` (D#7) | ⚠️ Not valid production evidence |
| WordPress connector (pages, audits, drafts) | **STAGING** `dev.tourdegirona.com` (D#7) | ⚠️ Staging labels applied throughout |
| Google Ads | Not configured (`TC_GOOGLE_ADS_CUSTOMER_ID` missing) | ❌ |
| Meta Ads | Not configured (account ID / token missing) | ❌ |
| PageSpeed Insights | HTTP 429 on both URLs, first attempt — not retried per policy | ❌ |

All "currently available sources" have been collected. Google Ads, Meta Ads, and PageSpeed are unavailable this cycle (see Pending Integrations).

---

## 1 · SEO Opportunities

### 1a — Top opportunity by page (position 5–20, high impressions)

**`/alquiler_bicicletas/` (Spanish rental hub) — PRIORITY 1**

| Metric | ES page | EN page |
|---|---|---|
| Impressions | **1,421** | 593 |
| Clicks | 67 | 34 |
| CTR | 4.71% | 5.73% |
| Avg position | **14.74** | 4.55 |

OBSERVATION: The ES rental page is the highest-impression non-home page on the site yet sits at position 14.74 — about 10 positions below its EN counterpart. Staging audit (post ID 13699, environment: staging) reveals three structural issues: **H1 is empty**, meta description appears to have no English qTranslate block (Spanish text only), and body copy is only 144 words (thin). These are likely reflected in production.

HYPOTHESIS (confidence: medium-high): an empty H1 and absent bilingual meta reduce relevance signals to Google for both language variants, contributing to the lower ES position versus EN. This is consistent with, but does not prove, positional underperformance — other factors (link equity, query mix, competition) also apply.

CONVERSION DESTINATION: WooCommerce rental add-to-cart → checkout.

**Recommended actions (D#9 — proposed, awaiting human approval):**
- Apply bilingual title and meta to production post (specs in D#9):
  - **Title:** `[:es]Alquiler de Bicicletas en Tossa de Mar – Carretera, BTT y eBike[:en]Bike Rental Tossa de Mar – Road, MTB & eBike[:]`
  - **Meta:** `[:es]Alquila bicicleta de carretera, BTT o eBike en Tossa de Mar. Todas las tallas, disponibilidad en tiempo real, reserva online en minutos. ¡Pedalea por Costa Brava![:en]Hire a road bike, MTB or eBike in Tossa de Mar. All frame sizes, real-time availability, book online in minutes. Explore Costa Brava at your own pace![:]`
  - **Companion (human content edit):** add bilingual H1 in page body; expand to ≥300 words with bilingual content; add internal links to individual rental product pages.
- Note: slug `/alquiler_bicicletas/` is **unchanged** — a slug change would require a redirect and is a separate decision.
- wp_create_seo_draft was blocked at phase 0; specifications above are for direct human implementation pending D#9 approval.

---

**`/en/salidas_guiadas-listado/` — Guided Tours Hub**

| Impressions | Clicks | CTR | Avg position |
|---|---|---|---|
| 256 | 3 | 1.17% | 4.1 |

OBSERVATION: Position ~4 with 1.17% CTR is anomalously low — CTR at this position is typically several multiples higher for informational and commercial queries. Staging audit (post 48284): **H1 empty**, **meta description completely absent** (Google is auto-generating the snippet from body copy, which may not match user intent), 401 words of content.

CONVERSION DESTINATION: guided tour date selection via event calendar on this hub, leading to individual event checkout.

**Recommended action (D#10 — proposed, awaiting human approval):**
- Apply bilingual title and meta to production:
  - **Title:** `[:es]Salidas Guiadas en Bicicleta – Costa Brava desde Tossa de Mar[:en]Guided Cycling Tours – Costa Brava from Tossa de Mar[:]`
  - **Meta:** `[:es]Salidas guiadas en bici por Costa Brava. Grupos reducidos, guías expertos, rutas de carretera y BTT desde Tossa de Mar. Consulta el calendario y reserva tu plaza.[:en]Guided cycling tours along Costa Brava. Small groups, expert guides, road bike and MTB routes from Tossa de Mar. Check the calendar and book your spot online.[:]`
  - **Companion:** add bilingual H1.
- ⚠️ Before applying: pull this page with query+page dimensions in GSC to verify the query mix — SERP features or non-cycling queries could independently explain the low CTR. CTR benchmarks are screening heuristics only; inspect the SERP before concluding title/meta is the sole driver.

---

**`/en/salidas-autoguiadas/self-guided-ebike-tour-coastal-explorer/`**

| Impressions | Clicks | CTR | Avg position |
|---|---|---|---|
| 106 | 1 | 0.94% | 3.48 |

OBSERVATION: Position 3.48 with <1% CTR is markedly low. This warrants query-mix inspection (GSC query+page filter for this URL) before any title/description changes are recommended. Possible causes: rich SERP features suppressing CTR; queries with informational (not transactional) intent; or a title/snippet mismatch. CONVERSION DESTINATION: self-guided eBike coastal tour booking. ACTION: pull query breakdown for this URL in next cycle and report back.

---

### 1b — High-value query opportunities

| Query | Impressions | CTR | Avg position |
|---|---|---|---|
| `costa brava bike rental` | 24 | 4.2% | **19.25** |
| `alquiler bicicletas` | 22 | 9.1% | 8.59 |
| `alquiler bici carretera tossa` | 18 | 5.6% | 9.22 |
| `alquiler de bicicletas` | 17 | 5.9% | 10.59 |

OBSERVATION: `costa brava bike rental` (position 19.25) is the highest-commercial-value under-positioned query — broad regional intent, directly matching the business. Applying the D#9 title/meta draft to `/alquiler_bicicletas/` is the most likely lever for this query. Verify which URL ranks for it using GSC query+page dimensions before additional actions.

---

### 1c — Historical assets (routing, not traffic optimisation)

Per policy, past-date event pages are HISTORICAL ASSETS. Do not optimise their title/CTR; instead route residual traffic to the current commercial hub.

| Page | Impressions | CTR | Position | Commercial state |
|---|---|---|---|---|
| `/en/events/tour-de-girona-2026-road-s1/` | 299 | 1.34% | 6.83 | Past event (Tour de Girona 2026 — run date Aug 1) |
| `/en/events/tour-de-girona-2026-gravel-o1/` | 68–70 | 1.43–7.4% | 6–10 | Past event |
| `/en/events/emtb-tour-salida-guiada-facil-2026-24-06-2026/` | 254 | 1.57% | 2.87 | Past event (date: 24 Jun 2026) |

RECOMMENDATION: Add prominent in-page links from each of these pages to the current guided tours hub (`/en/salidas_guiadas-listado/`) or next-edition event page. The eMTB June 24 page's low CTR at position 2.87 is consistent with searchers seeing a past date in the snippet and not clicking — the intent mismatch is expected and does not require a snippet fix; it requires better routing of the visitors who do land there.

---

### 1d — Other structural observations

**www vs non-www homepage split (GSC):**
- `https://www.tossacycling.com/` → 2,912 impressions, position 4.14, CTR 12.5%, 364 clicks
- `https://tossacycling.com/` → 1,363 impressions, position 12.53, CTR 8.6%, 117 clicks

OBSERVATION → HYPOTHESIS: Both URL variants appear as separate GSC entries about 8.4 positions apart. This is consistent with (a) a missing or inconsistent www/non-www canonical/redirect, or (b) GSC tracking distinct URL forms that actually redirect correctly. CANNOT CONCLUDE canonical issue without verification. RECOMMENDED CHECK: GSC URL Inspection on both URLs; confirm HTTP redirect chain and canonical tag in `<head>`. If both are serving without a definitive canonical, consolidating could strengthen home-page authority signals.

**Wishlist page `/en/wishlist/`:**
- 80 impressions, position 5.24, CTR 1.25%, 1 click.
- A WooCommerce utility page with no organic conversion purpose appearing at position 5. RECOMMENDED (separate proposal, not bundled into D#9/D#10): add a `<meta name="robots" content="noindex, follow">` tag (via Yoast or wp_robots — **not** robots.txt Disallow, which cannot noindex and hides the tag from crawlers). This requires human approval.

---

## 2 · Ads Efficiency

**Google Ads:** ❌ Not configured (`TC_GOOGLE_ADS_CUSTOMER_ID` not set). No spend, conversion, or ROAS data available. `budget_recommendations` cannot run.

**Meta Ads:** ❌ Not configured (account ID / access token not set). No campaign data available.

Wasted-spend analysis, best-performer identification, and capped budget-change recommendations cannot be produced this cycle. See Pending Integrations.

---

## 3 · Revenue Insights

### GA4 — 28-day window (production G-NCQ75TTKKR)

> ⚠️ **Critical context:** The purchase-tracking fix (D#3 — WooCommerce Google Analytics Integration, installed 2026-07-08) means only ~25 of these 28 days have operational tracking. This is the **first near-complete post-fix 28-day window.** All pre-fix sessions (2026-07-05 to 2026-07-07) contributed near-zero conversions. Values are from top-50 GA4 rows and are NOT transaction-matched to WooCommerce production orders (D#7: WooCommerce tool reads staging).

| Channel | Sessions (visible rows) | GA4 purchase events | Observable revenue |
|---|---|---|---|
| Organic Search | ~650+ | **15** | **~€2,244** |
| Direct | ~400+ | **5** | **~€182** |
| Referral | ~35 | 0 | €0 |
| AI Assistant | ~35 | 0 | €0 |
| Organic Social | ~12 | 0 | €0 |
| **Total (observable)** | **~1,130+** | **20** | **~€2,426** |

*GA4 event name: `purchase`. Event count: 20 in top-50 rows; actual total may be higher. Not transaction-matched.*

### Top converting organic landing pages

| Landing page | GA4 purchase events | Observable revenue | Conversion destination |
|---|---|---|---|
| `/` | 5 | €1,179 | Rental/tour booking |
| `/en` | 4 | €543 | Rental/tour booking |
| `/en/alquiler_bicicletas` | 2 | €110 | Rental cart |
| `/en/carrito` | 2 | €155 | Checkout (cart entry as session origin) |
| `/en/shop/alquiler/rental_road/scott-addict-50-carretera` | 1 | €147 | Road bike rental |
| `/en/shop/alquiler/rental_ebike-mtb/scott-aspect-eride-910-ebike-mtb` | 1 | €110 | eMTB rental |
| `/en/salidas_guiadas-listado` (Direct) | 1 | €134 | Guided tour booking |
| `/en/shop/alquiler/rental_tandem/schauff-tandem` (Direct) | 1 | €45 | Tandem rental |

### High-traffic, zero-conversion pages — investigation triggers

- **`/alquiler_bicicletas` (Organic, 54 sessions, 0 conversions):** The primary Spanish rental hub attracts meaningful organic traffic but registers no GA4 purchase events. Possible causes: page leads to an ES-language flow that results in checkout under a different session (conversion attributed to `/en/alquiler_bicicletas` or cart); UI friction at the point of adding to cart; or browse-and-return patterns where conversion happens in a later session. RECOMMENDED CHECK: walk the `/alquiler_bicicletas` → add-to-cart → checkout path manually to confirm CTA visibility and no broken steps.
- **`/en` (Direct, 90 sessions, 0 conversions):** Direct home-page traffic that doesn't convert is expected — many return visitors, bookmarks, and non-intent visits. Not flagged as a concern.

### AI Assistant channel (emerging)
~35 sessions this window landing on `/`, `/en`, `/en/alquiler_bicicletas`, and event pages. Zero conversions — consistent with AI-driven awareness/discovery traffic. No action required; worth monitoring as this channel grows.

### Order-received page — tracking note (monitoring)
GA4 shows `/en/pedido/order-received/[masked]`: 5 Organic Search sessions. D#6 (noindex) was executed and verified 2026-07-14. Per policy: GA4 sessions are an investigation trigger, not proof of indexing. Sessions are likely attributable to pre-noindex indexed URLs or bookmark/email access. Verify via GSC URL Inspection if any doubt about current crawlability.

---

## 4 · Known Cases — Weekly Status

### INC-2026-02-01 — Tobacco/spam doorway pages · MONITORING · conf medium-high
D#2 (410 rule + GSC removals) executed and verified 2026-07-14.

**This week's evidence:** Spam paths still appearing with clicks in the 28-day window — top individual impression count: **12** (`/Spark-Rasa-Mangga.../579664`). Tobacco-brand queries (`"backed by a tobacco brand" debut album`: 8 impressions; Marlboro-rewards.com fragments: 2–4 impressions each) remain in GSC query data at 0 clicks — residual stale index signals.

**Trajectory (top impression count, individual URL):** pre-fix → 74 impressions → 23 impressions (2026-07-27) → **12 impressions (this week)**. Consistent with expected post-410 de-indexing decay. No re-acceleration observed.

**Threshold:** Prior recommendation was to propose 'resolved' when top individual URL impressions drop below 10. At 12 this week, not yet at threshold. Continue monitoring. If next window (ending ~2026-08-08) shows all individual spam URLs below 10 impressions, **propose moving to 'resolved'**.

---

### TRK-20260706-050158 — GA4 & WooCommerce tracking gap · MONITORING · conf 0.95
D#3 (install WooCommerce Google Analytics Integration, enable purchase events) — executed 2026-07-08, verified end-to-end. D#6 (noindex order pages) — executed and verified 2026-07-14. D#8 rejected (low GA4 purchase values were genuine coupon-test totals, not a mapping defect).

**This week:** First near-complete post-fix 28-day window. GA4 shows 20 observable purchase events / ~€2,426 revenue — meaningful first revenue signal from the restored tracking pipeline. Tracking appears stable.

**Human milestone condition** (from 2026-07-12 note): *"Set to monitoring until processed report shows 2.70 EUR for 12 Jul, then resolve."* That milestone was met in the 2026-07-13 weekly check (3 conversions / €2.70, consistent with verified coupon-test orders).

**PROPOSAL:** Move TRK-20260706-050158 to **`resolved`** — subject to human confirmation that WP Admin order counts for the post-2026-07-08 period are consistent with the 20 GA4 purchase events observed. **Status change requires human approval via `case_set_status`.**

---

### INC-20260705-222323 — Tobacco doorway pages (organic) · CLOSED
Closed into INC-2026-02-01. D#2 executed and verified 2026-07-14. No new action.

---

## 5 · Recommended Actions — Prioritised

| # | Priority | Action | Owner | Case / Decision |
|---|---|---|---|---|
| 1 | 🔴 High | **Approve D#9** and apply bilingual title + meta to `/alquiler_bicicletas/` in production; add bilingual H1; expand body copy to ≥300 words | Human | D#9 (proposed) |
| 2 | 🔴 High | **Approve D#10** and apply bilingual title + meta to `/salidas_guiadas-listado/` in production; add bilingual H1 | Human | D#10 (proposed) |
| 3 | 🔴 High | **Confirm TRK-20260706-050158 resolved** — check WP Admin order count post-2026-07-08; if consistent with 20 GA4 conversions, approve `case_set_status` → resolved | Human | TRK-20260706-050158 |
| 4 | 🟠 Medium | **GSC query+page audit** for `/en/salidas-autoguiadas/self-guided-ebike-tour-coastal-explorer/` — pull query breakdown to diagnose 0.94% CTR at position 3.48 before recommending title/meta changes | Agent next cycle | — |
| 5 | 🟠 Medium | **Add routing links** from past-event pages (Tour de Girona 2026 road/gravel, eMTB June 24) to current guided-tours hub or next-edition event page | Human content edit | — |
| 6 | 🟠 Medium | **Verify www/non-www canonical**: GSC URL Inspection on `https://www.tossacycling.com/` and `https://tossacycling.com/`; check HTTP redirect chain and `<link rel="canonical">`. Confirm or rule out split authority before any fix | Human | — |
| 7 | 🟡 Low | **Wishlist noindex**: propose adding `<meta name="robots" content="noindex, follow">` to `/en/wishlist/` via Yoast/wp_robots (NOT robots.txt). Requires separate human approval | Human approval needed | — |
| 8 | 🟡 Low | **PageSpeed audit (retry with backoff)**: both home and rental page checks returned HTTP 429 (cause unverified, not retried). Rerun in a separate session before peak-season window closes | Agent / Human | — |
| 9 | 🟡 Low | **Configure Google Ads** (`TC_GOOGLE_ADS_CUSTOMER_ID`) and **Meta Ads** (account ID / token) to enable paid-channel efficiency analysis and `budget_recommendations` | Human (DevOps) | — |
| 10 | 🟡 Low | **INC-2026-02-01 monitoring**: if next weekly GSC window shows all spam URL impression counts <10, propose `case_set_status` → resolved | Agent next cycle | INC-2026-02-01 |

---

## Pending Integrations

| Integration | Status | Consequence |
|---|---|---|
| Google Ads (`TC_GOOGLE_ADS_CUSTOMER_ID`) | ❌ Not configured | Paid spend, ROAS, and wasted-spend analysis unavailable |
| Meta Ads (account ID / token) | ❌ Not configured | Facebook/Instagram performance invisible |
| PageSpeed Insights | ❌ HTTP 429 on both URLs (cause unverified — not retried per policy) | Mobile CWV data unavailable this cycle |
| WooCommerce (production) | ⚠️ Reads STAGING (D#7) | Revenue truth requires WP Admin or GA4; tool output discarded |

---

*Report generated: 2026-08-01. Sources: GSC + GA4 (production); WordPress connector (staging, D#7). Decisions logged: D#9, D#10 (both proposed, awaiting human activation). Case notes appended: INC-2026-02-01, TRK-20260706-050158.*

---
⚠️ **Platform lint:** mentions robots.txt alongside noindex — robots.txt CANNOT noindex; use a meta robots tag or X-Robots-Tag and keep the page crawlable

---
_Blocked (need higher phase / human approval): wp_create_seo_draft_
