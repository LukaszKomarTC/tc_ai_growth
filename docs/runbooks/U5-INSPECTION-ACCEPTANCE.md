# WP-U5.2 — the on-host inspection acceptance run (owner-executed)

*U5.1 (PR #85) built the collect → normalize → snapshot → compare → classify foundation. U5.2
(PR #86) added the four real collectors and the Console trigger. U5.2a (PR #87) fixed drift being
computed over the measurement rather than the state. U5.2b normalized the runtime contract — one
canonical Console unit, the docroot as governed configuration, and a Runtime panel so the browser
can state what it is. This is the on-host run the agent cannot perform — it needs the VPS, a real
journal, a real filesystem and a real WordPress.*

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
3. **Set `TC_SITE_DOCROOT` — as governed configuration, not a shell export.** Since U5.2b it is
   an input to `deploy-console.sh` (`TC_SITE_DOCROOT=/path/to/docroot ./deploy-console.sh
   --apply`), which writes it into the unit alongside `TC_DB_PATH`. The dry run prints whether it
   is set and whether the path exists, so an unset docroot is visible **before** `--apply`.
   Without it `wp.inventory` returns `unknown` — correct and by design, since guessing a docroot
   would mean inspecting whichever site happens to live at a familiar path and filing the result
   under this profile's name — but the run then proves nothing about WordPress.
4. *(Optional)* `TC_INSPECTOR_LOG` if the v0 integrity scan writes somewhere other than
   `/var/log/tc-inspector.log`.
5. **Confirm the Console is the canonical unit.** Since U5.2b there is exactly one:
   `tc-console.service`, named in `tc_growth/runtime_identity.py` and imported by the collectors,
   the command boundary, the journal read and this runbook. `tc-dashboard.service` is the older
   read-only dashboard, marked transitional in its own unit file with retirement criteria; it is
   deliberately **not** inspected.
6. **Confirm the service was restarted** so it is running the deployed code and carrying the new
   environment. Note that a merge to `main` does **not** advance the Console: it runs from a
   release worktree pinned at a reviewed commit, and `autodeploy` deliberately leaves it alone so
   an execution surface is never auto-advanced. Advancing it is an explicit `deploy-console.sh`
   run.

**You no longer need SSH to check any of this.** The Console's own **Runtime** panel on Operations
Health states the effective unit, profile, environment, deployed commit and docroot — and refuses
to hide behind a fold when something is wrong. That panel is the pre-flight; §2 begins by reading
it.

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

### Before the first sweep — read the Runtime panel

- [ ] **Service** is `tc-console.service`. If it names anything else, the collectors are watching
      a unit that is not serving this page and the run will produce findings about naming drift
      rather than about the Inspector. Stop and fix the deployment.
- [ ] **Identity** is the profile and environment you intend to file this evidence under.
- [ ] **Deployed commit** matches the head you deployed.
- [ ] **WordPress docroot** is set and readable — no red banner.

If the panel shows the red *"This Console is not fully configured to inspect"* block, fix that
first. A sweep will still run and will still be honest, but `unknown` from a misconfiguration is
not an acceptance-quality reading.

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
- [ ] Open **Evidence** on a row for **both** sweeps and compare the two digests it shows:
      `digest` (this row's exact bytes) and `compared` (the material state drift was decided on).
      For an unchanged scope, **`compared` must be identical across the pair while `digest` may
      differ.** This is the sharpest available proof that the fix works in the right direction —
      the reading moved and the state did not. If both are identical the host is genuinely
      frozen and this criterion has not been tested; pick a scope where `digest` moved
      (`platform.services` always will, since its ages are recomputed against the clock).

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
