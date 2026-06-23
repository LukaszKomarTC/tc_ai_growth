# Managed Agents control plane

Version-controlled config for the Anthropic Managed Agents runtime. Applied with the `ant` CLI;
the **data plane** (sessions, events, host-side custom-tool execution) is driven by the Python
orchestrator.

## Files

- `environment.yaml` — the cloud sandbox the agents run in.
- `coordinator.agent.yaml` — **the Phase 1 agent.** Implements all five specialists as *roles*
  inside one coordinator prompt (per review guidance: don't overbuild five autonomous workers
  on day one).
- `seo.agent.yaml` — **template** for promoting a role to a standalone multiagent thread later.

## Apply

```sh
ENV_ID=$(ant beta:environments create < environment.yaml --transform id -r)
AGENT_ID=$(ant beta:agents create < coordinator.agent.yaml --transform id -r)
# store ENV_ID + AGENT_ID (config/secrets manager); the orchestrator references them.
```

## Important notes

- **Custom tools run host-side.** The orchestrator answers `agent.custom_tool_use` events with
  its own credentials, so Google/Meta/WordPress secrets never enter the sandbox. This is also why
  we default to host-side tools over MCP-OAuth for the ad platforms (we control token refresh).
- **Two-layer guardrail.** The orchestrator enforces the phase gate in code (`core/approval.py`)
  *and* draft/spend tools carry `always_ask` permission policies here. Either layer alone blocks
  an unapproved action.
- **Keep tool schemas in sync with the registry** (`orchestrator/tc_growth/tools`), or generate
  the `tools:` block from it to avoid drift.
- **Provider-neutral.** This directory is Anthropic-specific by design — it is the *runtime*.
  The connector, tools, business logic, and approval rules do not depend on it, so the runtime
  is swappable.
