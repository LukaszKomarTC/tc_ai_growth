# Work Package #2 — Spam URL Cleanup (410 + GSC removals)

- **From:** case `INC-2026-02-01` (monitoring) · decision **D#2 (approved 2026-07-06)**
- **Objective:** accelerate deindexation of the ~50 residual tobacco/vape doorway URLs (verified
  404/dead since 2026-07-05; still drawing impressions/clicks from stale index entries).
- **Owner:** Łukasz / dev · **Environment:** PRODUCTION (shared IONOS hosting — `.htaccess`).
  **Estimated:** 30–45 min. **Run after WP-01** (independent, lower priority than revenue
  visibility).

## Tasks

1. [ ] Add a 410 rule to production `.htaccess` for the doorway pattern — two-segment URLs
       ending in a 6-digit id. Test on a *staging copy of the rule logic first* if unsure:

   ```apache
   # TC: gone-forever spam doorway pattern /Any-Hyphenated-Title/123456
   RewriteEngine On
   RewriteRule ^[A-Za-z0-9%._-]+/[0-9]{6}/?$ - [G,L]
   ```

2. [ ] Verify with 3 known spam URLs (e.g. `/Cigarette-Price-In-India.../628548`) → **410**,
       and 5 real URLs (home, `/alquiler_bicicletas/`, `/en/...`, a product, an order page)
       → unchanged.
3. [ ] GSC → Removals: submit the top ~20 offending URLs (highest impressions).
4. [ ] Never 301 these URLs anywhere.

## Acceptance criteria

- Spam samples return 410; all legitimate routes unaffected (checkout untouched — verify a
  test booking still works).
- GSC removal requests submitted.
- Weekly GSC spam-impression trend continues to zero over the following weeks.

## Record-keeping

```bash
sudo -u tcgrowth /opt/tc_ai_growth/app/.venv/bin/python -m tc_growth.cli case-note INC-2026-02-01 "WP-02 executed <date>: 410 rule live, verified on N samples, top-20 GSC removals submitted."
sudo -u tcgrowth /opt/tc_ai_growth/app/.venv/bin/python -m tc_growth.cli decision-outcome 2 worked "410 serving, removals submitted"
```
