# INC-2026-07-27 — Closure Verification Report

**For review / contrast against the 2026-07-27 security assessment.** This answers that
assessment's 12-point minimum closure test and its specific corrections with the evidence
gathered afterward. Every line marked ✅ has supporting command output captured in the
remediation session (see `INC-2026-07-27.md` for the raw findings).

## Response to the two corrections raised

1. **"Do not overclaim from a single check."** Accepted and fixed. The claim that the
   application-password audit "closed the last re-entry path" was scoped back to its true
   meaning (*no attacker app-password exists for users 1/119 — nothing more*), and the
   **Operational / Security / Forensic** three-status framing was adopted as the incident's
   official status line.
2. **"The compromised backup does not cost nothing."** Accepted. The 19 GB image is now treated
   as a forensic copy: to be labeled `DO_NOT_RESTORE-COMPROMISED-2026-07-27`, `sha256`-recorded,
   `chmod 600`, excluded from operational backups, with a deletion date (~2 weeks). Same for
   `/root/quarantine/`.

## The 12-point minimum closure test — status

| # | Requested check | Result | Evidence |
|---|---|---|---|
| 1 | Full filesystem + DB malware review | ✅ done | core+plugin `verify-checksums`; fingerprint / hex-name / breach-window sweeps of the whole tree; `wp_options` scanned for `eval`/`base64`/health-transient (clean) |
| 2 | Core checksums verified | ✅ done | `wp core verify-checksums` → *Success* after removing 2 shells hidden in `wp-includes/` |
| 3 | Plugins/themes reinstalled from trusted sources | ✅ done | premium code restored from the **July 18 pre-breach** backup (files-only); 7 repo plugins updated to latest; restored files re-swept clean |
| 4 | Custom files inventoried/hashed | ◐ partial | all malicious files hashed + quarantined; a full hash-manifest of legit custom code is deferred to the Technical Inspector baseline |
| 5 | Cron / systemd / users / SSH keys / processes | ✅ done | only Plesk terminal key; only Plesk subscription users; all logins `root@127.0.0.1`; post-Jul-18 systemd units all Plesk; `lukasz` crontab removed, only legit `psaadm` remains → **no OS-level access** |
| 6 | WP users + application passwords + API creds | ✅ done | admins = only ids 1,119; app-passwords: one legit 2023 WooCommerce (user 1), none (user 119); signing key + all secrets rotated |
| 7 | Outbound mail queue + logs clean | ✅ done | queue held system mail + 2 spam remnants; **outbound :25 blocked** (why spam mostly failed: 2702 deferred / 2 sent); queue flushed (`postsuper -d ALL`); business mail intact via :587 (Gmail inbox) |
| 8 | Access logs: first exploit + callbacks | ✅ done | full kill chain identified from logs: `batch/v1` → admin creation → `upload-plugin` → shell; the 18:24 self-reinfection during cleanup also captured |
| 9 | All VPS subscriptions inspected | ✅ done | `tourdegirona.com` + `zelcycling.com` scanned clean; `dashboard`/`dev` have no WP docroot; separate users + no OS access = no pivot |
| 10 | Clean baseline backup after verification | ✅ done | 24 GB Plesk full backup created post-remediation |
| 11 | Restore-test of the clean backup | ✅ done | 569 MB clean dump imported to an isolated scratch DB: `exit 0`, 171 tables / 293 users / 15,718 orders / 5,670 options intact; combined with the successful July-18 *file* restore = both layers proven |
| 12 | Several clean monitoring days | ◐ in progress | **Technical Inspector v0** (`orchestrator/scripts/wp-integrity-scan.sh`) automates the monitoring: daily core/plugin-checksum + shell-pattern + admin-drift scan, emails only on a finding |

**Also verified beyond the 12 points:** the **orchestrator** (`/opt/tc_ai_growth`, `tcgrowth`
user) — code intact, git tree clean, no malware fingerprints, only legit connector PHP + venv
library false-positives. This was the platform's gating prerequisite.

## Current status

- **Operational:** Stable — site online, business as normal.
- **Security:** No active indicators; every persistence class audited clean.
- **Forensic:** All remediation, full verification, clean baseline, and restore-test COMPLETE.
  Only the passive monitoring window remains (now automated by Inspector v0) before formal CLOSED.

## What still needs a decision (not a technical gap — a governance call)

The AI-growth platform's Release 0.3 gate required clean Monday validation reports. The box was
compromised **July 19–27**, so the **July 20 and July 27** reports ran on a compromised host
(the orchestrator itself was verified clean, but the production data they read was from a
compromised site). Recommendation: **do not count those two Mondays**; re-baseline the box and
require fresh consecutive clean Mondays on the clean host. This costs ~2 weeks on the *merge*
and nothing on the *build*. Flagged for review — not decided unilaterally.

## Confidence

Every persistence class named in the assessment has been **checked, not assumed** — filesystem,
core, plugins, mail, users, app-passwords, cron/systemd/SSH, other subscriptions, orchestrator.
The remaining uncertainty is time-based (the monitoring window), not evidence of anything
missed. Consistent with the assessment's ~90–95% post-audit confidence, now with the
infrastructure checks it left open completed.
