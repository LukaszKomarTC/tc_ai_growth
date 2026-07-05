"""Provider-neutral runtime contract.

A runtime takes a system prompt, a user task, and a tool registry, runs the agentic loop
(calling phase-allowed tools), and returns the final text plus a transcript of tool calls.
Business logic and tools depend only on this protocol — never on a concrete provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..core.approval import Phase
from ..tools.base import ToolRegistry


@dataclass
class RuntimeResult:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    blocked_calls: list[dict] = field(default_factory=list)
    # Usage — provider-neutral token counts for cost logging (None if the runtime can't report it).
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class AgentRuntime(Protocol):
    """What every provider adapter must implement."""

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
        ...
