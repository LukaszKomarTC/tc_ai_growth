"""Host-side, provider-neutral API tools.

Each tool is a plain Python callable wrapped in a `Tool` spec (name + JSON schema + handler).
A runtime adapter translates these into the AI provider's tool/function format. None of these
modules import an AI SDK — that is what keeps the system provider-portable.
"""

from .base import Tool, ToolError, registry

__all__ = ["Tool", "ToolError", "registry"]
