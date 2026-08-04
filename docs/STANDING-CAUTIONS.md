# Standing cautions — permanent operational warnings

Facts that must survive every session, summary, and handoff. These are not current state (see
project/HANDOFF.md) — they are standing dangers. Remove an entry only with an owner decision
recorded here.

## ⛔ The compromised backup (DO NOT RESTORE)

A large (~19 GB) server backup from the prior security-incident era (the tobacco-spam
compromise, see INC-2026-02-01 / incident cases in the platform store) contains the COMPROMISED
site state. It is labeled **DO_NOT_RESTORE**. Restoring it would reintroduce the compromise.

- Recorded 2026-08-03 from owner statements during incident sessions; until this line, this fact
  lived ONLY in chat memory — the exact failure mode project/PROTOCOL.md exists to prevent.
- Before ANY restore decision on this server: verify the backup's label/date/location in the
  hosting panel and treat anything from the compromise window as tainted until proven otherwise.
- Clean-state references instead: Git (`main`), the deploy snapshots under `/var/backups/tc-console/`,
  and the release-worktree model — not full-server backup archives from the incident era.

## ⛔ Root Git in the production checkout (incident D5)

Never run `git` as root in `/opt/tc_ai_growth/app` or its worktrees — it rewrites index/object
ownership and breaks tcgrowth-run deploys. Always `sudo -u tcgrowth git -C /opt/tc_ai_growth/app …`.
(Also recorded in WP-CONSOLE-ACCEPTANCE-LEDGER.md D5 and project/PROTOCOL.md; repeated here
because the failure is one habitual keystroke away.)

## ⚠️ Secrets in transcripts

Never paste tokens/passwords into AI chats. It happened once (TC_CONSOLE_TOKEN, ledger F4) and
forced a rotation. Tokens are read on the server (`sudo cat /etc/tc-console.env`) and go straight
into the login form or a password manager.

## ℹ️ Staging WordPress lives on a different domain (intentional)

Tossa Cycling's staging WordPress/WooCommerce host is **dev.tourdegirona.com** — owner-confirmed
2026-08-04. This is deliberate cross-domain staging, NOT a configuration error. Do not "fix"
`TC_WP_BASE_URL` on sight of the unfamiliar domain; the Console truth panel showing it is
correct behavior.
