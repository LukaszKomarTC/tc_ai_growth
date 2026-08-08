# WP-U5.2 — the on-host inspection acceptance run (owner-executed)

*U5.1 (PR #85) built the collect → normalize → snapshot → compare → classify foundation. U5.2
(PR #86) added the four real collectors and the Console trigger. U5.2a (this PR) fixed drift
being computed over the measurement rather than the state. This is the on-host run the agent
cannot perform — it needs the VPS, a real journal, a real filesystem and a real WordPress.*

Issue #82 §19 requires the acceptance protocol to be written **before** production installation,
following the U4 pattern. This is that protocol.

**Nothing here is privileged.** U5 adds no sudoers entry, no verb, no root-owned program and no
new escalation. The collectors read as the service account and nothing more; `deploy_release`
stays `enabled=False` and server-refused throughout, exactly as it is today.

## What this run is actually testing

Not "does the page render". The four claims below are the ones a monitoring system fails at
silently, so they are the ones the owner is asked to confirm by eye:

1. **The first reading is a baseline, not a clean bill of health.** A system with no history
   that shows green on day one has told you nothing (§7 / criterion 7).
2. **Every reading names its source, and `unknown` means unreadable — never healthy** (§14, §16).
3. **A second sweep of an unchanged host raises nothing.** This is the criterion the U5.2 code as
   merged would have failed: three of four scopes reported `changed` → `warn` on every sweep,
   because the digest was taken over ages, byte counts and occurrence counts that move on their
   own. Fixed in U5.2a; this run is where it is confirmed against a real host rather than a fake
   one (§7).
4. **Something that really changes is still reported.** A change detector that has been quietened
   passes test 3 and is worthless.

## 0. One-time setup (technical maintainer, terminal, once)

1. **Deploy the merged head** through the existing governed path. No new install step: U5 is
   application code inside the same runtime.
2. **The store migrates itself on first open** (schema v9 → v10, two nullable columns on
   `observations`). It is additive and forward-only; no existing row is rewritten. Nothing to
   run by hand. If a v9 store already holds observations, the first sweep after the upgrade
   compares them the way they were written, so the migration itself cannot report drift.
3. **Set `TC_SITE_DOCROOT` in the Console service's environment**, to the WordPress docroot for
   this profile. Without it `wp.inventory` returns `unknown` — correctly and by design, since
   guessing a docroot would mean inspecting whichever site happens to live at a familiar path
   and filing the result under this profile's name. But it means the run proves nothing about
   WordPress, so set it before the run rather than discovering it during.
4. *(Optional)* `TC_INSPECTOR_LOG` if the v0 integrity scan writes somewhere other than
   `/var/log/tc-inspector.log`.
5. **Confirm the service was restarted** so it is running the deployed code and carrying the new
   environment.

`run_inspection` ships `enabled=True` and `self_service=False`: it is reachable only from the
dedicated Operations Health surface, never as an argument-less call through `/api/execute`. No
registry flip is part of this run.

## 1. Run it — browser only

1. Open the Console over the SSH tunnel, sign in.
2. **Operations Health** → **Run inspection**. That click is the only input. The browser supplies
   no profile, environment, path, unit or command — identity comes from the executing service's
   own configuration, so a sweep launched for one business cannot be filed under another
   (§ amendment 1).
3. Read the page.
4. **Click it a second time**, a few minutes later, having changed nothing on the host.
5. Read the page again. This is the real test.

## 2. What to confirm, in order

### After the first sweep

- [ ] Every scope shows change class **`baseline`** — not `unchanged`. Four scopes are expected:
      `wp.inventory`, `host.capacity`, `platform.services`, `logs.signatures`.
- [ ] The header states the profile and environment, and they are the right ones.
- [ ] Each row's reason is a sentence about *this host*, naming what was read — a docroot, a unit
      name, a journal window with its priority floor, a filesystem path.
- [ ] Any row reading `unknown` says **why** it could not be read, and is **not** shown as
      healthy. `unknown` here is an acceptable outcome; an unexplained `unknown` is not.
- [ ] `logs.signatures` does not claim "no errors observed" unless it also names the unit and the
      24-hour window. (If the unit has never logged, the honest answer is `unknown` — the probe
      read exists so an empty journal cannot be reported as a quiet one.)
- [ ] Open **Evidence** on any row: the stored value is structured and bounded, with no raw log
      tail and no credential. Read it by eye before capturing anything for the record.

### After the second sweep — the one that matters

- [ ] Every scope that was readable both times shows **`unchanged`**, and severity **`ok`**.
- [ ] **In particular `platform.services` and `host.capacity`.** Before U5.2a these were the two
      that could not hold still: the first because its ages are recomputed against the clock on
      every sweep, the second because free space moves continuously on a live host. If either
      shows `changed` with no corresponding host event, **the fix did not hold on the real host
      and the run has failed** — record the row's `digest` and `compared` values from the
      Evidence fold and stop.
- [ ] Open **Evidence** on a row: it now shows two digests — `digest` (this row's bytes) and
      `compared` (the material state drift was decided on). They differ, and `compared` is
      identical between the two sweeps for an unchanged scope.

### Then prove it is not simply mute

Pick **one** of these — the first is the least invasive and is enough:

- **Touch nothing, wait for a real change.** If the host applies a WordPress plugin update on its
  own schedule, the next sweep should report `wp.inventory` `changed` at severity `ok`, with a
  sentence naming the plugin and version.
- **Or, deliberately:** deactivate a non-critical plugin, sweep, confirm `wp.inventory` reports
  `changed` and **escalates** (a plugin that was active and no longer is is the shape of both a
  broken update and a compromise), then reactivate it and sweep again.

- [ ] A real change was reported, in a sentence naming what changed.

## 3. Evidence to bring back

From the browser:

- the deployed commit and the run ids of both sweeps;
- the four scopes with their status, severity and change class, for **both** sweeps;
- for one scope, the Evidence fold from both sweeps showing `compared` identical across them;
- the reason text for any `unknown`, verbatim;
- the row from the "not mute" check.

**Read the streamed detail by eye for secret-bearing output before posting.** The boundary
redacts structurally and by key name, and the human review still applies.

## 4. What a failure means

| Symptom | Reading |
|---|---|
| Any scope `changed` on the second sweep with no host event | **Fail.** The defect U5.2a fixed is still present on the real host, in a form the fakes did not reproduce. |
| All four scopes `unknown` | **Fail.** Nothing was proven; the sweep inspected nothing. |
| Some scopes `unknown`, each explained | **Pass**, with the gaps recorded. `unknown` is a real state, not a defect. |
| First sweep shows `unchanged` rather than `baseline` | **Fail.** A comparison is being claimed that never happened. |
| A real change is not reported | **Fail.** The detector has been quietened rather than corrected. |

## 5. Explicitly out of scope for this run

- **The integrity scan's own operational acceptance** (issue #84) is still open. A stale or
  `unknown` scan reading here may be an honest description of the scan's real state rather than a
  fault in the reading, and this run does not settle it.
- **Trend and forecast.** `host.capacity` records numbers and says plainly that projection needs
  history it does not yet have. A "~9 days until breach" from two samples is a guess wearing a
  number's clothes; there is nothing to accept here yet.
- **Cases.** U5.1/U5.2 open none (amendment 2). Case linkage waits for machine-enforced
  `(profile, environment, finding)` keying in U5.4.
- **Backups.** U5.3a is next and is not covered here. Whether off-site backup to Google Drive is
  actually configured (R3) remains unanswered and is not something this run can discover.
- **Any privileged surface.** U5 adds none, and this run must not be used as an occasion to
  enable one. `deploy_release` stays `enabled=False`.
