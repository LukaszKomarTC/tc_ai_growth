# Production Baseline v1

**Recorded:** 2026-08-03 (state as deployed 2026-08-02). The first known-good, reproducible
production reference point. Every future release compares against this.

| Item | State |
|---|---|
| Production commit (`/opt/tc_ai_growth/app`) | `b6779cc14ccc63952261e9c97ae22b389e9bc093` |
| Production regression | **190 passed** (full suite, run on the VPS as `tcgrowth`) |
| Weekly-report validator | **PASS** — deployed; accepts run #20 genuine body, rejects run #19 narration (verified on deployed code) |
| Weekly reporting | **PASS** — accelerated gate closed on runs #20/#21 (timer-fired, human-graded, technically verified) |
| Console foundation | Integrated into `main` and present (dormant) in the production checkout; tc-console serves from its separately accepted release worktree |
| Monday timer | `tc-weekly-report.timer` armed, Mon 05:00 UTC (07:00 Europe/Madrid), unchanged throughout |
| Deployment process | **Manual, deliberate** — controlled fast-forward as `tcgrowth`, VPS test-gate, no reset/force (WP-REPORT-VALIDATION-DEPLOYMENT.md) |
| Autodeploy | **Disabled** by decision — re-enabling is its own operational review |
| Rollback markers on server | `backup/pre-converge-527fdea`, `backup/pre-validator-7655159` |
| Known production issues | None |

## Known deferred work (parked, not blocking)

- Autodeploy review (whether/when to restore GitOps delivery)
- Technical Inspector `notify` merge (`feature/technical-inspector`; server-side insurance patch at `orchestrator/data/staged-notify-hotfix-2026-08-02.patch`)
- Server branch-name cleanup (checkout branch still named `claude/wordpress-ai-growth-agent-l70f55`, pointing at main-line history)
- Rotate `TC_CONSOLE_TOKEN` (F4)

## Business queue (the current bottleneck — value capture, not infrastructure)

1. **D#9** — approve + publish bilingual title/meta for `/alquiler_bicicletas` (post 13699)
2. **D#10** — approve + publish bilingual title/meta for `/salidas_guiadas-listado` (post 48284)
3. **D#11** — resolve TRK-20260706-050158 after WP-admin order cross-check

## Governance invariants carried forward

Owner is release authority · every deploy is deliberate and evidence-gated · freeze protocol
(all changes through Git, never hand-edits on the box) · all production-checkout Git as
`tcgrowth`, never root (incident D5).
