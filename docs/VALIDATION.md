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
- [ ] THREE consecutive clean Mondays: ____-__-__ · ____-__-__ · ____-__-__
      (clean = no calibration failure, no duplicate case, no false critical, no re-proposed
      decided item).
- [ ] Zero production writes during the entire release.
- [ ] Decision logged: "Release 0.3 validation complete — proceed to 1.0 production shadow mode."

The checklist decides the transition — not enthusiasm, not schedule.
