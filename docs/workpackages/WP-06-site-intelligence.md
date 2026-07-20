# WP-06 — Site Intelligence (the agent's eyes on site structure)

**Status:** SPEC 2026-07-20 — approved build order: first post-0.3 module. Code develops on
`feature/site-intelligence` NOW; merges to `main` only after Release 0.3 signs off (the gate
freezes the deployed system, not development).

**Why (evidence, not theory):**
- Scheduled Run #2 (clean) still produced watch-item Rec #4: it recommended routing CTAs the
  event plugin already renders — the encoded rule was followed; the *site knowledge* was missing.
- The 2026-07-19/20 draft-test night required a human to relay site structure, plugin behaviour,
  and DB state by hand. Every relay loop is a Site Intelligence gap.
- Owner + external reviewer converged (2026-07-20): "eyes before eloquence" — structure and
  lifecycle knowledge before more report sophistication.

## What it is

A per-profile, versioned, read-only **site snapshot** the platform refreshes before each
scheduled run and injects (as a compact digest) into report/investigation prompts, with the
full snapshot queryable via a tool.

Four maps, built in this order (lifecycle first — it kills the worst miss class):

1. **Lifecycle map** — for every event/product/page with a commercial state: past/upcoming
   (event dates from the events plugin), active/inactive (products), plus the standing
   treatment rules (past editions stay indexed, routed to the hub `/tour_de_girona-listado/`;
   the event plugin already renders the past-event notice + hub button — prominence, not
   existence, is the lever).
2. **URL/page map** — all public posts/pages/products: ID, slug, type, language pattern
   (qTranslate: ES at root, EN under `/en/`), parent, template.
3. **Navigation map** — menus and their targets (what the site itself considers primary paths).
4. **Capability map** — active plugins that shape agent work (qTranslate XT, Yoast, WPBakery,
   WooCommerce+Bookings, the events plugin, Snippets) + the behavioural rules already proven in
   SITE_PROFILE.md (audit reads are language-filtered; staging render is clone-frozen; etc.).

## Design constraints

- **Read-only end to end.** New connector endpoint(s) expose structure only; no write surface.
  Phase gate: READ_ONLY.
- **SITE_PROFILE.md is the validation baseline, not the victim.** Snapshot output is DIFFED
  against the human-maintained facts; discrepancies become report findings ("map says X,
  profile says Y — owner to arbitrate"), never silent overwrites. (Rule already recorded in
  SITE_PROFILE's header.)
- **Snapshots are versioned per profile** (`site_snapshot` store table or dated JSON under the
  profile's data dir); reports cite the snapshot date they reasoned from.
- **Digest is size-capped.** The prompt gets a distilled structure summary (menus, lifecycle
  states of currently-trafficked pages, the standing treatment rules); the full map stays
  behind a `site_map_query` tool the model can call when it needs detail.
- **Production profile:** same reads, dormant until the production schedule exists; the
  snapshot tool respects the profile's connector (staging reads staging, production production).

## Build slices (each with tests, in order)

1. Connector `GET /site-structure`: post-type inventory, menus, per-item {id, slug, type,
   status, language-tagged title, parent, event dates where the type carries them}. Paged,
   size-capped, audit-logged.
2. Orchestrator tool `site_snapshot_refresh` (builds + stores + diffs vs previous) and
   `site_map_query` (read the stored snapshot). Both READ_ONLY phase.
3. Lifecycle classifier: event date → past/upcoming; product status → active/inactive;
   emits the treatment rule alongside the state (state without treatment is trivia).
4. Report integration: digest injection + one new prompt rule ("consult the site map before
   recommending structural or content-routing changes; cite the snapshot date") + fixture.
5. Dashboard: read-only snapshot page (what the agent believes the site looks like) — the
   owner's correction loop.

## Acceptance (validation-style, evidence required)

- [ ] Snapshot for tossacycling-staging built, versioned, diffed against SITE_PROFILE — zero
      silent contradictions.
- [ ] A validation-mode report demonstrates a Rec-#4-class recommendation being suppressed or
      correctly reframed ("routing exists; prominence is the lever") citing the map.
- [ ] Full suite green; connector endpoints audit-logged; production profile untouched.
