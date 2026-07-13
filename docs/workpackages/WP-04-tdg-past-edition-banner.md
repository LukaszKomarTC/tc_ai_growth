# WP-04 — Tour de Girona: past-edition banner → hub CTA

**Status:** DRAFT for owner review — do NOT publish until approved.
**Origin:** Scheduled run #1 (2026-07-13) surfaced 441 impressions/28d on the *expired* Spring
2026 edition page; review established the page already has a "Todos eventos TDG" link near the
top and a past-event message near the registration section. The gap is an **above-the-fold
past-edition banner with a strong CTA to the hub** — visible before any scrolling, so search
visitors landing on the historical page are routed to the current offer in the first second.

**Scope (strict):**
- Page: `/events/tour-de-girona-2026-road-s1/` (Spring 2026 road edition) — and, once approved,
  the same pattern becomes the TEMPLATE treatment for every event whose date has passed.
- Change: add ONE banner block at the very top of the content area. No slug change, no redirect,
  no de-indexing, no other content edits. The page stays indexed as a historical asset.
- Hub target: `/tour_de_girona-listado/` (the menu-linked listing that already filters to
  future editions).

## Proposed banner (bilingual, qTranslate XT tagged — one block, both languages)

Plain-text content (for the page builder / theme block of the owner's choice):

```
[:es]🏁 Esta edición (Primavera 2026) ya se ha celebrado.
La próxima edición del Tour de Girona ya está disponible — fechas, recorridos e inscripciones:
➜ Ver ediciones actuales del Tour de Girona
[:en]🏁 This edition (Spring 2026) has already taken place.
The next Tour de Girona edition is open — dates, routes and registration:
➜ See current Tour de Girona editions
[:]
```

Button/link (single CTA, prominent, above the fold):

```
[:es]Ver ediciones actuales[:en]See current editions[:]  →  https://tossacycling.com/tour_de_girona-listado/
```

Suggested minimal HTML variant (if inserted as a raw block; style to match theme):

```html
<div class="tdg-past-edition-banner" role="note">
  <p><strong>[:es]Esta edición (Primavera 2026) ya se ha celebrado.[:en]This edition (Spring 2026) has already taken place.[:]</strong><br>
  [:es]La próxima edición del Tour de Girona ya está disponible.[:en]The next Tour de Girona edition is open.[:]</p>
  <a class="button" href="/tour_de_girona-listado/">[:es]Ver ediciones actuales del Tour de Girona[:en]See current Tour de Girona editions[:]</a>
</div>
```

## Owner review checklist (before publishing)

- [ ] Banner renders above the fold on mobile AND desktop (most event traffic is mobile).
- [ ] Both language views show the correct language only (no raw `[:es]…` tags visible).
- [ ] CTA lands on the hub and the hub currently lists the next edition.
- [ ] Existing "Todos eventos TDG" link and registration-area past-event message remain (no
      duplication conflict — if the banner supersedes them visually, simplifying is the owner's
      call, not part of this WP).
- [ ] No other content, slug, or metadata changed.

## Record-keeping after publishing

```bash
tc-growth decision-add "Past-edition event pages get an above-the-fold banner + hub CTA (template treatment); editions stay indexed as historical assets, never redirected while no equivalent successor exists" 
tc-growth case-note <case-or-WP ref> "WP-04 executed: TdG Spring 2026 banner live, CTA to /tour_de_girona-listado/. Monitor: hub impressions/clicks vs spring-page CTR in next reports."
```

**Verification in later reports:** the success metric is NOT higher CTR on the spring page — it
is rising engagement on the hub (and eventually registrations on the next edition) from traffic
that lands on historical editions.
