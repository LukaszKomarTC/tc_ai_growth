# TC AI Operations Platform — Status

> **Constitution:** every future capability strengthens the governance doors — the phase gate,
> the store, the approval path — or it waits.

This is the primary progress document. Progress is measured in **system maturity and release
gates**, not commits. (What was an "AI Growth Agent" is now an **AI Operations Platform**;
growth is the first specialist module that plugs into the governed core.)

**Current operating mode: VALIDATE** (see `VISION.md` for the mode ladder
BUILD → VALIDATE → SHADOW → ASSIST → OPERATE and what each allows/forbids).

## Architecture maturity

```
Core engine (tools · runtimes · phase gate)   ██████████ 100%
Memory (store · cases · decisions · context)  ██████████ 100%
Dashboard (read-only console)                 ██████████ 100%
Approval workflow (CLI: approve/reject/
  outcome; buttons deferred)                  █████████░  90%
Validation (Release 0.3 checklist)            █████░░░░░  52%
Production readiness (profiles: read-only-
  by-construction · GitOps · portability)     █████░░░░░  50%
```

## Releases

| Release | Contents | Status |
|---|---|---|
| **0.1** | Observe · report · investigate · remember · explain · cost | ✅ Done |
| **0.2** | Maintain memory · no case re-opening · decision awareness · autonomous weekly · CLI approvals | ✅ Done |
| **0.3** | **Validation Release — NO NEW CAPABILITIES.** Polish, bug fixes for defects validation exposes, testing, documentation, confidence. | 🔶 **Current** |
| **1.0** | Production read-only: connector on production · shadow mode · stable weekly operation | Gated on 0.3 |
| **1.1** | Production drafts (SEO, products, landing pages). Nothing published automatically — ever. | Gated on 1.0 |
| **2.0** | Business Operating System: Strategy · Knowledge · Tasks · richer Cases · Assets | Gated on 1.1 |

## Release 0.3 — success criteria (ALL must hold; the checklist decides, not opinion)

- [ ] 3 consecutive clean weekly reports (no calibration failures)
- [ ] Zero duplicated cases across all runs
- [ ] Zero false critical incidents
- [ ] Every investigation evidence-graded (observations ≠ hypotheses ≠ conclusions)
- [ ] Every staging draft generated, reviewed, and rendering correctly (see `VALIDATION.md`)
- [ ] Approval round-trip proven: approved stays in force, rejected is never re-proposed
- [ ] Dashboard stable through the whole period
- [ ] Zero production writes of any kind
- [ ] `VALIDATION.md` fully green

**Then and only then → Release 1.0 (production shadow mode).**

## Open business items (outside the code)

- **GA4/Woo conversion tracking fix** (case `TRK-20260706-050158`) — blocks all ROI measurement.
- Google Ads developer token + Meta app review — long-lead; enables the Ads specialist later.
- Decision queue hygiene: approve/reject the current proposals so Monday runs respect them.

_Update this file when maturity or release state changes; details live in git history, not here._
