# Validation Checklist — Phase 3B (staging)

The gate between "built" and "trusted to act". Work through every box against **staging**
(`dev.tourdegirona.com`); tick with a date + one line of evidence (run id, case ref, or screenshot).
Nothing advances to Phase 4 until ALL boxes are green **and** two consecutive Monday reports run
clean (no calibration failures, no duplicate cases, no re-proposed decided items).

How to run a draft test: invoke the run at DRAFTS phase (supervised, from the CLI) so
`wp_create_seo_draft` / `wp_create_product_revision` are admitted by the gate; the connector only
reaches staging. Review each result in staging wp-admin.

## Content (drafts at DRAFTS phase, staging connector)

- [x] **SEO draft — Spanish rental page** (`/alquiler_bicicletas/`, post 13699) — 2026-07-06,
      draft 50457: qTranslate-tagged bilingual title+meta, slug untouched, status draft; verified
      in staging wp-admin (ES/EN tabs correct). Supersedes draft 50455 (untagged — the finding
      that produced policy D#4).
- [x] **Product revision — Scott Addict 50** — 2026-07-19, revision 50459 on product 50274:
      bilingual tagged description stored as a revision ("Revision by tc-agent" in the compare
      screen), live product untouched. Required connector v0.1.1
      (`add_post_type_support('product','revisions')`) — WooCommerce products don't support
      revisions by default, so the stored revision was invisible in wp-admin until the plugin
      declared support. Known limitation recorded: the connector writes `post_content` only;
      it cannot target the Short Description (`post_excerpt`) field.
- [x] **Landing/tour draft — Tour de Girona** — 2026-07-19, draft 50461 on hub page 48347
      (`tour_de_girona-listado`). Drafted for the HUB, not the expired event page: the original
      "CTR-focused event-page draft" wording predates the commercial-state policy (historical
      editions are routed, not CTR-optimised), so the hub draft is the policy-compliant form of
      this test. Both language blocks tagged, no brand suffix, slug untouched; empty H1 and
      zero internal links correctly flagged as separate out-of-scope content work.
- [x] **Homepage title draft** — 2026-07-19, draft 50460 on page 11038: "Home" →
      `[:es]Alquiler de Bicicletas y Rutas en Tossa de Mar[:en]Bike Rental & Guided Tours in
      Tossa de Mar[:]` + tagged meta (~148/149 chars), GSC-informed, D#4/D#5/D#7 compliant.
      The agent's pre-approval flag (audit returned untagged source fields) was resolved by
      code+render inspection: audit reads are qTranslate-filtered; storage is tagged (raw DB
      row on 11038 confirms `[:es]…` stored) — flagged calibration was correct behaviour.

## Memory

- [x] **Opens the correct case** for a genuinely new finding — 2026-07-06: TRK-20260706-050158
      (TRK prefix, confidence 0.85, order-ID evidence in body), opened by the Monday 05:00 run.
- [x] **Does not reopen a resolved case** — 2026-07-06 mid-week report: Active Case Dashboard
      references INC-2026-02-01 (monitoring) and the closed duplicate as "merged, no separate
      action"; zero new cases opened for known topics.
- [ ] **case_read consulted** before judging new-vs-known (visible in run tool calls).
      **Criterion clarification (2026-07-20, BEFORE the run it applies to):** this box means
      exactly what it says — case-memory consultation for new-vs-known judgment, evidenced by
      the FROZEN 0.3 candidate's own tool trace (Monday scheduled run #3, or a supervised
      validation run on the same frozen candidate if Monday's trace doesn't show it).
      WP-06's acceptance evidence ("site map consulted before structural claims") is a
      DIFFERENT behaviour proven on a post-merge build — it must NOT close this box, and 0.3
      does not sign off while this box is open. Both checks together become a standing item
      of post-merge validation reports (case memory for new-vs-known; site map for
      structural), but the gate closes on the original criterion only.
- [x] **Links decisions to cases** — 2026-07-06: D#6 (noindex order pages) logged as proposed,
      linked to TRK-20260706-050158.
