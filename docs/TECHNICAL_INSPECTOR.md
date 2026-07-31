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

## Scope boundary (what the Inspector must NOT become)

The Inspector **detects drift and produces evidence. It does not remediate.** No autonomous
malware removal, no production repair, no "auto-quarantine." It is not a home-built replacement
for Wordfence / Cloudflare / EDR / a SOC — those are bought, not built, and building them would
misspend the platform's limited capacity on its non-purpose (the platform's purpose is growth,
operations, and evidence). The Inspector's value is that it *notices and reports* drift early;
a human decides what to do. This boundary is deliberate, matching the platform's
FORBIDDEN-capabilities discipline.

## v0 — external integrity monitor (detection validated; operational acceptance PENDING)

`orchestrator/scripts/wp-integrity-scan.sh` — a dependency-free shell script that runs the
incident's detection checks and, on a finding, logs + prints + best-effort-emails. Read-only.
A deliberate stopgap delivering day-one detection value while the real Inspector is built.

**Honest status — three separate things, do not conflate:**
1. **Detection logic works (manual run):** ✅ validated (`exit 0` on the clean site after
   tuning out three benign false positives).
2. **Runs correctly under cron** (minimal PATH/env/cwd): ⬜ NOT yet acceptance-tested.
3. **A real finding reaches a human via a reliable channel:** ⬜ NOT yet — local `mail` is
   absent and outbound :25 is blocked; alert delivery must be wired to the platform notifier.

So v0 is **"manual scan passes,"** not "live." It is done only when the v0.1 checklist below
passes.

Checks: core checksums · repo-plugin checksums · hex-suffixed PHP anywhere · PHP in
uploads/mu-plugins · known-kit fingerprints · administrator-set drift · wp-config injection
markers.

### Source of truth & deployment (ONE script, no drift)

The **repository copy `orchestrator/scripts/wp-integrity-scan.sh` is the single source of truth**,
versioned by git. It is *deployed* atomically to a controlled release path
(`/usr/local/bin/wp-integrity-scan.sh`), and the deployed copy is **never hand-edited** — every
change goes through the repo and is redeployed. Record which commit a deployment came from so the
running script is always traceable to a reviewed revision.

Critically, **both consumers run the same deployed file**: the cron schedule *and* the Operations
Console. The Console's `run_integrity_scan` op invokes the script via `TC_INSPECTOR_SCRIPT`, which
in production **must point at the deployed path**, not a developer working tree — otherwise cron
and the Console could run two different versions. Set it in the Console's environment:
`TC_INSPECTOR_SCRIPT=/usr/local/bin/wp-integrity-scan.sh`.

```bash
# Deploy the repo version atomically, stamping the commit it came from.
COMMIT=$(git rev-parse --short HEAD)
install -m 0750 orchestrator/scripts/wp-integrity-scan.sh /usr/local/bin/wp-integrity-scan.sh
logger -t tc-inspector "deployed wp-integrity-scan.sh @ $COMMIT"   # traceable to a reviewed revision
# dry-run once (should print nothing and exit 0 on a clean site)
/usr/local/bin/wp-integrity-scan.sh; echo "exit: $?"
# schedule daily 04:17 (root crontab) — same deployed path the Console uses
( crontab -l 2>/dev/null; echo '17 4 * * * /usr/local/bin/wp-integrity-scan.sh' ) | crontab -
```
Config via env in the cron line if needed: `TC_SITE_DOCROOT`, `TC_ALERT_EMAIL`,
`TC_EXPECT_ADMINS` (sorted comma-joined admin IDs — update when you legitimately add/remove an
admin), `TC_INSPECTOR_LOG` (default `/var/log/tc-inspector.log`).

**Findings are always written to the log file and printed to stdout, and additionally emailed
best-effort.** So a finding is never hidden by a missing MTA (the first dry-run exposed exactly
that: `mail` was absent, and the alert would have gone nowhere). For real email delivery either
`apt install bsd-mailx` and relay the local MTA through IONOS submission (:587, since outbound
:25 is blocked on this host), or — preferred — wire Inspector alerts into the platform's
existing notifier during the branch work. Until then, findings land in the log file reliably.

### False-positive discipline (learned on first run)
The v0 dry-run flagged two *benign* things, both now fixed — because a monitor that cries wolf
gets muted:
- **`shopkeeper-extender`** legitimately mismatches the free wp.org edition on every file. The
  plugin check now flags **only "should not exist" (extra/planted files)**, not "does not match".
- **Our own `zzz-tc-*` hardening mu-plugins** are allowlisted so the "PHP in mu-plugins" check
  doesn't flag the platform's own code.
- **WP All Import's `uploads/wpallimport/functions.php`** is a legit code-exec feature that ships
  empty — now flagged **only when non-empty** (turning a false positive into a real check: an
  attacker writing a shell there makes it non-empty, so it alerts; the empty default stays quiet).

These three tuning passes are themselves the argument for the **v1 baseline model**: rather than
maintaining a growing list of "known-legit exceptions," v1 hashes the current *clean* state and
alerts on CHANGES — so a legit-but-unusual file is learned once, and only genuine drift fires.

**Exception discipline (mandatory).** Every exception is *narrow and documented* — never a
whole-directory exempt (that just hands an attacker a blessed hiding place). Each carries: exact
path, expected owner/perms, expected state (empty / known hash), reason, date added, and a
review trigger. Registry:

| path | expected | reason | added | review trigger |
|---|---|---|---|---|
| `wp-content/uploads/wpallimport/functions.php` | empty (0 bytes) | WP All Import custom-functions feature, ships empty; verified benign in INC-2026-07-27 | 2026-07-28 | **fires if non-empty** (attacker write OR owner adds custom functions) |
| `wp-content/mu-plugins/zzz-tc-*.php` | platform-authored hardening | our own batch/v1 block etc. | 2026-07-28 | any `zzz-tc-*` change → re-verify against the repo copy |

### v0.1 — operational acceptance (the checklist that makes v0 "done")

Bounded incident-hardening; complete ONLY these, then stop:
- [ ] runs successfully under cron's minimal environment (not just an interactive shell)
- [ ] records each run: timestamp, exit code, result (to the log; later the run ledger)
- [ ] delivers findings through the **platform's existing notifier** (email via IONOS :587 /
      Telegram) — not the missing local `mail`
- [ ] positive-path tested with a **harmless controlled fixture** that is guaranteed to trigger,
      alert verified to arrive, fixture removed, next run returns 0
- [ ] notification-failure path tested separately (a finding must never be silently lost)
- [ ] overlapping runs prevented (flock)
- [ ] log retention bounded (rotation / size cap — never fills the disk)

**Cron timing note:** the cron line `17 4 * * *` is **UTC** → ~06:17 Europe/Madrid in summer
(DST), not 04:17 local. Acceptable, but intentional and documented here.

### v0 limitations (honest)
- Single-site, hard-coded expectations (the real Inspector is per-profile, config-driven).
- Signature/pattern-based — the incident *proved* signatures miss variants; v0 mitigates by
  combining core-checksum verification (catches ANY core change) with pattern scans, but
  dropping plugin "does not match" means **modified-file injection into a repo plugin** is only
  caught if it carries a known fingerprint. The snapshot-diff model below closes that gap.
- Alerts are log-file + best-effort email; no case creation, no history, no dashboard.

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
