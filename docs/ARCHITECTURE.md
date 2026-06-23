# Architecture

## Goals

Elevate SEO/positioning, analyse Google + Meta ads, and tie everything to real WooCommerce
bookings and revenue — without risking the rental/checkout system.

## Three layers

```
WordPress / WooCommerce
   └─ tc-growth-connector plugin  (read endpoints + DRAFT-ONLY writes + audit log)
                │  signed REST (App Password + HMAC)
                ▼
Orchestrator (Python, provider-neutral)
   ├─ tools/    host-side API clients: WP, Search Console, GA4, Google Ads, Meta, GBP, PageSpeed
   ├─ core/     business logic: KPIs, opportunity scoring, approval/phase gate
   └─ runtime/  AI provider adapter (Claude today; swappable)
                │  (Managed Agents: custom tools executed host-side; secrets stay out of sandbox)
                ▼
AI runtime — Claude Opus 4.8 on Anthropic Managed Agents (preferred first runtime)
```

## Why this shape

- **Thin website.** WordPress only exposes controlled data and accepts drafts. Booking/checkout
  untouched and fast. The connector is removable without affecting rentals/orders/payments.
- **Provider-neutral core.** `tools/` and `core/` import no AI SDK (enforced by a test). Only
  `runtime/` knows the provider, so Claude can be swapped for OpenAI/Gemini/a cheaper model later.
- **Host-side custom tools.** The orchestrator executes tool calls with its own credentials and
  answers the agent's `custom_tool_use` events. Google/Meta tokens never enter the sandbox or a
  prompt. We also control OAuth refresh ourselves rather than depending on vault auto-refresh.
- **Two-layer guardrail.** A code-level **phase gate** (`core/approval.py`) plus `always_ask`
  permission policies on draft/spend tools. Either layer alone blocks an unapproved action.

## The business chain

`keyword → landing page → availability → price → booking → revenue → action`. `core/opportunities`
scores Search Console rows (high-impression/low-CTR, position 5-20) and flags wasted ad spend, so
the LLM reasons over real, pre-ranked numbers.

## Multi-agent stance

Phase 1: five specialists (SEO / Ads / Analytics / Content / Local) are **roles** in one
coordinator prompt. Phase 2+: promote any role to a standalone Managed Agents **thread** (its own
context + tools, shared workspace) via the coordinator's `multiagent` roster. See `agents/`.

## Models

- `claude-opus-4-8` — coordinator + analysis (default).
- `claude-haiku-4-5` — cheap high-volume sub-tasks.
- `claude-fable-5` — reserved for the hardest occasional strategy runs.
