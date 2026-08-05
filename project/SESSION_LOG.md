# SESSION LOG — append-only breadcrumbs

## 2026-08-03

Completed
- Weekly report run#22 verified (status=0/SUCCESS, ledger ok) — first production Monday through the validator
- Production Baseline v1 recorded (144a173)
- WP-CONSOLE-USABILITY spec v1+v2 (69ea559)
- Deploy-script provenance fix (d260726) — found by U1 dry-run
- Console U1 fix round (63448f3): stream keepalive, nav truth, durable evidence store (TC_DB_PATH)
- Console redeployed twice (d260726 → 63448f3), U1 ACCEPTED in-browser (f222f03; evidence run#24)
- /project protocol adopted and seeded (19ef4b1)
- Protocol v1.1: chat-is-not-canon invariant, multi-engineer rules, reviewer bundles; docs/STANDING-CAUTIONS.md created (DO_NOT_RESTORE backup warning was chat-only until now)
- Codex governance onboarding read (at baf81b6): found HANDOFF stale main pin + wrong "3 doc-only" drift claim — both conceded; HANDOFF corrected with verified drift statement; protocol gains no-self-invalidating-pins corollary
- Reviewer gained GitHub READ connector (no write, by design); CODEX-1 refined to Repository Auditor role with validation task: docs-only PR modernizing WP-CONSOLE-DEPLOYMENT.md
- PR #67 (Codex): runbook modernized — lead-reviewed (193 green on branch), rebase-merged cd4623f. Full governed loop proven; CODEX-1 DECIDED. Found: shared GitHub identity blocks same-account approvals (recorded in PROTOCOL); new ops rule: retain N-1 release worktree until next successful deploy

- U2 EXECUTED: ops.tossacycling.com live (IONOS DNS + Plesk subdomain + Let's Encrypt + Apache-only proxy — no nginx on box, rate-limit deviation recorded; htpasswd perms fix). Verified through URL: SMTP + 114.9s scan (run#27). Token rotated (F4 closed). Logout built + tested (194 green). RUNBOOK-CONSOLE.md written

- U2 ACCEPTED: Console release ab9afa4 deployed; Sign out verified in-browser. U1+U2 done same day

- BUSINESS QUEUE CLEARED: D#9+D#10 executed by owner in WP, lead-verified live (all 4 URLs, ES+EN correct); P3-ES closed (real ES bookings); D#11 closed with reviewer-revised rationale (GA4=attribution, Woo=truth; 93 orders/€11,604 evidence). Record: docs/decisions/2026-08-D9-D10-D11.md. YoY −21% flagged as business observation

- U3a BUILT on feature/u3a-report-artifacts: schema v3 + immutability trigger, hash chain persist-before-deliver, delivery-by-hash, CLI reads, migration test, 201 green. Awaiting review + owner-authorized merge (touches Monday path)

- U3a review: 2 findings (stale branch base; hash-only delivery ambiguity on twin bodies) — both fixed (rebase; ArtifactBody id-binding, fail-closed mismatch, twin regression tests; report-redeliver). 205 green. AUTHORIZED + MERGED f0e5a50

- CI break on main (f0e5a50/7bab5ca): cross-test-module import failed CI's bare-pytest shape (passes python -m pytest locally + VPS). Fixed de3d8d7, CI green in 39s. New protocol rule: pusher verifies CI after every main push

- U3a DEPLOYED: converged b6779cc→d391247, 205 on VPS, v2→v3 migration clean, ledger intact, timer armed. Artifact #1 lands Monday 08-10

- U3b BUILT on feature/u3b-operator-homepage: home five-questions view, /report/<id> chain-metadata view, real Cases tab, redeliver_latest_report registry op, 213 green. Awaiting review

- U3b reviewer criteria recorded: behavioral capstone (Gmail-vs-Console on Monday), homepage checklist, anti-report rule, standing manual-elimination product bar. U3B-1 queued for owner authorization

- U3b reviewer-authorized; U4 opening requirement recorded (U3b=what needs attention, U4=why approve; evidence+impact before controls) + post-Monday owner-behavior instrumentation note. Merge held for OWNER word (reviewer input ≠ authorization)

- U3b MERGED (owner GO): rebased, 213 green, ff to main. Console redeploy pending

- U3b DEPLOYED (release 48e91d7) + in-browser acceptance: STRUCTURAL PASS, 4 observations (truth panel caught uncapped allow_writes + wrong/unconfirmed WP host; store decisions unsynced D#9/10/11; hierarchy debt -> U3b.1 polish adopted). Reviewer: usability 7/10, "beginning of an operations product"

- U3b.1 built+merged (94463c3, CI green, 214 tests): status card first (green all-clear / red top-decision with rationale+age), truth panel to bottom, severity accents, heading hierarchy. Reviewer's 10%-polish budget respected

- O1+O3 executed + U3b.1 DEPLOYED (Console release fd8f682, health 200): decisions approved in store (after lead's decision-set/decision-approve command-name fix), TC_ALLOW_WRITES=false live. O2 (WP host question) still open

- Reviewer wrote issue #68 (U3b UX review + U4 charter) — first reviewer write artifact. Lead replied on-thread (gap 4's simple card already shipped in fd8f682). GitHub-bus workflow ADOPTED (PR threads for increments; owner only authorizes); defer-Issues decision reversed with rationale. PROTOCOL updated

- O2 closed: dev.tourdegirona.com confirmed as Tossa's staging WP (intentional cross-domain; recorded in STANDING-CAUTIONS to prevent future false alarms). U3b observation set fully resolved

- GitHub bus round-trip complete on #68: reviewer accepted all points on-thread + added U4 requirement (auditable eliminated-actions table: disappears vs intentionally-manual); lead committed to it on-thread. Zero owner clipboard involved

- U4 spec written + PR #69 opened (owner GO — no waiting): eliminated-actions table, schema v4, content-bound approvals, verify-execution loop closing production decisions WITHOUT production writes, U2 basic-auth retirement trigger. Lead subscribed to the PR; review happens on-thread

- PR #69 review round 1: nine technical points (envelope binding, canonical hashing, state machine+concurrency, Verify-not-Execute naming, exact fail-closed verification, provenance on estimates, honest unknown counts, staging-apply OVERCLAIM conceded->dependency (verified on main), authority identity). ALL addressed in spec r2 (b02180a), point-by-point reply on thread. Fully on the bus — zero owner clipboard

- PR #69 review round 2: six spec inconsistencies (dup paragraph; approval-edit contradiction -> resolved to storage-immutable + explicit Unapprove; 60s-open-request UX -> two owner-triggered verify steps with store-backed pending; URL equality defined; attempts as immutable rows; production-first exit condition). ALL fixed in r3 (7782f3c), replied on thread

- PR #69 review round 3: two stale-wording contradictions (eliminated-actions staging row still claimed an "already accepted" apply path; PR description still described round-1 design). Fixed in r4 (7fcafe0): row now REMAINS MANUAL / DEFERRED (no registry op on main, not part of U4 closure); description rewritten to r4 truth (Verify-live-change control, target-bound envelope hash, staging apply = deferred dependency). Replied on thread

- PR #69 reviewer verdict on r4: "safe for owner authorization to merge" + 10 U4a acceptance criteria (adopted verbatim as U4a review gate, durable on thread). Reviewer's no-CI observation answered: ci.yml green ×2 on 7fcafe0. Merge queued for owner (OWNER_QUEUE U4-SPEC)

- U4 spec MERGED (owner GO): PR #69 rebase-merged to main f37dfb8. Queue emptied (U4-SPEC decided). U4a build begins on feature/u4a-decision-detail against the 10 thread criteria

- U4a BUILT + PR #71 opened (626b5ce, subscribed): schema v4 additive migration (proven on production-shaped v3 store), canonical envelope hashing (byte-exact pinned fixtures), storage-trigger lifecycle guards (approved immutable / executed terminal / events append-only), revision concurrency, /decision/<id> detail page (owner-first order), genuine two-step browser Approve + Reject-with-reason, decision-propose CLI seed. 250 green (36 new); branch CI green. PR body addresses the 10 criteria point-by-point. Awaiting reviewer round

- PR #70 discovered (reviewer's FIRST PR: AGENTS.md attribution protocol — identity headers, reserved authority language, review format). Lead review posted on-thread (adopting the header in the same comment): substance sound; 2 non-blocking findings (dual role-truth divergence risk -> pointer sentences both ways; reviewer write-surface widening -> PROTOCOL update on merge). Recommended for owner authorization; queued AGENTS-1

- PR #70 MERGED (main 365f623): AGENTS.md in force. Lead's committed alignments executed: authority-pointer sentence in AGENTS.md (PROTOCOL wins on role boundaries), PROTOCOL reviewer write-surface widened to governance-doc PRs, AGENTS-1 decided

- PR #71 review round 1 (reviewer, under AGENTS.md header): 3 findings — profile/environment must be ENFORCED at proposal boundary not displayed; target schema must be closed per kind; storage-enforcement claim overstated. ALL implemented in r2 (ec894e3, rebased onto post-#70 main): runtime-context params required on propose/repropose (fail closed, no row no event), TC_DECISION_URL_HOSTS setting (fail closed unset), closed kind schemas (unknown kinds unproposable; seo_meta_update: wp_post + post_id + both es/en HTTPS URLs), transition-graph trigger vs raw SQL, claims narrowed to precise layer. 258 green (+8). PR body rewritten to r2 with attribution header; replied on-thread

- PR #71 review round 2: 1 blocker — target-environment authority was inferred from env_kind, which would have REFUSED the live acceptance (staging-operating Console, production-targeting decisions); plus hosts optional at store boundary = future bypass. Fixed in r3 (9252821): TC_DECISION_TARGET_ENVIRONMENTS explicit setting (fail-closed, independent of env_kind/allow_writes; staging-console-proposes-production proven both ways), allowed_hosts MANDATORY at store boundary (omitted=TypeError, empty=ValueError), decision_proposal_context() testable. 262 green (+4). Deploy values recorded on thread: targets=production, hosts=www.tossacycling.com,tossacycling.com

- PR #71 reviewer verdict on r3: "safe for owner authorization to merge" (both round-2 corrections verified in code; reviewer self-corrected an earlier stale-state report). 6 deployment acceptance criteria adopted as the U4a deploy gate. Merge queued for owner (U4A-1)

- U4a MERGED (owner word): PR #71 rebase-merged to main 95c7974; 262 green on merged tip locally. Queue emptied (U4A-1 decided). Deploy plan next (6 reviewer criteria: 2 env values, controlled v3→v4 migration, VPS suite, seeded real decision, browser approve/reject, no-overstated-controls check)

- U4a DEPLOYED + BROWSER ACCEPTANCE PASSED: app converged d391247→a3104a8 (venv dev-extras reinstall needed); v3→v4 migration clean (schema 4, 11 decisions/26 runs/3 cases intact, 6 triggers); hosts env line markdown-mangled in paste — caught+fixed; D#12 seeded from live evidence (homepage 'Home | TOSSA CYCLING' both langs, post 11038); owner APPROVED in browser (two-step, audit rev 0→1); no Apply/Execute/Verify anywhere (screenshots). Owner applied in WP by hand; ES title/meta VERIFIED LIVE by lead fetch. Findings: owner enriched copy at apply (live ≠ envelope -> D#13 supersede plan); EN still cached/old on first check; Console redeploy regressed env truths (STAGING badge + writes Enabled) — release env seeded from app .env; fix = persist TC_ENV_KIND/TC_ALLOW_WRITES in /etc/tc-console.env. Record: WP-CONSOLE-USABILITY §U4a

- U4a closeout progress: VPS suite 262 passed (criterion 3 closed); EN homepage VERIFIED LIVE on re-fetch (was page cache) — BOTH languages of D#12's change now live; owner ran the /etc/tc-console.env persist fix + restart (badge/writes re-check pending owner refresh). Hosts .env line mangled a SECOND time by the owner's chat client (renders www URLs as markdown links even in code blocks) — new fix avoids contiguous www.host text; TARGET_ENVIRONMENTS line also duplicated (dedupe in same fix)

- U4a closeout confirmed by owner: badge PRODUCTION + writes Disabled restored (env persist works across releases now); D#13 (as-applied content) APPROVED in browser; D#12 UNAPPROVED (the reject was claimed but never happened — see 08-04 correction). Record now matches live content. Hosts-line hygiene fix output still unpasted (non-blocking: valid first entry carried every proposal)

- Reviewer post-merge finding on #71 (under AGENTS.md header): NO decision-history view — approved/rejected decisions vanish from homepage (proposed-only queue), reachable only by remembered URL; Unapprove effectively undiscoverable. "Real UX defect… fix promptly before U4a is called fully closed." U4a.1 build begins: /decisions destination (all statuses, filterable), nav tab, post-action history link

- U4a.1 BUILT + PR #72 opened (c6c5c72, subscribed): /decisions history destination (all statuses, whitelisted filters, legacy labeled), Decisions nav tab, history links where items leave the queue + on detail pages; queue semantics unchanged. 265 green (3 new incl. e2e approve→leaves-queue→discoverable). Replied on #71 thread; awaiting reviewer round

- PR #72 reviewer verdict: "safe for owner authorization to merge and deploy" (after self-correcting a restated-requirement comment — second connector-lag episode). 5 post-deploy acceptance checks adopted; pagination/search noted as future (U4c). Queued U4A1-1

- U4a.1 MERGED (owner word): PR #72 rebase-merged to main 8dafa5c; 265 green on merged tip. Queue emptied. Console redeploy block issued (release 8dafa5c; no migration)

- U4a.1 DEPLOYED (release 8dafa5c, health 200; env truths SURVIVED the redeploy — /etc/tc-console.env persist proven) + owner acceptance: Decisions nav live, D#12/D#13 discoverable, unapprove exercised. Owner observation -> real CSS bug: bare .card modal selector clamped every section.card (560px + 86vh inner scrollbar) — explains 'three decisions visible' compression. U4a.2 fix on PR #73 (scoped .modal .card + regression test, 266 green, subscribed)

- PR #73 reviewer verdict (one round): "Safe to merge" + 5 post-deploy checks + standing design rule (page = the scrolling surface; dialog geometry under .modal only). Queued U4A2-1

- U4a.2 MERGED (owner ok-go): PR #73 rebase-merged to main 9dd11ef; 266 green on merged tip. Queue emptied. Redeploy block issued (release 9dd11ef)

- U4a FULLY CLOSED: release 9dd11ef deployed (health 200), owner's 5 eyes-on checks ALL PASS (full-width history, single scrollbar, 13 rows, modal contained, no mobile overflow). Closure record in WP-CONSOLE-USABILITY. Three PRs (#71/#72/#73), 8 review rounds total, 266 tests

- U4b BUILT + PR #74 opened (d59f497, subscribed; owner go-U4b): tc_growth/verify.py (pinned URL-equality rules, NFC exact content match, cache-bypass fetch with redirect chain, per-language fail-closed reads); two-step flow store-backed (pending derived from attempts table — survives restarts; 60s from STORED read time; failed confirm consumes the pair); schema v5 additive (decision_verify_attempts, append-only triggers, migration proven); approved->executed atomic with evidence pointer + execute event; Console Verify-live-change section (countdown Confirm, attempts evidence, executed terminal display); control only for VERIFIABLE_KINDS. 297 green (31 new). D#13 = first live target

- PR #74 review round 1: 3 UX recommendations (self-explanatory two-step; plain-language mismatch BEFORE raw evidence; execution evidence as permanent business record) — ALL implemented in r2 (02913bb): why-two-reads intro, failed-read callout (fixed text + store-derived problems, nothing reflected), Execution record paragraph + history row context. 4 production acceptance criteria adopted as U4b deployment gate. 297 green. Replied on thread

- PR #74 reviewer verdict on r2: "safe for owner authorization to merge and deploy" + 6 production acceptance criteria (adopted as U4b deployment gate; incl. deliberate one-language mismatch + failed-confirm-consumes-pair exercises). Authority boundary confirmed correct. Queued U4B-1

- U4b MERGED (owner go): PR #74 rebase-merged to main 3edb0de; 297 green on merged tip. Queue emptied. Deploy plan issued (app v5 convergence + console redeploy; D#13 acceptance script covers all 6 criteria incl. deliberate-mismatch and failed-confirm-consumes-pair)

- U4b DEPLOYED: app converged to 3edb0de (297 on VPS, schema v5, 13 decisions/26 runs/3 cases intact, verify table + both append-only triggers armed); Console release 3edb0de, health 200

- RECORD CORRECTION: the store's decision_events (5, not 6) proved D#12 was never rejected — only unapproved. The lead had recorded the reject from chat memory without reading the store; D#12 sat back in the owner's queue unnoticed for ~13h. Owner rejected it for real 19:25 before the U4b acceptance. Lesson re-earned: verify state from the store before writing it into a record (PROTOCOL invariant 2)

- U4b ACCEPTED — THE PLATFORM CLOSED ITS OWN LOOP. D#13 verify failed closed on a REAL ES-meta drift (owner had refined copy again) -> D#13 rejected, D#14 seeded from live values, approved in browser, read#1 match 19:39:38, tc-console restarted mid-wait (pending survived, store-backed), read#2 match 19:47:18 -> EXECUTED by actor 'platform', evidence verify_attempt:3. 5 of 6 reviewer criteria proven live; criterion 4 (failed confirm consumes pair) honestly recorded as test-only. Record: WP-CONSOLE-USABILITY §U4b. Eliminated-actions row 2 retired

- Product finding: copy drift is a PATTERN (D#12->D#13->D#14 — owner improves wording while applying). Candidate: 'adopt live content' action proposing a pre-filled decision from the live page (U4c). U2 basic-auth retirement review now triggered per spec exit condition 4

- Reviewer posted 4 post-acceptance UX tasks on the MERGED #69 thread at 02:11 (business-first titles, before/after diff, quantified impact, expandable explanation) — unseen for ~17h because the lead only wakes on SUBSCRIBED PRs and a merged thread is not one. Mechanism restated on-thread: cross-increment guidance goes on the open PR of the day or a fresh issue referenced there. All 4 adopted into U4c with cost/priority; item 3 bounded (real GSC numbers or absent — never invented); item 1 conceded as lead's own authoring fault (technical titles came from the seed files)

- Issue #68: two reviewer reviews (governance + process) ADOPTED INTO PROTOCOL (c2c9da7). (a) store-backed state corollary to invariant 2: no closure/handoff/acceptance claim about ledger objects from chat memory; cite status + event sequence; counts must match; queue re-checked after every lifecycle act; discrepancies corrected explicitly. (b) closed PRs are historical records, not coordination channels — merging auto-unsubscribes the lead (the #69 mechanism); guidance goes on the open PR or a referenced open issue; every implementation PR carries its complete acceptance scope. Reviewer's stale "D#13 is the remaining gate" corrected on-thread with the store trail (D#13 rejected on real drift; D#14 executed)

- U4c SCOPE FIXED (reviewer-narrowed, lead-agreed): 1) business-first presentation 2) read-only current-vs-proposed comparison (reuses U4b fetch/compare — diff cannot disagree with the verifier) 3) progressive disclosure of technical evidence 4) adopt-live-content AS A NEW UNAPPROVED PROPOSAL WITH FULL PROVENANCE (never mutates an approved envelope, never shortcuts approval). External metrics (GSC/impact/ranking) explicitly OUT of U4c -> own increment

- Issue #75 opened by reviewer as the U4c coordination surface (the new process rule working as designed) with 7 acceptance criteria — all adopted on-thread. Three restated precisely: titles enforced at PROPOSAL time (lead proposed an objective constraint — title = owner headline, required, <=60 chars, technical detail to rationale, enforced at the store boundary — rather than a fuzzy jargon detector that would eventually refuse a legitimate title; schema-v6 headline-column alternative offered as the owner/reviewer's call BEFORE build); live comparison values timestamped with honest failure (no silent fallback to an older read — an unreadable page must look unreadable); adopt-live-content composes a NEW envelope through the unchanged proposal boundary at revision 0 with provenance (source decision id, URLs, fetch time, fetched strings) and never touches the source

- U4c BUILT + PR #76 opened (ee1833e, subscribed, references #75 per its criterion 1): headline constraint at the proposal boundary (objective <=60 chars, not a heuristic — a fail-closed boundary must not guess; legacy titles untouched); live comparison via the VERIFIER's own fetch/parse/normalize path, on request only (?live=1), timestamped, unreadable page shows NO value and withholds adopt; progressive disclosure (<details> for history/attempts/ops); adopt-live composes a new envelope through the UNCHANGED proposal boundary -> proposed rev 0 with provenance, source untouched, partial snapshots and stale revisions refused. Plus smart card (headline + provenance impact/confidence) and Action-required/Keep-an-eye-on labels. 307 green (10 new). Business-review block deliberately deferred (needs Monday's artifact #1 — no verifiable view before then). decision_proposal_context moved cli->config (a UI must not import the CLI)

- PR #76 review round 1: BLOCKING TOCTOU consent defect — adopt-live re-fetched on POST, so the proposal could bind wording the owner never reviewed (page can change between comparison and click). Conceded: binding the source REVISION protects the decision, not the consent. Fixed r2 (39f68b3): snapshot_digest over source id+revision+envelope and every displayed value (timestamp excluded — content must match, not the clock), signed adopt token (fetched_at|digest|sig), POST re-fetches and requires exact equality else refuses 'live content CHANGED', idempotent duplicate submit, provenance records BOTH reads. 312 green (5 new). Also found+fixed: `secret` out of scope in the decision handler made a NameError look like a policy refusal — broad except turning defects into polite refusals flagged as a pattern to watch

- PR #76 review round 2: idempotence not durable (200-row scan + evidence substring — PR claimed "can never" while code guaranteed it only for recent rows) and broad excepts still able to disguise defects as policy. Both fixed r3 (006adae): schema v6 decision_adoptions with adopt_key PRIMARY KEY (source:revision:envelope:snapshot-digest), claim-then-complete with reclaimable orphan claims, O(1) size-independent; unexpected exceptions now recorded as console-error runs with traceback and rendered as DEFECTS, never adopt-failed. Same lesson found one level down: claim_adoption answered False for ANY IntegrityError, so an FK violation would have read as "already claimed" — now re-reads and re-raises unless the key truly exists. 317 green (5 new)

- PR #76 reviewer verdict on r3: "recommended for owner authorization to merge and deploy" + 8 deployment criteria (adopted). Criterion 1 evidenced BEFORE deploy: new v5->v6 migration test on a POPULATED production-shaped store (executed decision + events + verify attempt + runs + artifact all byte-identical after migration) — 5b400af, 318 green. Corrected my own earlier PR line: U4c is NOT console-only, schema v6 means app convergence too. Queued U4C-1

- PR #76 review round 4 — BLOCKING on the RECORD, not the code: reviewer refused to authorize merge while the PR BODY still said "No schema change" and "Deploy = Console release only (no migration)" — both false since r3. I had conceded this in a thread comment and left the body untouched, which is conceding it in the wrong place: the body IS the durable acceptance scope, a comment is not, and the owner executes the deploy from the body hours later at a terminal. Body rewritten: schema v6 + decision_adoptions named, both false claims removed, deployment stated as an ORDERED three-phase sequence (app-checkout convergence -> v5->v6 migration from the converged checkout -> Console release/restart; order is load-bearing or a v5 Console binary meets a v6 store), head 5b400af / 318 green, 8 deployment criteria retained verbatim incl. both deliberate exercises. Documentation-only, no new head, CI unchanged. Second time this WP a durable record drifted while the code was correct (first: the D#12 "rejected" record the store disproved) — record drift is now treated as merge-blocking, same as a failing test

- U4C-1 AUTHORIZED (owner "ok" 2026-08-04) -> PR #76 rebase-merged. main 684681c, CI run #349 green, 318 green locally on the merged tip. Schema v6 now on main, so the next deploy is TWO phases in order: app-checkout convergence (runs the v5->v6 migration on the shared store) THEN Console release/restart — a Console-only deploy would put a v6 binary or a v5 binary on the wrong side of the store

- Issue #77 (reviewer): PAUSE the U4c production deploy until U4d — a constrained, owner-authorized, auditable deployment runner — exists. Security boundary adopted verbatim (no shell, allowlists, exact-SHA-only, backup verified before migration, stop-on-failure + tested rollback, secrets never in evidence, approval separate from execution, never touches production WP). But raised a BOOTSTRAP finding that makes the stated first operation self-defeating: the runner is repo code, so installing it requires converging the app checkout to a commit CONTAINING U4c, and that convergence IS the v5->v6 migration — installing U4d performs the U4c deploy. The pause relocates the manual deploy, it doesn't remove one. Also flagged: risk inversion (gating a 5x-rehearsed procedure with tested rollback behind new high-blast-radius infra that itself deploys unprotected, incl. a sudoers expansion from one read-only script to install//usr/local/bin + systemd unit + restart); #77 describes TWO different systems (forced-command remote identity vs owner-clicked Console operation — only the second is needed to satisfy its own acceptance criteria, and it adds no inbound surface; I have no SSH and asked for none); and the Console cannot restart itself mid-operation without killing the process writing the evidence -> needs a DETACHED runner (systemd-run oneshot) that outlives the restart, which shapes the whole increment

- Owner direction: take #77's decisions WITH THE REVIEWER, on the issue, ONE AT A TIME — not in chat. Reposted as Decision 1 only (sequencing: A deploy U4c now then build U4d / B hold per #77 / C build+prove U4d then let its install BE the U4c deploy / D runner built off a pre-U4c base). Recommended A, stated C is legitimate, B is C without honesty about the bootstrap. Decision 2 (trigger architecture) deliberately withheld until 1 is answered. U4c deploy HELD

- #77 Decision 1 RESOLVED — owner approved A (2026-08-04), ahead of a reviewer response on the thread; recorded as an OWNER decision, not reviewer concurrence (owner is sole release/deploy authority — the model working, not a bypass). U4c deploys now via the rehearsed procedure; U4d built after with a staging dry run, first production exercise = the next increment. #77 STAYS OPEN, scope and security boundary unreduced — A fixes the sequencing, not the defect that the owner still pastes terminal blocks. Decision 2 (trigger architecture) still with the reviewer, to be opened after U4c acceptance with the detached-runner problem attached

- U4c DEPLOYED (684681c, schema v6) and ACCEPTED on all 8 criteria. Criteria 1-2 proved on the PRODUCTION store by diffing the pre-migration .backup against the migrated db: only decision_adoptions added, every data table byte-identical, D#14 still executed with its propose/approve/execute trail. Criteria 3a/3b/4/5/6/7 exercised by the LEAD over real HTTP against the deployed commit after the owner stopped the browser pass — 3a/3b/5/7 against the REAL live pages, 4/6 against a local HTTPS fixture whose content genuinely changed mid-flow (real second fetch, not a stub). Recorded explicitly as evidence about the CODE on an equivalent instance, NOT a production browser pass

- Two lead errors cost the owner a round of clicking: I told him to edit /alquiler_bicicletas while the comparison open was D#12, a HOMEPAGE decision — so the platform correctly saw no change and criterion 4 never ran, looking like a failure. (Earlier slips: `meta` vs `schema_version`, `event` vs `action`.) The gravel edit landed on the rental page and now drifts from D#9's executed envelope — his call whether to keep it; executed stays terminal either way

- TWO FINDINGS from the acceptance run, neither fixed: (1) FAIL-OPEN COMPARISON — validate_envelope only requires payload to be a non-empty object, never the keys the kind uses, so a seo_meta_update envelope with unrecognised payload keys validates, compare_fields returns ZERO rows, and the page asserts "Every field matches what is live right now". A positive claim about reality from an empty comparison is the exact fail-open shape U4c exists to prevent. Unreachable from the Console UI, reachable from decision-propose. (2) THE OWNER GOT LOST IN THE UI, reported twice unprompted — U4c's goal was business-first presentation, and an acceptance pass the owner cannot finish is that goal not met

- Owner decision 2026-08-04: the accidental "Gravel" wording on /alquiler_bicicletas STAYS (it is better copy). Lead CORRECTED its own claim about the consequence: I said it would drift from D#9's "executed envelope" and show up in future comparisons — both false. The store has D#9 as (9, 'approved', 0, NULL) — a pre-v4 legacy row with NO envelope and no kind, so there is nothing to hash-drift from and it can be neither compared nor adopted through U4c. Real consequence: the live wording is correct and UNRECORDED; putting it under platform control needs a fresh seo_meta_update proposal for that page

- RECORD DRIFT FOUND on the pre-v4 rows: docs/decisions/2026-08-D9-D10-D11.md and OWNER_QUEUE both call D#9 "Executed" while the store says approved — same class as the D#12 false record. To be reconciled AGAINST THE STORE as a deliberate pass over all pre-v4 decisions, not patched one-off

- #77 FULLY DECIDED. D1: reviewer independently confirmed A and additionally ruled out the pre-U4c fork (option D) as a divergent subsystem for no gain — my bootstrap analysis accepted. D2 (OWNER, binding, final): owner-clicked Operation Registry action + DETACHED supervised runner that survives the Console restart and writes its own Evidence; remote SSH identity, inbound trigger path, interactive shell and general command execution all REJECTED. U4d authorized to build on current main with NO further owner design decision before its PR. Posted the U4d scope restated so it can be held against me, and stated plainly on-thread that U4c's criteria 3-7 were LEAD-run, not an owner browser pass — offering to hold U4d if either judges that insufficient

- U4d BUILT + PR #78 (36305b5 -> c436da2, subscribed). Owner-clicked Operation Registry action + DETACHED runner per #77 D2. Authorization is a STORE ROW not an argument (CLI takes a run id, has no --sha); triggers make the reviewed target immutable and a finished run terminal against raw SQL; EXECUTORS is a closed argv table (shell check runs on the parsed AST, not source text, so prose can't fool it); detached survival proven by killing a real parent process. Registered but enabled=False — the page renders, the control is absent AND the server refuses the POST. Registry gained target_surface site|platform so a platform-write op isn't forced to lie about targeting staging. Schema v7 (deploy_runs + deploy_steps, additive)

- PR #78 review round 1 — TWO BLOCKERS, both real, both mine: (1) execute() computed the atomic planned->running claim and THREW THE BOOLEAN AWAY, so two detached runners could both pass the earlier read and both deploy. Worse than the missing line: I had a test NAMED test_two_runners_racing... that asserted on the store helper and never called execute() — named after the property, testing the mechanism, passing while the property was false. (2) backup "verification" compared row counts, which is nearly free to satisfy and proves almost nothing, while the plan called it a verified recovery copy. Fixed r2 (c436da2): loser stops AT the claim before any step is recorded (proven with 2 real threads + barrier + separate store connections); backup proven by PRAGMA integrity_check AND a full sorted row-content digest, retried once because the store is live, refusing rather than guessing. Found a THIRD defect while fixing theirs: `context or default_context()` treats {} as absent, so context={} silently ran the PRODUCTION context and made one ordering assertion pass VACUOUSLY. 398 green

- Also corrected the PR description TWICE and recorded both in the body rather than editing silently: I first wrote a head SHA (44a6e5a) that does not exist — from memory instead of reading it — and the body had itself called count-comparison a verified recovery copy (criterion 7 covered the description, not just the code)

- PR #78 r1 re-review: blockers CLEARED, "suitable for owner merge authorization as a DISABLED capability" + 7 post-merge criteria before enabling (adopted verbatim). Queued U4D-1 — did NOT merge; a reviewer clearance is not an authorization. Flagged on-thread: criterion 3 (restart survival) must NOT default to KillMode=process, which would let ANY future Console child survive a restart — authority nobody asked for; a transient systemd-run unit scopes it to the deployment instead, and that trade belongs in the host review written down. Criterion 6 agreed: redaction tests prove 4 anticipated shapes don't survive, NOT that a real deploy's output is clean — the disposable run's Evidence gets read by eye. Honest status: the runner has never executed a real deployment on any target

- PR #78 convergence round: main advanced (my OWN queue/log push) -> branch behind, GitHub not mergeable. Rebased onto e0de845 (head b840646), re-ran the suite LOCALLY on the rebased head before pushing, 398 green. Nothing conflicted — main had gained only the two project/*.md files this branch never touches, so the security-sensitive code stayed byte-identical to the cleared review. Named the cause rather than treating it as weather: record-keeping commits to main during an open PR strand it every time (this repo requires branches up to date); the fix is prompt rebasing, not fewer records. THIRD description correction in the same edit: the body still asserted KillMode=process as THE restart-survival mechanism after I had argued on-thread that it broadens authority nobody asked for — leaving that in the durable scope would have contradicted my own position

- Deliberately HELD the queue-SHA correction while #78 was open: fixing it meant a main push, which would strand the branch again and invalidate the clearance the reviewer had just issued against b840646. Surfaced the trade to the owner instead of silently choosing either way

- U4D-1 AUTHORIZED (owner "merge" 2026-08-05) -> PR #78 rebase-merged. main 5beb562, 398 green on the merged tip. Merging deployed NOTHING and enabled NOTHING — deploy_release remains enabled=False and server-refused. The runner has still never executed a real deployment on any target; its first must be a disposable/staging proof, never production

Current
- U4c LIVE and accepted; U4d MERGED but DISABLED (main 5beb562, schema v7 not yet deployed). Next: U4d enablement gate — v6->v7 production migration, host privilege review (no general command path), restart-survival mechanism CHOSEN with the argument written down (KillMode=process vs transient systemd-run unit), disposable proof, rollback exercise, real-output secret inspection by eye. Also open: the 2 U4c findings (fail-open comparison + UI usability) need an owner scope call; U2 retirement review. Monday 08-10: artifact #1 + capstone (app convergence + v5->v6 migration, then Console release) + 8-criteria browser acceptance incl. the 2 deliberate exercises (mid-comparison page change -> adopt refuses; injected defect -> shows as DEFECT not policy). Then U2 retirement review. Monday 08-10: artifact #1 + capstone

Blocked
- Nothing hard; business queue on owner (see OWNER_QUEUE.md)

Next
- U3a artifact persistence; owner business queue (P3-ES, D#9, D#10, D#11)

## 2026-08-02 (prior sessions, reconstructed from records)

Completed
- Accelerated validation runs #20/#21 both PASS — reporting gate closed (7655159)
- Validator branch rebased onto main, deployment plan reviewed (WP-REPORT-VALIDATION-DEPLOYMENT.md)
- Production checkout converged 527fdea → 7655159 (183 tests) → validator merged → b6779cc (190 tests)
- Validator live; run19-narration rejected / run20-genuine accepted on deployed code
- Notify hotfix captured to patch + cleaned (lives in feature/technical-inspector)
