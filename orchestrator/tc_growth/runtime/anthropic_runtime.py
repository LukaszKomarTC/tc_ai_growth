"""Claude (Anthropic) runtime adapter — the preferred first runtime.

Runs a manual, phase-gated tool loop on the Messages API. Because our tools execute host-side
(so credentials never enter a sandbox), a controlled local loop is the cleanest fit and lets us
enforce the approval phase gate in code before any tool is dispatched.

The hosted **Managed Agents** path (coordinator + specialist threads, vaults, scheduled
deployments) is configured separately under `agents/` and `deployments/`; this adapter is the
portable building block and the local smoke-test harness.

This module is the ONLY one that imports `anthropic`.
"""

from __future__ import annotations

from typing import Callable

from ..core.approval import Phase, is_tool_allowed, needs_confirmation
from ..tools.base import ToolRegistry
from .base import RuntimeResult

# Default to Opus 4.8 (per the claude-api guidance). Swap via Settings.ai_model.
_DEFAULT_MODEL = "claude-opus-4-8"


class AnthropicRuntime:
    """Implements the AgentRuntime protocol against the Claude Messages API."""

    def __init__(self, api_key: str | None = None, confirm: Callable[[str, dict], bool] | None = None):
        import anthropic  # local import keeps the provider dependency contained

        # Human-confirmation hook for ALWAYS_ASK tools; None => such tools are refused.
        self._confirm = confirm
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def run(
        self,
        *,
        system: str,
        task: str,
        tools: ToolRegistry,
        phase: Phase,
        model: str | None = None,
        max_iterations: int = 12,
    ) -> RuntimeResult:
        model = model or _DEFAULT_MODEL
        tool_specs = [t.to_provider_schema() for t in tools.all()]
        messages: list[dict] = [{"role": "user", "content": task}]
        tool_calls: list[dict] = []
        blocked: list[dict] = []

        for _ in range(max_iterations):
            response = self._client.messages.create(
                model=model,
                max_tokens=16000,
                system=system,
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                tools=tool_specs,
                messages=messages,
            )

            if response.stop_reason != "tool_use":
                text = "".join(b.text for b in response.content if b.type == "text")
                return RuntimeResult(text=text, tool_calls=tool_calls, blocked_calls=blocked)

            messages.append({"role": "assistant", "content": response.content})

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                # Phase gate enforced in code — independent of the model's judgement.
                if not is_tool_allowed(block.name, phase):
                    blocked.append({"tool": block.name, "phase": int(phase), "reason": "phase"})
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "is_error": True,
                        "content": f"Blocked: tool '{block.name}' is not permitted in phase "
                                   f"{int(phase)}. This action requires a higher phase / human approval.",
                    })
                    continue

                # Always-ask tools need an explicit per-call human confirmation.
                if needs_confirmation(block.name) and not (self._confirm and self._confirm(block.name, dict(block.input))):
                    blocked.append({"tool": block.name, "phase": int(phase), "reason": "confirmation"})
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "is_error": True,
                        "content": f"Blocked: tool '{block.name}' requires explicit human "
                                   "confirmation, which is not available in this run.",
                    })
                    continue

                payload = tools.dispatch(block.name, dict(block.input))
                tool_calls.append({"tool": block.name, "input": dict(block.input), "ok": payload.get("ok")})
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _stringify(payload),
                })

            messages.append({"role": "user", "content": results})

        return RuntimeResult(
            text="(stopped: reached max iterations)",
            tool_calls=tool_calls,
            blocked_calls=blocked,
        )


def _stringify(payload) -> str:
    import json

    return json.dumps(payload, default=str)[:50000]
