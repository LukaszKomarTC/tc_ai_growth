# Vision — TC AI Operations Platform

This is the stable constitution of the platform. ROADMAP changes, STATUS changes, VALIDATION
changes — this document should not. Amend it only deliberately, the way you'd amend a policy,
not the way you'd edit a plan.

## Mission

Build an **AI Operations Platform** that safely assists in running Tossa Cycling.

The model is a component. The platform — governance, memory, confidence, validation,
observability — is the product. "Growth" (SEO, ads, analytics) is the first specialist module
that plugs into the governed core; it is not the identity of the system.

## Principles

1. **Safety before autonomy.**
2. **Staging before production.**
3. **Evidence before conclusions.** Observations ≠ hypotheses ≠ conclusions; confidence is
   stated and updated as evidence arrives.
4. **Human approval before irreversible actions.**
5. **Every action auditable.** If it isn't in the store, it didn't happen.
6. **Every recommendation explainable.** The reasoning trail — including retracted
   hypotheses — is preserved, not just the verdict.
7. **Memory before intelligence.**
8. **Architecture before features.** Every capability strengthens the governance doors —
   the phase gate, the store, the approval path — or it waits.
9. **Simplicity over cleverness.**
10. **The checklist decides, not enthusiasm.**

## Operating modes

The platform is always in exactly one mode. Every activity should know which mode it is in;
transitions happen only through the gates in `docs/VALIDATION.md` / `docs/STATUS.md`.

| Mode | Allowed | Forbidden |
|---|---|---|
| **BUILD** | New code, refactoring | — |
| **VALIDATE** ← current | Bug fixes, documentation, testing, **validation tooling** (test harnesses like `draft-test` that exercise existing gates without changing product behavior — "Type B" code) | New capabilities, new integrations, schema/workflow changes, structural refactoring ("Type A" code) |
| **SHADOW** | Recommendations, comparisons, reporting against production | Execution of any kind |
| **ASSIST** | Drafts, human-approved actions | Autonomous publishing |
| **OPERATE** | Approved, bounded, audited actions | See "Permanent limits" |

**Architecture freeze:** from VALIDATE onward, no structural refactoring until Release 1.0
unless validation proves something fundamentally wrong. The architecture is no longer the
bottleneck; trust is.

## Permanent limits (human-controlled regardless of mode)

These are not phase-gated — they are refused by construction (`core/approval.py
FORBIDDEN_CAPABILITIES` — the tools do not exist):

- Automatic **pricing** changes
- Automatic **availability / booking** changes
- Automatic **checkout / tracking-code** modification
- Automatic **financial transfers** (never even a tool)
- Automatic **publishing** without a human approval step

Changing any of these is a conscious policy amendment to this document — years away, if ever —
never a side effect of a feature.

## Long-term destination

A platform capable of assisting across **marketing, website, reservations, workshop, inventory,
pricing, customer service, finance, and business planning** — each as a specialist module
plugging into the same governed core (gate → store → approvals → audit), without ever
compromising operational safety. The agent should end up with a *business model* of Tossa
Cycling — cases, decisions, knowledge, strategy, assets — not merely a memory.

## The four documents

| Document | Question it answers |
|---|---|
| **VISION.md** (this) | Why are we building it, and what never changes? |
| **ROADMAP.md** | What will we build, in what order? |
| **STATUS.md** | Where are we right now? |
| **VALIDATION.md** | Are we allowed to move forward? |
