# Project Protocol — shared memory for humans and AIs

Adopted 2026-08-03 (owner-approved, reviewer-refined). This is the constitution; it should
change rarely. The problem it solves: the AIs have no shared live memory, and conversational
memory demonstrably corrupts (a session summary asserted the wrong production branch, the wrong
autodeploy state, and a misplaced commit — each corrected only by reading the repo and the
server). **The project remembers; the participants read.**

## Roles

| Role | Who | Responsibility |
|---|---|---|
| Product Owner | Łukasz | Release authority; the ONLY approver |
| Lead Engineer | Claude | Implementation, deployment plans, evidence; merges after green suite |
| Repository Auditor | Codex | Repository-consistency audits; docs-only PRs on branches (onboarded 2026-08-03 via PR #67 — audit → PR → lead review → merge, full loop proven) |
| Architecture & Governance | ChatGPT | Design review, audits, risk; writes recommendation artifacts only (issues, PR reviews) — never code/merges |
| Source of truth | Git repository | — |
| Shared memory | /project files | Navigation aids, NEVER authority |

**Known limitation (2026-08-03):** all agents currently act under ONE GitHub identity, so
GitHub's own review mechanics can't distinguish them (an "approval" of a same-account PR is
impossible; lead reviews land as comments). Role separation is enforced by this protocol and
the records, not by GitHub. If enforcement-by-platform becomes wanted, agents need distinct
GitHub identities (machine accounts + branch protection) — a deliberate future decision, not
an accident to drift into.

Standing governance (earned, not theoretical): **reviewer input ≠ authorization** — only the
owner authorizes releases and production actions. Freeze protocol: every change reaches servers
through Git, never hand-edits. All production-checkout Git runs as `tcgrowth`, never root (D5).

## The truth hierarchy

1. Live system / production state
2. Git history and repository content
3. Evidence records / work package documentation
4. /project markdown files

**If #4 disagrees with #1–#3, #4 is wrong** — fix the file, never argue from it. These files are
indexes pointing at authority, never restatements of it.

## The files

- **HANDOFF.md** — "where does the next engineer start?" One page maximum. Current work, current
  commits, current blocker, next action. Nothing historical.
- **OWNER_QUEUE.md** — the single interruption mechanism. Decisions/actions only the owner can
  take. **Invariant: empty queue == don't disturb Łukasz.** Fields mirror the future platform
  objects (see Phase 2) so migration is a storage upgrade, not a redesign.
- **SESSION_LOG.md** — append-only breadcrumbs, a few lines per session. No prose, no essays.
- **PROTOCOL.md** — this file.

## Invariants

1. **Index, not authority.** No file here restates evidence or duplicates a record that lives
   elsewhere — it points (commit, run #, doc path, PR).
2. **Live values are verified, not remembered.** Any branch/commit/deployment value carries how
   it was checked and when: `verified: <command> → <result> @ <UTC timestamp>`. A value without a
   verification note is a claim, not a fact. Corollary (Codex finding, 2026-08-03): never record
   a value that the act of recording invalidates — a file committed to `main` cannot pin `main`'s
   HEAD; point at the authority (`git rev-parse origin/main`) instead. Pin only values that
   change through OTHER events (deployed releases, server checkouts).
3. **Every substantive claim is traceable** — one pointer to its evidence, enough for any future
   reader (human or AI) to navigate to the source.
4. **Update on milestones, not session end.** Sessions die abruptly (context exhaustion is a
   first-class failure mode with direct evidence). Journal before the crash: update HANDOFF and
   SESSION_LOG at every commit/deploy/acceptance, not "when finished."
5. **Session ritual.** Start: read HANDOFF.md, OWNER_QUEUE.md, tail of SESSION_LOG.md (and know
   docs/STANDING-CAUTIONS.md exists). End (or milestone): update them. The reviewer reads the
   same files — nobody needs the chat.
6. **Chat is not canon.** The moment any participant relies on a load-bearing fact that exists
   only in conversation, it gets recorded in the repository — continuously absorbed, not
   bulk-exported. (Proven necessary 2026-08-03: the DO_NOT_RESTORE compromised-backup warning
   lived only in chat until a grep showed the repo had never heard of it.) Permanent dangers go
   to docs/STANDING-CAUTIONS.md; decisions to their work package; state to HANDOFF.

## Multiple engineers

The repository can host more engineers than the lead (e.g. a repository-native assistant such as
Codex). Rules, set before any second engineer joins:

- **Any engineer beyond the lead works on branches and opens PRs — never pushes `main`.** Merges
  to `main` are executed by the lead after the full test suite is green, or by the owner.
- **Every push to `main` is verified against CI** (.github/workflows/ci.yml) by whoever pushed —
  green locally is not green, because invocation shapes differ (learned 2026-08-03: a
  cwd-dependent test import passed `python -m pytest` locally and on the VPS but failed CI's
  bare `pytest`; the owner learned of the break from failure emails before the lead did).
- **Deployment is excluded** from additional engineers entirely: server actions remain
  owner-run under lead-prepared, reviewed plans. Nothing about the deploy discipline changes.
- New engineers start with a **narrow earned scope** (small fixes, tests, docs, PR preparation)
  and expand only through accepted work — capability is earned by acceptance here, same as for
  the platform's own operations.
- Every engineer follows this protocol's session ritual; the /project files are how engineers
  who cannot see each other's conversations coordinate.
- Roles are added to the table above when a participant actually joins, not speculatively.

## Coordination — how agents learn what happened

**Today: pull, not push.** The repository is the shared state; nobody relays content. Each agent
reads state when it activates (the session ritual); an agent's work IS its notification — the
commit, the PR, the SESSION_LOG line. The owner's role shrinks from "paste content between
agents" to "one-word nudge that an agent should look" — and even that disappears where push
exists (below).

Honest per-agent capabilities (2026-08-03):

- **Claude (lead):** reads the live repo on demand (commits, PRs, diffs, reviews — no uploads);
  can **subscribe to a specific PR**, after which comments/reviews/CI on that PR arrive as
  events into its session — a real push channel, used for active review loops.
- **Codex (auditor):** repository-native read; acts when invoked; reports via PR/commits.
- **ChatGPT (reviewer):** GitHub read connector when invoked; **no background worker** (its own
  statement) — it participates when the owner opens the conversation or, later, when the
  platform invokes it.

**Horizon (recorded, not built): the platform as event orchestrator.** GitHub webhook → events
recorded as evidence → role-scoped agent invocation → OWNER_QUEUE/notifications — the "AI
Operating System" shape, converging with U3b (queue panel) and U4 (decision workflow), reusing
the existing evidence/cases/decisions pipeline. Build it when coordination volume demands it;
at three agents and ~one PR a week, pull + per-PR subscriptions suffice, and process that
outpaces its value is how good protocols die.

## Reviewer access

The reviewer (ChatGPT) has READ access to the live repository via its GitHub connector (as of
2026-08-03): commits, files, branch comparisons, PR review/comments, search. Fallback when the
connector is unavailable — the owner uploads a bundle:

    git archive --format=zip -o /tmp/tc-review-bundle.zip HEAD docs project orchestrator

**Reviewer write surface (updated 2026-08-04): recommendation artifacts only.** The reviewer
can create GitHub issues and PR reviews/comments (first: issue #68, the U3b UX review) — these
are recommendations in durable form, not repo content. Code, merges, and releases remain
outside its authority, by its own recommendation and owner governance: separation of duties is
a strength of this model. The owner's word remains the only merge/deploy authority.

**The GitHub bus (adopted 2026-08-04, reversing the earlier defer-Issues decision — the pain it
solves materialized as transcript relaying):** engineering increments now run as PR threads.
Lead opens the PR and subscribes to it (events push into the lead's session) · reviewer reviews
on the thread · lead replies/fixes on the thread · auditor audits on the thread · the owner
steps in ONLY to authorize. Issues carry cross-increment charters (e.g. #68 = U4 UX charter).
Chat remains for owner guidance and server work; agent-to-agent content stops flowing through
the owner's clipboard.

## Deliberately NOT here

GitHub Issues (would be a third surface restating WP docs — revisit only when parallel
contributors create the pain Issues solve) · CURRENT_STATE/ARCHITECTURE/DECISIONS files (the
work packages, dependency map, and acceptance ledgers ARE those records; the queue indexes
decisions rather than copying them).

## Phase 2 (future)

These files retire into the platform itself: OWNER_QUEUE → the U3b pending-decisions panel and
U4 approval objects; HANDOFF/SESSION_LOG → store-backed records the dashboard renders. The
markdown fields are designed as the future database fields, so migration is mechanical. Like
every transitional layer in this project, this one retires deliberately, with its successor
already live.
