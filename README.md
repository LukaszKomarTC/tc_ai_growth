# TC AI Operations Platform

> **The checklist decides, not enthusiasm.**

An **AI Operations Platform** for **Tossa Cycling** — bike rentals, guided tours, eMTB/road
hire (Costa Brava / Tour de Girona). Growth (SEO, ads, analytics tied to real WooCommerce
bookings and revenue) is the platform's first specialist module; the platform itself is
governance, memory, confidence, validation, and observability. The model is a component.

The website stays thin: a small WordPress connector plugin exposes controlled data and accepts
**drafts only**. The "brain" runs externally, provider-neutral (Claude-first).

> ⚠️ **Safety first.** The system never publishes, never spends ad budget, and never touches
> prices, availability, the booking plugin, or checkout — those capabilities do not exist as
> tools. It produces drafts and reports for human approval. See [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

**Governance documents:** [`docs/VISION.md`](docs/VISION.md) (why — the constitution) ·
[`docs/ROADMAP.md`](docs/ROADMAP.md) (what) · [`docs/STATUS.md`](docs/STATUS.md) (where) ·
[`docs/VALIDATION.md`](docs/VALIDATION.md) (may we proceed). **Current mode: VALIDATE**
(Release 0.3 — no new capabilities).

## Architecture at a glance

```
                         Growth Coordinator (Opus 4.8)
        ┌───────────────┬───────────────┬───────────────┬──────────────┐
        ▼               ▼               ▼               ▼              ▼
   SEO Agent       Ads Agent       Analytics Agent  Content Agent   Local Agent
 (Search Console) (Google+Meta)   (GA4 + Woo)      (WP drafts)     (GBP + PageSpeed)
        │               │               │               │              │
        └───────────────┴──────── shared workspace + Memory Store ─────┘
```

- **Control plane** (`agents/`): agents + environment defined as version-controlled YAML,
  applied once with the `ant` CLI. Created once, referenced by ID — never re-created per run.
- **Data plane** (`orchestrator/`): a small Python service that opens sessions, streams events,
  and runs **host-side custom tools** (Search Console, GA4, Google Ads, Meta, GBP, PageSpeed,
  WordPress). Secrets live in Managed Agents **vaults**, never in the sandbox or prompts.
- **Website** (`wordpress-plugin/tc-growth-connector/`): read endpoints + draft-only write
  endpoints + an audit log. WooCommerce data via the native Woo REST API.

## Repository layout

```
agents/            Managed Agents config (coordinator + 5 specialists + environment), as YAML
orchestrator/      Python session driver, host-side custom tools, vault setup, weekly report
wordpress-plugin/  tc-growth-connector plugin (PHP)
docs/              ARCHITECTURE, SETUP, RUNBOOK
```

## Status

Phase 0 (foundations) + first increments:

- ✅ WordPress connector plugin (read + draft-only writes, HMAC auth, audit log)
- ✅ Provider-neutral orchestrator (tools / core / runtime), portability test-enforced
- ✅ Local Messages-API runtime **and** hosted Managed Agents session driver
- ✅ WooCommerce revenue attribution (bookings by source)
- ✅ Real report delivery (SMTP email + Telegram)
- ✅ CI (pytest + PHP lint) on push/PR — 14 tests green

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the design and the plan file for the full
phased roadmap.

## Quick start

1. Read [`docs/SETUP.md`](docs/SETUP.md) — OAuth setup for each platform and vault seeding.
2. Install the `tc-growth-connector` plugin on the WordPress site.
3. Create the Managed Agents environment + agents from `agents/` with the `ant` CLI.
4. Run the orchestrator smoke tests (`orchestrator/`), then trigger the weekly report.

## Models

- `claude-opus-4-8` — coordinator + analytical agents (default).
- `claude-haiku-4-5` — cheap high-volume sub-tasks (bulk fetch/parse, classification).
- `claude-fable-5` — reserved for the hardest occasional strategy runs (priced above Opus).
