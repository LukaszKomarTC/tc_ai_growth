# Work Package #1 — Analytics Recovery

- **From:** case `TRK-20260706-050158` · decision **D#3 (approved 2026-07-06)**
- **Objective:** restore trustworthy revenue tracking. Until this lands, every channel ROI/ROAS
  number is unmeasurable ("unknown", not "zero").
- **Owner:** Łukasz / dev · **Environment:** PRODUCTION WordPress (`tossacycling.com`) —
  a planned maintenance session, not a casual edit. **Estimated:** 2–3 h.

## Tasks

1. [ ] WooCommerce → Orders: verify orders **50662, 53385, 53252, 53028, 53717** exist as real
       completed orders (sizes the gap; 15 min).
2. [ ] WooCommerce → Settings → Advanced → **Order Attribution**: confirm enabled.
3. [ ] Place a test order (or reach `/en/pedido/order-received/` on a real one) with
       **Tag Assistant / GA4 DebugView** open: does the `purchase` event fire with
       `transaction_id`, `value`, `currency`?
4. [ ] If not firing: inspect **GTM container** — is the purchase tag present and triggered on
       the order-received page?
5. [ ] Check the **consent banner**: if it blocks GTM/GA4 before interaction, purchase events
       from consent-declining users never arrive → implement Consent Mode v2 or a server-side
       purchase event.
6. [ ] Confirm revenue appears in **GA4 Realtime/DebugView**, then in standard reports.

## Acceptance criteria (ALL required)

- Test purchase visible in GA4 with correct value/currency.
- WooCommerce Order Attribution returns non-empty `by_source`.
- The next weekly report shows non-zero conversions (or an explained, dated start point).

## Record-keeping (after verification, not before)

```bash
sudo -u tcgrowth /opt/tc_ai_growth/app/.venv/bin/python -m tc_growth.cli case-note TRK-20260706-050158 "WP-01 executed <date>: <what was wrong>, <what was changed>, purchase event verified in GA4 DebugView."
sudo -u tcgrowth /opt/tc_ai_growth/app/.venv/bin/python -m tc_growth.cli decision-outcome 3 worked "GA4 purchase event firing; revenue visible"
```

The next scheduled report acknowledging this instead of re-recommending it = the "case update
after manual action" validation box.
