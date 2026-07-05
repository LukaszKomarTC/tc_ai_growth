# Incident: Tobacco-spam listings on tossacycling.com (Merchant Center)

- **ID:** INC-2026-02-01
- **Opened:** 2026-02 (first observed in Search Console data 2026-02-12)
- **Closed:** 2026-07-05
- **Status:** **Resolved — contained.** Root vector no longer present; not positively identified.
- **Severity:** Medium (reputation / SEO surface). **No impact** on rentals, checkout, payments, or the WordPress filesystem.
- **Systems:** Google Merchant Center (production `tossacycling.com`), Google for WooCommerce plugin.
- **Not involved:** the VPS/staging (`dev.tourdegirona.com`), the booking plugin, WooCommerce orders.

This is the first entry in the agent's decision log. It is written in the house style:
**Observations** (what the data shows) are kept separate from **Hypotheses** (what we inferred),
and every hypothesis that was later retracted is recorded *with the evidence that killed it* — so
the reasoning trail, not just the verdict, is preserved.

---

## Summary

Tobacco/vape/pharma product URLs appeared under the `tossacycling.com` domain in Google. They were
**Merchant Center feed listings pointing at phantom URLs** on the verified domain — not real pages on
the WordPress site (the URLs 404 to every user-agent, including Googlebot). The listings arrived via
**account-level access to Merchant Center** (a supplemental feed or unauthorized access), *above* the
WordPress layer. The account is now clean (no rogue products, no active feed) and has been quiet since
~2026-03-29. The exact entry vector was never positively identified because it was already gone by the
time we investigated. Recurrence is guarded by securing the Google account that owns Merchant Center.

## Timeline (observations)

| Date | Observation | Source |
|---|---|---|
| 2026-02-12 | Tobacco-related URLs first appear in GSC performance data | Search Console (page_filter + date dimension) |
| ~2026-02-18 (± days) | Owner removes the rogue products in Merchant Center and uninstalls Google for WooCommerce | Owner report |
| 2026-02-27 → 03-02 | Impressions **peak** — *after* the removal | Search Console |
| ~2026-03-29 | Sharp **cliff** in impressions | Search Console |
| 2026-03-29 → 07-01 | Long decay tail; URLs return 404 (normal + Googlebot UA) | curl UA test; GSC URL Inspection (not indexed, last crawl 2026-07-01) |
| 2026-07-05 | Merchant Center confirmed clean: no rogue products, no active feed | Owner check |

Corroborating observations: WordPress product-ID ceiling frozen (~769k, no new page generation);
no spam pages found on the filesystem; GA4 shows no conversions/revenue tied to the spam URLs.

## Hypotheses raised and retracted

Recording these deliberately — the value of the investigation was as much in the wrong turns as the
right answer, and future cases should expect the same.

1. **"The site is serving hacked spam pages."** — *Retracted.* Overclaimed active compromise from
   the presence of URLs alone. The URLs 404 to all user-agents and no spam files exist on disk; the
   listings were feed phantoms, not served pages.
2. **"The ~Mar 29 cliff was caused by migration to the clean VPS."** — *Retracted.* Production
   `tossacycling.com` was never migrated to the VPS (only staging was). The mechanism doesn't exist.
3. **"It's not Merchant Center."** — *Retracted.* Direct owner evidence (rogue tobacco products
   visible and removable in Merchant Center) contradicted this. It *was* Merchant Center.
4. **"The owner's Feb 18 removal is the cliff."** — *Retracted.* Impressions peaked ~Feb 27–Mar 2,
   *after* the removal, and the cliff was ~6 weeks later. The removal did not cut the source — strong
   evidence the products were pushed at the account/feed level, which the plugin uninstall never touched.

## Conclusion (calibrated)

- **What it was:** historical tobacco-spam via Merchant Center account/feed access on production.
  Contained. Not a live compromise. **Confidence: medium-high.**
- **What the WordPress site was:** most likely never compromised; the 404s are best explained as
  feed phantoms pointing at the verified domain. A light filesystem check remains a low-priority
  tidy-up, not a live concern.
- **What caused the ~Mar 29 cliff:** **unknown.** Leading (unverified) candidate is a Merchant Center
  account suspension for a prohibited category (tobacco), which produces exactly this sharp-cliff shape.
  Not asserted as fact — the account is clean now, so the suspension state was not captured.
- **What actually prevents recurrence:** securing the **Google account that owns Merchant Center**
  (2FA + review connected apps). The vector lived at the Google-account level, above WordPress, so no
  WordPress-side control addresses it.

## Close conditions (owner actions)

1. Confirm **2FA is enabled** on the Google account that owns Merchant Center; revoke unfamiliar
   connected apps.
2. Keep the spam URLs returning **404/410** — never 301-redirect them to real pages.
3. Monitor Merchant Center + GSC weekly for ~4 weeks. If tobacco listings reappear → **reopen**.

## Lessons for the agent

- Presence of bad URLs is an **observation**, not a conclusion of compromise. Test the serving layer
  (UA fetch, URL Inspection, filesystem) before naming a cause.
- When a remediation "obviously" explains a timeline, **check the dates** — the Feb 18/Mar 29 mismatch
  was the single most informative fact and it falsified the tidy story.
- Distinguish *contained* from *root-caused*. This incident is safely closable while its exact entry
  vector remains unidentified, because the vector is verifiably no longer present.
