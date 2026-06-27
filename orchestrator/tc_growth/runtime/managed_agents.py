"""Managed Agents session driver — the hosted runtime.

This is the link that makes `agents/` work end-to-end. The hosted Claude agent runs on
Anthropic's infrastructure; when it calls one of our custom tools it emits an
`agent.custom_tool_use` event. We answer it HOST-SIDE with our own credentials and reply with a
`user.custom_tool_result` — so Google/Meta/WordPress secrets never enter the sandbox.

The code-level phase gate (`core.approval.is_tool_allowed`) is enforced here too, independent of
the agent's own `always_ask` permission policies — either layer alone blocks an unapproved action.

This module (with anthropic_runtime.py) is the ONLY place that imports the provider SDK.
"""

from __future__ import annotations

import json
from typing import Any

from typing import Callable

from ..config import get_settings
from ..core.approval import Phase, is_tool_allowed, needs_confirmation
from ..tools.base import ToolRegistry
from .base import RuntimeResult


def _etype(event: Any) -> str:
    return getattr(event, "type", "") or ""


def _stop_reason_type(event: Any) -> str:
    stop = getattr(event, "stop_reason", None)
    if stop is None:
        return ""
    return getattr(stop, "type", "") or (stop.get("type", "") if isinstance(stop, dict) else "")


class ManagedAgentsRuntime:
    """Drives a Managed Agents session, executing our custom tools host-side.

    Conforms to the AgentRuntime surface. `system`/`model` live on the pre-created agent, so they
    are accepted for protocol compatibility; the session references the agent by id instead.
    """

    def __init__(
        self,
        *,
        agent_id: str | None = None,
        environment_id: str | None = None,
        api_key: str | None = None,
        client: Any | None = None,
        confirm: Callable[[str, dict], bool] | None = None,
    ):
        # Human-confirmation hook for ALWAYS_ASK tools. None (the default) => such tools are
        # refused, so autonomous / scheduled runs can never trigger a live change.
        self._confirm = confirm
        if client is not None:
            self._client = client
        else:
            import anthropic

            self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

        import os

        self._agent_id = agent_id or os.environ.get("TC_COORDINATOR_AGENT_ID", "")
        self._environment_id = environment_id or os.environ.get("TC_ENV_ID", "")

    def run(
        self,
        *,
        system: str,
        task: str,
        tools: ToolRegistry,
        phase: Phase,
        model: str | None = None,
        max_iterations: int = 12,  # noqa: ARG002
    ) -> RuntimeResult:
        return self.run_session(task=task, tools=tools, phase=phase)

    def run_session(self, *, task: str, tools: ToolRegistry, phase: Phase) -> RuntimeResult:
        if not self._agent_id or not self._environment_id:
            raise RuntimeError(
                "Managed Agents runtime needs TC_COORDINATOR_AGENT_ID and TC_ENV_ID "
                "(create the agent + environment from agents/*.yaml first)."
            )

        beta = self._client.beta
        session = beta.sessions.create(agent=self._agent_id, environment_id=self._environment_id)

        # Stream-first: open the stream BEFORE sending the kickoff so no early events are missed.
        stream = beta.sessions.events.stream(session_id=session.id)
        beta.sessions.events.send(
            session_id=session.id,
            events=[{"type": "user.message", "content": [{"type": "text", "text": task}]}],
        )

        texts: list[str] = []
        tool_calls: list[dict] = []
        blocked: list[dict] = []

        for event in stream:
            kind = _etype(event)

            if kind == "agent.message":
                for block in getattr(event, "content", []) or []:
                    if getattr(block, "type", "") == "text":
                        texts.append(getattr(block, "text", ""))

            elif kind == "agent.custom_tool_use":
                name = getattr(event, "name", "")
                args = dict(getattr(event, "input", {}) or {})
                use_id = getattr(event, "id", "")

                if not is_tool_allowed(name, phase):
                    blocked.append({"tool": name, "phase": int(phase), "reason": "phase"})
                    self._send_tool_result(
                        beta, session.id, use_id,
                        f"Blocked: tool '{name}' is not permitted in phase {int(phase)}. "
                        "Requires a higher phase / human approval.",
                        is_error=True,
                    )
                    continue

                if needs_confirmation(name) and not self._confirmed(name, args):
                    blocked.append({"tool": name, "phase": int(phase), "reason": "confirmation"})
                    self._send_tool_result(
                        beta, session.id, use_id,
                        f"Blocked: tool '{name}' requires explicit human confirmation, which is "
                        "not available in this run.",
                        is_error=True,
                    )
                    continue

                payload = tools.dispatch(name, args)
                tool_calls.append({"tool": name, "input": args, "ok": payload.get("ok")})
                self._send_tool_result(beta, session.id, use_id, _stringify(payload))

            elif kind == "session.status_idle":
                if _stop_reason_type(event) != "requires_action":
                    break

            elif kind == "session.status_terminated":
                break

        return RuntimeResult(text="".join(texts), tool_calls=tool_calls, blocked_calls=blocked)

    def _confirmed(self, name: str, args: dict) -> bool:
        return bool(self._confirm and self._confirm(name, args))

    @staticmethod
    def _send_tool_result(beta: Any, session_id: str, use_id: str, text: str, *, is_error: bool = False) -> None:
        event: dict[str, Any] = {
            "type": "user.custom_tool_result",
            "custom_tool_use_id": use_id,
            "content": [{"type": "text", "text": text}],
        }
        if is_error:
            event["is_error"] = True
        beta.sessions.events.send(session_id=session_id, events=[event])


def _stringify(payload: Any) -> str:
    return json.dumps(payload, default=str)[:50000]


def build_default() -> ManagedAgentsRuntime:
    get_settings()
    return ManagedAgentsRuntime()
