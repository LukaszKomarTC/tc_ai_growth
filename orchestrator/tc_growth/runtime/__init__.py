"""AI provider adapters. This is the ONLY layer permitted to import a provider SDK.

To add a provider (OpenAI, Gemini, ...), implement `AgentRuntime` in a sibling module. tools/
and core/ never change.
"""

from .base import AgentRuntime, RuntimeResult

__all__ = ["AgentRuntime", "RuntimeResult"]
