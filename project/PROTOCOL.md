# Project Protocol — shared memory for humans and AIs

Adopted 2026-08-03 (owner-approved, reviewer-refined). This is the constitution; it should
change rarely. The problem it solves: the AIs have no shared live memory, and conversational
memory demonstrably corrupts (a session summary asserted the wrong production branch, the wrong
autodeploy state, and a misplaced commit — each corrected only by reading the repo and the
server). **The project remembers; the participants read.**

## Roles

| Role | Responsibility |
|---|---|
| Łukasz | Product Owner — release authority; the ONLY approver |
| Claude | Lead Engineer — implementation, deployment plans, evidence |
| ChatGPT | Chief Architect / Reviewer — audits, design review, risk |
| Git repository | Source of truth |
| /project files | Shared memory — navigation aids, NEVER authority |

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
   verification note is a claim, not a fact.
3. **Every substantive claim is traceable** — one pointer to its evidence, enough for any future
   reader (human or AI) to navigate to the source.
4. **Update on milestones, not session end.** Sessions die abruptly (context exhaustion is a
   first-class failure mode with direct evidence). Journal before the crash: update HANDOFF and
   SESSION_LOG at every commit/deploy/acceptance, not "when finished."
5. **Session ritual.** Start: read HANDOFF.md, OWNER_QUEUE.md, tail of SESSION_LOG.md. End (or
   milestone): update them. The reviewer reads the same three files — nobody needs the chat.

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
