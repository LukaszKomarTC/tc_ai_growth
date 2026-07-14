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

---

## Execution record (2026-07-14)

**D#6 EXECUTED and VERIFIED.** Implemented via the Snippets plugin (`wp_robots` filter,
noindex on the `order-received` and `order-pay` WooCommerce endpoints; pages stay crawlable
so the directive is visible — never robots.txt). Independent external verification (repo
session, 2026-07-14): `/en/pedido/order-received/` now serves
`<meta name='robots' content='noindex, follow' />`; homepage control unaffected
(`index, follow`). Pre-check the same day had confirmed NO robots meta was present before
the fix. Remaining: watch the /pedido/ URLs drop from GSC coverage over coming weeks.
