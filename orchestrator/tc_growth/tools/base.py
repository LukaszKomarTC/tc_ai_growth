"""Provider-neutral tool abstraction.

A `Tool` is just a name, a human/LLM-readable description, a JSON Schema for its input, and a
handler. Runtime adapters (runtime/) convert a list of `Tool`s into the provider's native tool
format (Anthropic custom tools, OpenAI functions, Gemini function declarations, ...).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


class ToolError(Exception):
    """Raised by a tool handler when the call fails in an expected, reportable way."""


@dataclass(frozen=True)
class Tool:
    """A single host-side tool the agent can call."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]

    def run(self, arguments: dict[str, Any]) -> Any:
        """Execute the tool with validated-by-the-model arguments."""
        return self.handler(arguments or {})

    def to_provider_schema(self) -> dict[str, Any]:
        """The shape most providers accept (name/description/input_schema)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class ToolRegistry:
    """Collects tools so a runtime can hand the whole set to the model."""

    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError(f"Unknown tool: {name}")
        return self._tools[name]

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def dispatch(self, name: str, arguments: dict[str, Any]) -> Any:
        """Run a tool by name. ALL failures are returned as structured payloads, never raised, so
        a single tool can never crash the run or the agent loop — the model/report just sees an
        error result and moves on. Expected failures use ToolError; anything else is caught as a
        fail-safe and reported with its type."""
        try:
            return {"ok": True, "result": self.get(name).run(arguments)}
        except ToolError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # fail-safe — must never propagate out of a tool call
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# Module-level registry the tool modules append to on import.
registry = ToolRegistry()
