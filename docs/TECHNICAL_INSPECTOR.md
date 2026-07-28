# Technical Inspector

**Purpose:** continuously verify that the site's *implementation* matches a known-good baseline —
core, plugins, themes, snippets, config, cron, users — and alert on drift. It generalizes the
snapshot-and-diff discipline the platform already applies to content/structure (WP-06) to the
*technical* layer.

**Origin:** `INC-2026-07-27`. An 8-day WordPress compromise (spam-mailer + RCE) ran undetected
because nothing was watching the filesystem for planted code or the admin table for new
accounts. The manual forensics that eventually surfaced it — `wp core/plugin verify-checksums`,
hex-suffix shell-name scans, PHP-in-uploads/mu-plugins, kit-fingerprint greps, admin-set diff —
are exactly what an Inspector automates. **The July incident is the Inspector's first acceptance
fixture: run against the compromised state, it must fire on every planted artifact.**

## v0 — external integrity monitor (shipped)

`orchestrator/scripts/wp-integrity-scan.sh` — a dependency-free shell script that runs the
incident's detection checks on a schedule and emails **only on a finding**. Read-only. This is a
deliberate stopgap: it delivers the day-one value (would have caught INC-2026-07-27 on July 19)
while the real Inspector is built, and it also serves as the monitoring automation that closes
INC-2026-07-27's monitoring window.

Checks: core checksums · repo-plugin checksums · hex-suffixed PHP anywhere · PHP in
uploads/mu-plugins · known-kit fingerprints · administrator-set drift · wp-config injection
markers.

### Install (on the VPS)
```bash
install -m 0750 orchestrator/scripts/wp-integrity-scan.sh /usr/local/bin/wp-integrity-scan.sh
# dry-run once (should print nothing and exit 0 on a clean site)
/usr/local/bin/wp-integrity-scan.sh; echo "exit: $?"
# schedule daily 04:17 (root crontab)
( crontab -l 2>/dev/null; echo '17 4 * * * /usr/local/bin/wp-integrity-scan.sh' ) | crontab -
```
Config via env in the cron line if needed: `TC_SITE_DOCROOT`, `TC_ALERT_EMAIL`,
`TC_EXPECT_ADMINS` (sorted comma-joined admin IDs — update when you legitimately add/remove an
admin, otherwise the drift check will alert).

### v0 limitations (honest)
- Single-site, hard-coded expectations (the real Inspector is per-profile, config-driven).
- Signature/pattern-based — the incident *proved* signatures miss variants; v0 mitigates by
  combining checksum verification (catches ANY core/repo-plugin change) with pattern scans, but
  it is not a substitute for the snapshot-diff model below.
- Alerts by email only; no case creation, no history, no dashboard.

## Toward v1 — the real Inspector (roadmap)

Per the Evidence Platform / Master-Roadmap specs, the full Inspector is a **per-profile,
snapshot-and-diff** capability (Python, in the platform, governed by the phase gate):

- **Snapshot** every technical surface with hashes + metadata: core/plugin/theme inventory &
  versions, mu-plugins, snippets/functions.php, WP + system cron, Action Scheduler, config,
  users & application passwords, DB health, runtime, server, certs.
- **Diff** each snapshot against its predecessor AND against an *approved* baseline (the WP-06
  three-state model: observed / approved / unexplained drift).
- **Case on drift** — an unexplained change opens an investigation case (like INC-2026-07-27
  would have), with evidence, not just an email.
- **Verify, don't assert** — carries the incident's hardest lesson: *timestamp-hunting caught
  what signature-hunting missed.* The Inspector must diff state over time, not only match
  signatures, precisely because a competent attacker varies signatures (proven July 19–27).

Acceptance fixtures (from the real incident): given the compromised-state filesystem, the
Inspector must detect — the mu-plugins nest, the fake plugin, the core shells, the wp-config
injection, the rogue admins, and the uploads shells — and must NOT false-positive on the legit
premium plugins (edition-mismatch) or the WooCommerce app-password.
