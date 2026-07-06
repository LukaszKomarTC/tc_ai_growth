# Work Package #3 — Order Pages noindex

- **From:** case `TRK-20260706-050158` · decision **D#6 (approved 2026-07-06)**
- **Objective:** stop Google indexing order-confirmation/payment URLs
  (`/en/pedido/order-received/<id>`, `/en/pedido/order-pay/<id>`) — a privacy leak (order IDs in
  search) and index pollution. Found by the 2026-07-06 mid-week report.
- **Owner:** Łukasz / dev · **Environment:** PRODUCTION WordPress. **Estimated:** 15 min.
  Convenient to do in the same session as WP-01 (same admin area).

## Tasks

1. [ ] Preferred: Yoast → confirm WooCommerce checkout/account pages are set to noindex, or add
       an `X-Robots-Tag: noindex` / robots meta rule covering the `/pedido/` (and `/en/pedido/`)
       path pattern.
2. [ ] Verify: view source of an order-received URL → `noindex` present (both languages).
3. [ ] Optional: GSC removal request for the handful of already-indexed order URLs.

## Acceptance criteria

- Order-received/order-pay pages emit noindex in both language URL forms.
- Checkout flow itself untouched and functioning (place a test booking).

## Record-keeping

```bash
sudo -u tcgrowth /opt/tc_ai_growth/app/.venv/bin/python -m tc_growth.cli case-note TRK-20260706-050158 "WP-03 executed <date>: noindex live on /pedido/ patterns, verified in page source both languages."
sudo -u tcgrowth /opt/tc_ai_growth/app/.venv/bin/python -m tc_growth.cli decision-outcome 6 worked "order pages noindexed"
```
