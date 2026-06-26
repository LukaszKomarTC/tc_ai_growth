# Runbook

## What the system can and cannot do (by phase)

| | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Read SEO/ads/analytics data | ✅ | ✅ | ✅ |
| Weekly opportunity report | ✅ | ✅ | ✅ |
| Create WordPress SEO/content **drafts** | ✅ | ✅ | ✅ |
| Draft Google/Meta ad copy, GBP posts | — | ✅ | ✅ |
| Publish approved SEO changes | — | — | ✅ (approved only) |
| Change ad budgets | — | — | bounded + `always_ask` only |
| Change price / availability / booking / checkout | ❌ never | ❌ never | ❌ never |

The phase is set in code where the runtime is invoked (`Phase.READ_ONLY` by default in the
weekly report). Raising the phase is a deliberate code/config change, reviewed by a human.

## Approving drafts

1. Drafts appear in WordPress as draft posts / native revisions (SEO), draft "Growth Drafts"
   (ad copy / GBP posts — the `tc_growth_asset` type), each with a `_tc_growth_rationale`.
2. Review the diff and the rationale; edit if needed; publish/use from the WordPress editor.
3. The connector audit table (`wp_tc_growth_audit`) records every read and draft created.

### Phase 3: letting the agent apply an SEO draft (triple-gated)

`publish_seo_draft` is the only tool that changes the live site. It can run **only** when all
three hold:

1. **Phase** — the orchestrator is invoked at `Phase.CONTROLLED_EXECUTION` (a code/config change).
2. **Confirmation** — the runtime was given a human-confirmation hook; an autonomous/scheduled run
   has none, so the tool is refused.
3. **Human approval in WordPress** — on the SEO draft's edit screen, the **"TC Growth — Approve to
   apply"** checkbox is ticked. That flag (`_tc_growth_approved`) can only be set by a user with
   `publish_posts`; the contributor-level agent user cannot self-approve.

Applying then copies title/slug/meta-description to the live source page and trashes the draft.
Price, availability, booking, and checkout are never touched.

## Kill switch (stop everything fast)

1. **Pause the schedule:** `ant beta:deployments pause --deployment-id <id>`.
2. **Cut runtime access:** revoke/rotate `ANTHROPIC_API_KEY`.
3. **Cut data access:** revoke the agent's WordPress Application Password and rotate
   `TC_GROWTH_SIGNING_KEY`; revoke Google/Meta OAuth credentials.
4. **Disable the connector:** deactivate the `tc-growth-connector` plugin (rentals/checkout
   are unaffected — it is fully separate from the booking plugin).

## Guardrail verification (run after any change)

**Run `make check` before every push.** It mirrors CI exactly: an editable install
(`pip install -e ".[dev]"` — exercises the packaging/build backend), an import smoke check,
the full pytest suite (phase gate, forbidden capabilities, portability invariant, runtime
driver, delivery routing), and `php -l` over the connector.

```sh
make check
```

A plain `cd orchestrator && pytest -q` runs the tests but does **not** exercise the build — it
will miss packaging errors (e.g. setuptools flat-layout discovery) that CI catches. Use
`make check` as the gate.

Then attempt a draft tool in `Phase.READ_ONLY` and confirm it is blocked and logged.

## Bottleneck watch

- **Google Ads developer token** and **Meta app review** are the long-lead approvals. Until
  granted, those tools return clear "not provisioned" errors and the report lists them under
  *Pending integrations* — the rest of the system keeps working.
