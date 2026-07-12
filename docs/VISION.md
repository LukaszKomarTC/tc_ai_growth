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
FORBIDDEN_CAPABILITIES` — the tools do not exist, cannot be enabled by configuration,
permissions, or dashboard settings, and are absent from any capability registry):

- **Pricing** changes
- **Availability / booking** changes (including creating or modifying bookings)
- **Checkout / tracking-code** modification
- **Financial transfers** — absolute: never a tool, in any mode, ever, amendment or not
- **Publishing** without a human approval step

Precision on scope: these prohibit *write* capabilities. **Reads in the same domains —
availability checks, reservation summaries, booking-conflict detection, pricing visibility,
checkout diagnostics — are ordinary gated capabilities**, subject to the normal mode ladder
and release gates, not to this section.

The correct description of these limits is: **constitutionally prohibited under the current
VISION.md** — not "never possible." Except for financial transfers (absolute), they can be
introduced by exactly one path: the amendment procedure below. Never as a side effect of a
feature, a spec revision, a dashboard permission, or a persuasive review.

## Amendment procedure (the only path to changing the permanent limits)

An amendment is a governance act, not a documentation edit. Editing this file alone changes
nothing — the procedure is what grants force:

1. **Written proposal** — exact capability definition (what it can and cannot do, parameters,
   blast-radius limits), risk/benefit assessment, rollback design, verification probes, and
   audit/alert requirements.
2. **Cooling-off period: 7 days minimum** between proposal and ratification. No same-day
   constitutional changes, ever — regardless of who proposes or how urgent it feels.
3. **Explicit owner ratification, recorded as a decision in the platform store** (with the
   proposal attached as evidence). Only the owner can ratify; the agent and its tooling can
   draft a proposal but nothing more.
4. **Dedicated release gate** — staging implementation and validation before any production
   presence, exactly like any other capability, on top of the amendment.
5. **Separate activation** — ratifying the amendment and enabling the capability are two
   distinct human actions. Merging the code never activates the capability; one click must
   never do both.

If any step is missing, the limit stands, whatever this file happens to say.

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
