# WP-09 — Visual Intelligence (the rendered page as a first-class evidence source)

**Status:** SPEC 2026-07-20 — recorded during the post-0.3 architecture freeze; builds AFTER
WP-06 → WP-07 → WP-08 → Console workflows, and is re-scoped at the one-month operating
review. Specced now so the idea survives the freeze intact.

**Origin:** owner observation — a draft H1 can be "technically good for SEO" and still wrong
on the page. The agent optimizes what it can see; today it cannot see the page.

**The four intelligences (target operating model):**
- Site Intelligence (WP-06) — structure and relationships
- Source Intelligence (WP-07) — implementation
- Data Intelligence (WP-08) — configuration and live state
- **Visual Intelligence (this WP) — what visitors actually experience**

## Design principle: measure first, look second

Platform identity applies here too — computed where possible, calibrated where not. Two tiers:

1. **Layout facts (deterministic, citable):** rendered via headless Chromium on the VPS
   against PUBLIC urls (no credentials — the least sensitive read in the platform). Computed
   from the live DOM at standard viewports (mobile 390×844, desktop 1440×900), per language
   view (ES + EN):
   - H1/heading line-wrap counts; visible-text lengths
   - CTA bounding box vs the fold (is the primary action visible without scrolling?)
   - hero height as viewport fraction; section count; large empty-space detection
   - horizontal-overflow check (broken mobile layout)
   - screenshot artifacts (mobile + desktop, per language) stored with the run
2. **Design review (model judgment, bounded):** the screenshots go to the model for the
   genuinely holistic layer — readability, hierarchy, visual rhythm, trust, consistency with
   the rest of the site. Output rules: observations and options, never invented percentages
   or pixel claims (those belong to tier 1); every recommendation names which tier its
   evidence came from.

## Rules to encode with this WP (drafting-level, testable)

- **SEO title ≠ visible H1 — optimize independently.** The SERP title carries keywords and
  location ("Bike Rental in Tossa de Mar | Road, MTB & eBike"); the visible H1 carries
  clarity ("Bike Rental in Tossa de Mar"). A draft that sets both to the same long string is
  a defect. The connector already audits them separately; the drafting prompt must too.
- **Wrap budget:** proposed visible headings are checked against tier-1 wrap counts at both
  viewports before a draft ships; >2 lines desktop or >3 mobile requires a shorter visible
  variant.
- **Above-the-fold CTA:** any landing-page recommendation must state where the primary CTA
  sits relative to the fold on mobile (measured, not assumed) — the WP-04 lesson
  (prominence, not existence) generalized.

## Reviewer Council seat

Adds the **UX/Design Reviewer** alongside SEO/Content/Technical: works from tier-1 facts +
screenshots, challenges drafts on visitor experience ("wraps to four lines on mobile and
pushes the CTA below the fold — shorten the visible H1, keep the SEO title"). Sequenced with
the Council itself: after the read layers, because a reviewer is only genuine verification
when it holds independent evidence — this one brings its own eyes.

## Constraints

- Single-box caution: one render at a time, investigation-context only (not every scheduled
  report page), explicit page budget per run.
- Renders hit the PUBLIC site as an anonymous visitor; no wp-admin rendering, no cookies,
  no logged-in state — Visual Intelligence sees what a visitor sees, nothing more.
- Staging renders inherit the SITE_PROFILE #7 caveat (clone-frozen SEO output): visual
  evidence about SEO tags on staging is unreliable; layout/UX evidence is fine.

## Acceptance (sketch — finalized post-freeze)

- [ ] Tier-1 facts computed for one ES/EN page pair at both viewports; artifacts stored and
      visible in the console.
- [ ] A draft with an over-long H1 triggers the wrap-budget rule (fixture test).
- [ ] A design-review output cites tier-1 facts for every mechanical claim (lint-style check).
- [ ] Suite green; render budget enforced.
