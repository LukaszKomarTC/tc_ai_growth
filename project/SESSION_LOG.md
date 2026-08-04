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

Current
- PR #76 (U4c) under review on-thread; owner word merges; deploy = console release only. Then U2 retirement review. Monday 08-10: artifact #1 + behavioral capstone

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
