"""Command-line entrypoints.

    python -m tc_growth.cli list-tools
    python -m tc_growth.cli smoke <tool_name> '<json args>'
    python -m tc_growth.cli weekly-report

`smoke` exercises a single host-side tool WITHOUT the AI runtime — the fastest way to surface
OAuth/vault/credential problems (the usual first failure point). `weekly-report` runs the full
coordinator via the configured provider runtime.
"""

from __future__ import annotations

import json
import sys

from .config import get_settings, load_env
from .core.approval import Phase
from .tools.load import load_all


def _build_runtime(kind: str = "messages"):
    """Instantiate the configured provider runtime. Only this function knows the provider.

    kind="messages"  -> local Messages-API tool loop (no Managed Agents needed; good for smoke).
    kind="managed"   -> hosted Managed Agents session driver (needs TC_COORDINATOR_AGENT_ID + TC_ENV_ID).
    """
    s = get_settings()
    if s.ai_provider != "anthropic":
        raise SystemExit(f"Unknown / unconfigured ai_provider: {s.ai_provider}")
    if kind == "managed":
        from .runtime.managed_agents import ManagedAgentsRuntime

        return ManagedAgentsRuntime()
    from .runtime.anthropic_runtime import AnthropicRuntime

    return AnthropicRuntime()


def cmd_list_tools() -> int:
    for tool in load_all().all():
        print(f"{tool.name:24} {tool.description.splitlines()[0]}")
    return 0


def cmd_smoke(name: str, raw_args: str) -> int:
    args = json.loads(raw_args) if raw_args else {}
    payload = load_all().dispatch(name, args)
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("ok") else 1


def cmd_weekly_report(kind: str = "messages") -> int:
    from .report import build_weekly_report, deliver

    runtime = _build_runtime(kind)
    report = build_weekly_report(runtime, phase=Phase.READ_ONLY)
    deliver(report)
    return 0


def main(argv: list[str] | None = None) -> int:
    load_env()  # export .env into the process environment (Anthropic SDK, Meta/Telegram tokens)
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "list-tools":
        return cmd_list_tools()
    if cmd == "smoke":
        return cmd_smoke(rest[0], rest[1] if len(rest) > 1 else "")
    if cmd == "weekly-report":
        # Optional: `weekly-report managed` to use the hosted Managed Agents runtime.
        return cmd_weekly_report(rest[0] if rest else "messages")
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
