# Validation Checklist — Phase 3B (staging)

The gate between "built" and "trusted to act". Work through every box against **staging**
(`dev.tourdegirona.com`); tick with a date + one line of evidence (run id, case ref, or screenshot).
Nothing advances to Phase 4 until ALL boxes are green **and** two consecutive Monday reports run
clean (no calibration failures, no duplicate cases, no re-proposed decided items).

How to run a draft test: invoke the run at DRAFTS phase (supervised, from the CLI) so
`wp_create_seo_draft` / `wp_create_product_revision` are admitted by the gate; the connector only
reaches staging. Review each result in staging wp-admin.

## Content (drafts at DRAFTS phase, staging connector)

- [ ] **SEO draft — Spanish rental page** (`/alquiler_bicicletas/`, post 13699): title/meta/H1
      draft created as a revision, never published.
- [ ] **Product revision — Scott Addict 50**: description draft stored as a revision.
- [ ] **Landing/tour draft — Tour de Girona event page**: CTR-focused title/meta draft.
- [ ] **Homepage title draft** ("Home" → brand+location).

## Memory

- [ ] **Opens the correct case** for a genuinely new finding (right category prefix, numeric
      confidence, evidence in body).
- [ ] **Does not reopen a resolved case** — references it by ref with current status instead.
- [ ] **case_read consulted** before judging new-vs-known (visible in run tool calls).
- [ ] **Links decisions to cases** (decision_log carries the case ref).
- [ ] **Updates confidence with a basis** — visible in the case journal and the dashboard
      confidence-evolution ladder.
- [ ] **References a previous investigation** when the same topic recurs.

## Workflow (approval round-trip)

- [ ] **Draft generated → human reviews** in staging wp-admin.
- [ ] **decision-approve** flips the proposal's status; case journal records the human action.
- [ ] **decision-reject** settles a proposal; the NEXT run does not re-propose it.
- [ ] **Case update after manual action**: human applies a change, notes it via case-note; the
      next report acknowledges it instead of re-recommending it.
- [ ] **Dashboard reflects all of the above** (statuses, journal, decision queue).

## WordPress (draft fidelity, staging)

- [ ] **Draft appears correctly** in wp-admin (right post, right type).
- [ ] **Revision formatting preserved** (no mangled HTML/blocks).
- [ ] **Images/metadata untouched** by the revision.
- [ ] **Approval meta box** behaves (only publish_posts-capable users can approve) and shows the
      full proposal (meta description + rationale) so the reviewer sees what they approve.
- [ ] **qTranslate x Yoast at apply time**: after the first approved apply, view BOTH language
      URLs' page source — the meta description tag must render per-language, never the raw
      `[:es]…[:en]…[:]` string. (Requires the qTranslate-XT Yoast integration module if raw
      tags appear.)
- [ ] **Nothing published automatically** — post status unchanged by every test above.

## Sign-off (Release 0.3 → 1.0 gate; see docs/STATUS.md for the full criteria)

- [ ] All boxes green (dates + evidence above).
- [ ] THREE consecutive clean Mondays: ____-__-__ · ____-__-__ · ____-__-__
      (clean = no calibration failure, no duplicate case, no false critical, no re-proposed
      decided item).
- [ ] Zero production writes during the entire release.
- [ ] Decision logged: "Release 0.3 validation complete — proceed to 1.0 production shadow mode."

The checklist decides the transition — not enthusiasm, not schedule.