- [x] **Updates confidence with a basis** — 2026-07-12 re-examination of TRK-20260706-050158:
      0.85 → 0.95, basis "live ecommerce funnel + 2 purchase events after 8 Jul install";
      recorded by the run in the case journal (confirm ladder rendering on the dashboard).
- [x] **References a previous investigation** — 2026-07-06 mid-week report cites the 2026-07-05
      human Googlebot-404 verification from the case journal in its spam assessment.

## Workflow (approval round-trip)

- [x] **Draft generated → human reviews** in staging wp-admin — 2026-07-06, draft 50457 reviewed
      (language tabs, slug, status, meta box).
- [x] **decision-approve** flips status + journals the human action — 2026-07-06: D#2, D#3, D#6
      approved; case journals carry the entries.
- [x] **decision-reject** settles; the NEXT run does not re-propose — 2026-07-06: D#1 rejected as
      duplicate; absent from the same-day mid-week report.
- [x] **Case update after manual action** — 2026-07-12, stronger than the scripted test: the
      WP-01 tracking fix was applied WITHOUT a prior case-note, and a blind re-examination run
      discovered it from GA4 data alone — acknowledged the change, raised confidence with basis,
      proposed MONITORING (respecting ALWAYS_ASK), cross-referenced the INC spam cases without
      re-raising, honored D#7 provenance (no Woo/staging data), and routed its one
      context-starved hypothesis (D#8, "value mapping broken" — actually coupon-test totals)
      to the human decision queue instead of asserting it.
- [x] **Dashboard reflects all of the above** — 2026-07-06 screenshots: cases, run costs,
      decision statuses, confidence, validation report page.

## WordPress (draft fidelity, staging)

- [x] **Draft appears correctly** in wp-admin — 2026-07-06, draft 50457: right source post
      (#13699), draft status, tc-agent author, correct parent.
- [x] **Revision formatting preserved** — 2026-07-06 screenshots: WPBakery builder content intact
      in both language views.
- [x] **Images/metadata untouched** by the revision — 2026-07-19, revision 50459: compare
      screen shows only Título/Content changed; product images, price, and all product meta
      untouched (revisions store post fields only, never product meta — structural guarantee).
- [x] **Approval meta box** behaves and shows the full proposal — 2026-07-06 screenshot after
      PR #26: bilingual meta description + agent rationale + source link + capability-guarded
      checkbox.
- [x] **qTranslate x Yoast at apply time** — CLOSED 2026-07-20 on a three-part evidence chain
      (owner called scope: no further staging drilling; final end-to-end confirmation rides
      the first production apply, Release 1.1, per-run human confirmation).
      1. **Apply pipeline verified live** (2026-07-19/20): draft 50461 human-approved and
         applied via `publish_seo_draft`; triple gate exercised (two 403 refusals on
         unapproved drafts 50457/50460 proved the server-side approval check). TITLE renders
         per-language on both URLs, zero raw-tag leaks.
      2. **Connector defect found & fixed by this test — the test earned its keep.** First
         apply stored a Spanish-only meta (qTranslate language-filters postmeta reads in
         REST contexts → the connector read its own proposal pre-stripped) and left Yoast's
         indexable stale (meta written after `wp_update_post`). Fixed in v0.1.2 (raw `$wpdb`
         read + meta-before-update, PR #58); re-apply verified by raw SQL: stored value is
         the intact tagged string `[:es]Todas las ediciones…`.
      3. **Per-language render of a tagged value is proven by the homepage**: its indexable
         holds raw `[:es]CENTRO DE CICLISMO…` and renders ES on `/`, EN on `/en/`, no raw
         tags (verified 2026-07-19 by page-source fetch of both languages).
      **Why the applied value doesn't render on STAGING (documented, not a defect):** Yoast
      refuses to create/update indexables when `WP_ENVIRONMENT_TYPE` is not 'production'
      (confirmed by its own `wp yoast index --reindex` refusal message). Staging's rendered
      SEO output is therefore FROZEN AT CLONE TIME — cloned indexable rows render; anything
      written since never reaches the page. Production has no such gap. Optional staging
      override if a live demo is ever wanted (3-line mu-plugin):
      `add_filter( 'Yoast\WP\SEO\should_index_indexables', '__return_true' );`
- [x] **Nothing published automatically** — 2026-07-06: every artifact (50455, 50457) remained
      status=draft; live post 13699 untouched; zero production writes.

## Sign-off (Release 0.3 → 1.0 gate; see docs/STATUS.md for the full criteria)

- [ ] All boxes green (dates + evidence above).
- [ ] At gate close: tag the exact deployed commit that produced the three clean Mondays
      (`release-0.3-validated`) BEFORE merging any post-gate capability — the gate validated
      that commit, not whatever main becomes afterwards.

      **Agreed close-out sequence (2026-07-20 — gate evidence and post-gate acceptance are
      SEPARATE evidence events):**
      1. Monday scheduled run #3 executes on the frozen candidate.
      2. Grade it (clean-Monday criteria) AND collect genuine case_read evidence from its
         tool trace.
      3. Close the remaining original 0.3 boxes. If case_read is unproven, 0.3 does NOT sign
         off — nothing merges until the box closes honestly (supervised validation run on the
         same frozen candidate is the permitted fallback).
      4. Tag `release-0.3-validated`.
      5. Merge and deploy WP-06 (feature branch).
      6. Run WP-06 live acceptance (first real snapshot + behavioural grading) — graded as
         the FIRST POST-0.3 CAPABILITY, never as gate evidence.
- [ ] THREE consecutive clean Mondays: **2026-07-13 ✅ (operational gate)** · **2026-07-20 ✅
      (CLEAN)** · ____-__-__
      (clean = no calibration failure, no duplicate case, no false critical, no re-proposed
      decided item).

      **Scheduled Run #2 (2026-07-20 07:07): CLEAN — first fully clean scheduled run.**
      Graded against the complete listed-miss inventory; every previously-violated rule held:
      - 404-vs-410 (the rerun-#3 violation carried forward to this grading): NO comparative
        de-indexing claim anywhere. "410 + GSC removals should accelerate deindexing" makes
        no status-code comparison and hedges a testable 2–4-week expectation. Lint clean.
      - Positions ordinal: "about 11 positions below" / "~9 positions below" — the exact
        prescribed absolute-difference form; no ratios, no page-boundary claims.
      - Direct traffic: "consistent with confirmed coupon test orders (D#8 rejected)" —
        hedged, cites the rejected decision without re-proposing it; /pedido/ GA4 sessions
        explicitly called "not evidence of ongoing indexing".
      - Query→page via GSC query+page dimensions; masking + pattern aggregation
        (`/en/pedido/order-[masked]`, 12 sessions total); computed-or-omitted (D#3 date
        stated, no invented percentages); 429 calibration verbatim ("cause unverified; retry
        with backoff"); CTR-as-heuristic verbatim; historical assets kept indexed with routing
        CTAs; www/non-www led verification-first; "not transaction-matched" + consent-mode
        caveats present; preamble absent; platform dates correct (28-day inclusive window);
        profile header correct ("Tossa Cycling · STAGING" — the "default" cosmetic defect is
        gone). Operational gate: no duplicate cases, no false criticals, INC/TRK referenced
        without re-raising, no writes attempted, delivered on schedule.
      Non-disqualifying notes (watch items):
      1. Rec #4 (add routing CTAs to event pages) duplicates settled WP-04 — the event plugin
         already provides the hub button; the planned plugin-template change covers this.
         Encoded routing rule was followed correctly; the gap is site-structure knowledge
         (Site Intelligence, post-gate). Owner: treat Rec #4 as already covered.
      2. "~15 days before / ~12 after" the D#3 fix: actual split is 15/13 (sums to 28); the
         tilde'd figures sum to 27. Off-by-one under an explicit hedge — candidate for
         platform computation when keyed `fix_date` facts land (Memory 2.0, already planned).
      3. §5 quotes the 429 policy line "2 attempts" while describing 2 calls × 1 attempt —
         cosmetic phrasing tension.
      4. Rec #2 (www/non-www) verified same morning from the sandbox: `www.` 301s to
         non-www (path-preserving) and canonical declares non-www — configuration is correct
         TODAY; the report's hypothesis direction was inverted (it assumed www canonical).
         The in-window split likely reflects the 2026-07-10 VPS migration changing redirect
         behaviour mid-window; expect consolidation onto non-www. No action; monitor.

      **Scheduled Run #1 — Operational gate PASS. Analytical-rule defects discovered during
      external review. Recommendations remained contained by the approval gate. Corrections
      required before Run #2.**
      - Gate evidence: standing-incidents table honored both cases without re-raising; D#8
        rejection cited, not re-proposed; D#7 enforced in-body (staging Woo zeros explicitly
        discarded); €2.70/3 conversions reported with the tracking-gap caveat; ads/PageSpeed
        outages reported as blocked, not hallucinated; www/non-www finding graded OBSERVATION
        medium-confidence with verification steps (verified same day: 301 enforces non-www
        post-migration); no autonomous production change of any kind.
      - Analytical defects (review 2026-07-13, all contained by the approval gate — none
        executed): CTR-optimisation recommended for an EXPIRED Tour de Girona edition (no
        commercial-state check); CTR benchmarks presented as quantified losses; "all data
        collected" while four sources were unavailable; order IDs unmasked; purchase metrics
        reported as bare "conversions"; findings promoted toward causes (also committed by
        both reviewers during analysis — hence the rule).
      - Corrections: the seven RECOMMENDATION & REPORTING rules + FINDINGS-ARE-NOT-CAUSES
        calibration rule, encoded in prompts and pinned by tests/test_report_rules.py.
        A manual rerun validates the corrected rules (does NOT count toward this gate);
        Run #2 is not clean if it repeats any listed defect.
      - **Manual validation rerun #1 (2026-07-13): materially improved, not clean.** Honored:
        commercial-state fail-safe (eMTB past event → routing; TdG → refused to draft without
        state confirmation — correct at current tooling; mechanical lifecycle classification is
        the Site Intelligence module, post-gate), CTR-as-heuristics, completeness wording,
        conversion destinations, approval gate. Failed: order IDs unmasked (→ fixed
        MECHANICALLY in the pipeline, 53717→5xxxx, tested); "Week of" future date invented
        (→ dates now computed in code, Europe/Madrid, injected into the task); noindex advice
        included robots.txt — technically wrong and harmful (→ prompt rule + deterministic
        lint warning); purchase match implied without being performed (→ "not
        transaction-matched" rule); PageSpeed-quota specifics and "primary organic revenue
        gap" overclaimed (findings≠causes — graded against Run #2). Also added:
        `weekly-report --validation` (distinct ledger kind `weekly-report-validation`,
        MANUAL VALIDATION header + email subject prefix, "does not count toward the gate"
        stamp) and a provenance header (profile · analytics source · connector env).
        **A second manual validation rerun (`--validation`) must be clean on the mechanical
        rules before scheduled Run #2 counts.** Neither manual run counts toward the gate;
        manual runs on 2026-07-13 are distinguishable in the ledger by kind/timestamp.
      - **Manual validation rerun #2 (2026-07-13, `--validation`): IMPROVED, NOT CLEAN**
        (grade corrected after third external review — the initial same-day "PASS" was
        premature). **Held:** computed dates used verbatim; IDs masked (acknowledged
        in-report); MANUAL VALIDATION labels; past events gated with routing CTAs; TdG
        fail-safed pending state confirmation; "not transaction-matched" wording exact;
        non-www finding kept unproven; robots.txt advice correct; cross-run note dedup.
        **Deterministic defects (all platform-side, all fixed same day with tests):**
        window was 29 days labelled "28" (off-by-one, now days=27 + inclusive-count test);
        lint false-positive on anti-robots.txt advice (negation-aware); model preamble
        shipping "All data collected" chatter (stripped). **Semantic misses (prompt rules
        added; graded against Run #2):** "95% pre-fix" estimated not computed (→ show-your-
        arithmetic rule); "consider noindex once closed" for TdG contradicted the
        historical-asset strategy (→ historical-assets-stay-indexed rule); obsolete GSC
        preferred-domain check + "recover ~1,414 impressions" fabricated-impact language
        (→ cite-approved-specs rule, no quantified fix impact, no retired features);
        improvised /Word-Word/NUMERICID production pattern instead of citing D#2's approved
        WP-02 matcher; GA4 landing pages described as proving crawlability (violates the
        deployed attribution rule). Masked-ID collision (two orders → same 5xxxx) is a
        DELIBERATE trade: privacy over distinguishability in emailed reports.
        **No third manual rerun** — deterministic fixes are unit-tested; semantic rules are
        graded live. **Scheduled Run #2 counts on its own merits and is not clean if it
        repeats any listed miss.**
      - **Review round 4 disposition (2026-07-13):** contamination percentages are
        COMPUTED-OR-OMITTED (correction accepted: the fix date is case data, not Site
        Intelligence — code computation lands with Memory 2.0 keyed `fix_date` facts; until
        then the model states dates, never percentages). Added TECHNICAL CLAIMS CALIBRATION
        rules + fixtures: 429 proves only itself (no quota stories); no live-status (404/410)
        claims without an in-run test and no comparative de-indexing speed claims; noindex
        verification = direct meta robots / X-Robots-Tag fetch (GA4 sessions only trigger it);
        CWV = contributing page-experience signals, never "ranking eligibility"; masked
        transactional URLs aggregated by pattern, no identical duplicate rows. Preamble test
        now asserts the emailed body BEGINS with the approved header. Profile identity =
        owner config: `TC_SITE_NAME=Tossa Cycling` in the VPS .env (examples already correct).
        **A third manual `--validation` rerun after this deploys + the .env edit grades
        semantic quality only — the mechanical layer is closed.**
      - **Manual validation rerun #3 (2026-07-13, `--validation`): SEMANTIC PASS — 9 of 10
        rules held; manual validation cycle CLOSED.** Held: computed-or-omitted ("~5 of 28
        days", no invented %); 429 calibration verbatim ("cause unverified; retry with
        backoff"); historical-assets-stay-indexed (TdG explicitly "not noindexing");
        spec citation ("reference D#2 specification"); www/non-www led with the benign
        hypothesis + verification-first; "not transaction-matched"; CWV phrasing;
        D#6 verify-then-execute; audit-before-draft sequencing. Analysis quality up:
        discovered TdF-2026-Girona query interception on the TdG page and brand-query CTR
        dilution on the carretera page (self-correcting an earlier overclaim). **One
        violation:** the comparative 404-vs-410 de-indexing speed claim + "eroding
        reputation signal" (rule was live) — now ALSO caught deterministically by lint;
        graded against scheduled Run #2. One platform lint false-positive ("is not the
        correct method" phrasing) — negation handling generalized, fixtures added.
        **No further manual reruns. The next report that matters is the scheduled one.**
      - **Review round 5 disposition (2026-07-13):** items 1–2 (lint negation, 404-vs-410)
        were already fixed in PR #43 before the review arrived — the reviewer grades the
        report artifact, which lags repo HEAD (Reviewer Council evidence packets must carry
        the commit hash). New rules adopted with fixtures: positions are ordinal (absolute
        differences, no ratios, no fixed page boundaries); URL Inspection inspects URLs not
        queries (query→page via GSC query+page dimensions or SERP check); Direct traffic is
        never indexing evidence; partial boundary days stated honestly. Rerun #3 stands as
        mechanically successful, semantically 9/10. **Patch batch complete — reporting
        system frozen until scheduled Run #2. Human time now goes to D#2, D#6, WP-04.**
      - Known cosmetic defect: header banner reads "default · STAGING" while body data is
        production GSC/GA4 — profile label vs data provenance; covered by the Memory 2.0 /
        console provenance-label spec.
- [ ] Zero production writes during the entire release.
- [ ] Decision logged: "Release 0.3 validation complete — proceed to 1.0 production shadow mode."

The checklist decides the transition — not enthusiasm, not schedule.
