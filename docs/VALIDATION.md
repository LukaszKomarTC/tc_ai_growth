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
- [ ] **Product revision — Scott Addict 50**: description draft stored as a revision.
- [ ] **Landing/tour draft — Tour de Girona event page**: CTR-focused title/meta draft.
- [ ] **Homepage title draft** ("Home" → brand+location).

## Memory

- [x] **Opens the correct case** for a genuinely new finding — 2026-07-06: TRK-20260706-050158
      (TRK prefix, confidence 0.85, order-ID evidence in body), opened by the Monday 05:00 run.
- [x] **Does not reopen a resolved case** — 2026-07-06 mid-week report: Active Case Dashboard
      references INC-2026-02-01 (monitoring) and the closed duplicate as "merged, no separate
      action"; zero new cases opened for known topics.
- [ ] **case_read consulted** before judging new-vs-known (visible in run tool calls).
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
- [ ] **Images/metadata untouched** by the revision. (Test page had no featured image — verify on
      the product-revision test.)
- [x] **Approval meta box** behaves and shows the full proposal — 2026-07-06 screenshot after
      PR #26: bilingual meta description + agent rationale + source link + capability-guarded
      checkbox.
- [ ] **qTranslate x Yoast at apply time**: after the first approved apply, view BOTH language
      URLs' page source — the meta description tag must render per-language, never the raw
      `[:es]…[:en]…[:]` string. (Requires the qTranslate-XT Yoast integration module if raw
      tags appear.)
- [x] **Nothing published automatically** — 2026-07-06: every artifact (50455, 50457) remained
      status=draft; live post 13699 untouched; zero production writes.

## Sign-off (Release 0.3 → 1.0 gate; see docs/STATUS.md for the full criteria)

- [ ] All boxes green (dates + evidence above).
- [ ] THREE consecutive clean Mondays: **2026-07-13 ✅ (operational gate)** · ____-__-__ · ____-__-__
      (clean = no calibration failure, no duplicate case, no false critical, no re-proposed
      decided item).

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
      - Known cosmetic defect: header banner reads "default · STAGING" while body data is
        production GSC/GA4 — profile label vs data provenance; covered by the Memory 2.0 /
        console provenance-label spec.
- [ ] Zero production writes during the entire release.
- [ ] Decision logged: "Release 0.3 validation complete — proceed to 1.0 production shadow mode."

The checklist decides the transition — not enthusiasm, not schedule.
