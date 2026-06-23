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

1. Drafts appear in WordPress as draft posts / native revisions with a `_tc_growth_rationale`.
2. Review the diff and the rationale; edit if needed; publish from the WordPress editor.
3. The connector audit table (`wp_tc_growth_audit`) records every read and draft created.

## Kill switch (stop everything fast)

1. **Pause the schedule:** `ant beta:deployments pause --deployment-id <id>`.
2. **Cut runtime access:** revoke/rotate `ANTHROPIC_API_KEY`.
3. **Cut data access:** revoke the agent's WordPress Application Password and rotate
   `TC_GROWTH_SIGNING_KEY`; revoke Google/Meta OAuth credentials.
4. **Disable the connector:** deactivate the `tc-growth-connector` plugin (rentals/checkout
   are unaffected — it is fully separate from the booking plugin).

## Guardrail verification (run after any change)

```sh
cd orchestrator && pytest -q   # phase gate, forbidden capabilities, portability invariant
```

Then attempt a draft tool in `Phase.READ_ONLY` and confirm it is blocked and logged.

## Bottleneck watch

- **Google Ads developer token** and **Meta app review** are the long-lead approvals. Until
  granted, those tools return clear "not provisioned" errors and the report lists them under
  *Pending integrations* — the rest of the system keeps working.
