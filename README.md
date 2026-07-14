# TC AI Operations Platform

> **The checklist decides, not enthusiasm.**

An **AI Operations Platform** for **Tossa Cycling** — bike rentals, guided tours, eMTB/road
hire (Costa Brava / Tour de Girona). Growth (SEO, ads, analytics tied to real WooCommerce
bookings and revenue) is the platform's first specialist module; the platform itself is
governance, memory, confidence, validation, and observability. **The model is a component;
the platform is the product.**

The website stays thin: a small WordPress connector plugin exposes controlled data and accepts
**drafts only**. The "brain" runs externally, provider-neutral (Claude-first).

> ⚠️ **Safety first.** The system never publishes, never spends ad budget, and never touches
> prices, availability, the booking plugin, or checkout — those capabilities do not exist as
> tools (constitutionally prohibited; see `docs/VISION.md`, including the amendment procedure).
> It produces drafts, reports, and proposals for human approval.

**Governance documents (the source of truth — read these, not this README, for current
state):** [`docs/VISION.md`](docs/VISION.md) (why — the constitution) ·
[`docs/ROADMAP.md`](docs/ROADMAP.md) (what) · [`docs/STATUS.md`](docs/STATUS.md) (where) ·
[`docs/VALIDATION.md`](docs/VALIDATION.md) (may we proceed). **Current mode: VALIDATE**
(Release 0.3 — no new capabilities; bug fixes, docs, and read-only polish only).

## Architecture at a glance

```
                Owner (dashboard · CLI · weekly email)
                          ▲            │ approvals, decisions
                          │            ▼
   ┌──────────────────────┴──────────────────────────────┐
   │  Orchestrator (Python, provider-neutral)             │
   │  phase gate → tools → runtime → store → report       │
   │  · SQLite store: cases · decisions · runs (per site) │
   │  · profiles: <property>-<environment>, write-capped  │
   │  · read-only dashboard (GET-only, profile switcher)  │
   │  · GitOps auto-deploy (tests-gated, auto-rollback)   │
   └──────┬───────────────┬───────────────┬───────────────┘
          ▼               ▼               ▼
     GSC + GA4      WP connector     Ads platforms
    (production,   (staging drafts;  (not yet
     read-only)     production reads, provisioned)
                    writes disabled
                    server-side)
```

- **Specialist roles** (SEO / Ads / Analytics / Content / Local) run as prompts under one
  coordinator; a hosted Managed-Agents session driver also exists. Promotion to independent
  agent threads happens only when value is proven.
- **Memory**: cases with append-only journals and confidence evolution; a decision queue the
  agent treats as authoritative (approved = in force, rejected = never re-proposed).
- **Reports**: scheduled weekly (systemd timer), calibrated by ~15 tested reporting rules,
  mechanically guaranteed dates/masking/labels, deterministic lint.

## Repository layout

```
orchestrator/      Python platform: tools, phase gate, store, runtimes, report, dashboard, CLI
  profiles/        <property>-<environment>.env (examples; real files live on the VPS, mode 600)
  deployments/     systemd units (weekly report, dashboard, GitOps auto-deploy) + setup README
wordpress-plugin/  tc-growth-connector (PHP): read + draft endpoints, HMAC auth, audit log,
                   TC_GROWTH_DISABLE_WRITES server-side kill-switch for production installs
scripts/           operational scripts (e.g. wp05_finalize.sh)
docs/              VISION · ROADMAP · STATUS · VALIDATION · SITE_PROFILE · workpackages/ ·
                   incidents/ · ARCHITECTURE · SETUP · RUNBOOK
agents/            optional Managed Agents YAML (hosted runtime variant)
```

## Status (summary — `docs/STATUS.md` is authoritative)

- ✅ Autonomous weekly loop on the VPS (read → reason → investigate → report → email)
- ✅ Governed memory: cases, decisions, runs; CLI approvals; confidence evolution
- ✅ Multi-site profiles (`tossacycling-staging` / `tossacycling-production`), production
  read-only by construction on BOTH sides (profile cap + connector write routes not registered)
- ✅ Read-only dashboard: Today view, cases, decisions, validation report, deployment report,
  request-scoped profile switcher, GET-only JSON API
- ✅ GitOps: merges to `main` self-deploy in ≤5 min behind the full test suite, auto-rollback
- ✅ CI + on-box suite — **125+ tests** (see the latest PR/deploy record for the exact count)
- 🔶 Release 0.3 validation in progress: operational gate run #1 clean (2026-07-13); production
  profile connected DORMANT (WP-05); scheduled production shadow mode gated on 0.3 sign-off

## Quick start (own deployment)

1. `docs/SETUP.md` — credentials for GSC/GA4 (service account), SMTP, WordPress application
   password + HMAC key. Secrets live in `orchestrator/secrets/` (mode 600), never in git.
2. Install `tc-growth-connector` on the WordPress site — with
   `define( 'TC_GROWTH_DISABLE_WRITES', true );` in `wp-config.php` for any production install.
3. Create a profile from `orchestrator/profiles/*.env.example`, then
   `python -m tc_growth.cli --site <profile> db-init && ... smoke wp_list '{"kind":"pages"}'`.
4. systemd units in `orchestrator/deployments/systemd/` (weekly report, dashboard, auto-deploy).

## Models

Task-kind → model tier via `tc_growth.config.model_for` (override: `TC_MODEL_POLICY`):
weekly reports on Sonnet, investigations on Opus, monitoring on Haiku. The runtime layer is
the only provider-aware code — swapping providers never touches tools or business rules.
