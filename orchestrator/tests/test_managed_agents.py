"""Managed Agents driver: verify host-side tool dispatch + the code-level phase gate, using a
fake SDK client so no network/credentials are needed."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from tc_growth.core.approval import Phase
from tc_growth.runtime.managed_agents import ManagedAgentsRuntime
from tc_growth.tools.base import Tool, ToolRegistry


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(Tool(
        name="gsc_search_analytics",  # read tool — allowed in READ_ONLY
        description="read",
        input_schema={"type": "object"},
        handler=lambda args: {"rows": 1},
    ))
    reg.register(Tool(
        name="wp_create_seo_draft",  # draft tool — blocked in READ_ONLY
        description="draft",
        input_schema={"type": "object"},
        handler=lambda args: {"draft_id": 99},
    ))
    reg.register(Tool(
        name="publish_seo_draft",  # always-ask tool — needs confirmation even at phase 3
        description="publish",
        input_schema={"type": "object"},
        handler=lambda args: {"applied": True},
    ))
    return reg


class _FakeEventsAPI:
    def __init__(self, events: list[Any], sent: list[dict]):
        self._events = events
        self._sent = sent

    def stream(self, *, session_id: str):  # noqa: ARG002
        return iter(self._events)

    def send(self, *, session_id: str, events: list[dict]):  # noqa: ARG002
        self._sent.extend(events)


class _FakeSessionsAPI:
    def __init__(self, events: list[Any], sent: list[dict]):
        self.events = _FakeEventsAPI(events, sent)

    def create(self, *, agent: str, environment_id: str):  # noqa: ARG002
        return SimpleNamespace(id="sesn_test")


class _FakeClient:
    def __init__(self, events: list[Any], sent: list[dict]):
        self.beta = SimpleNamespace(sessions=_FakeSessionsAPI(events, sent))


def _tool_use(name: str, use_id: str):
    return SimpleNamespace(type="agent.custom_tool_use", name=name, id=use_id, input={})


def _idle_terminal():
    return SimpleNamespace(type="session.status_idle", stop_reason=SimpleNamespace(type="end_turn"))


def test_read_tool_dispatched_and_draft_blocked_in_read_only():
    sent: list[dict] = []
    events = [
        _tool_use("gsc_search_analytics", "u1"),
        _tool_use("wp_create_seo_draft", "u2"),
        SimpleNamespace(type="agent.message", content=[SimpleNamespace(type="text", text="done")]),
        _idle_terminal(),
    ]
    runtime = ManagedAgentsRuntime(
        agent_id="agent_x", environment_id="env_x", client=_FakeClient(events, sent)
    )
    result = runtime.run_session(task="go", tools=_registry(), phase=Phase.READ_ONLY)

    # The read tool ran; the draft tool was blocked by the phase gate.
    assert [c["tool"] for c in result.tool_calls] == ["gsc_search_analytics"]
    assert [b["tool"] for b in result.blocked_calls] == ["wp_create_seo_draft"]
    assert result.text == "done"

    # Two tool results were sent back; the blocked one is flagged is_error.
    results = [e for e in sent if e["type"] == "user.custom_tool_result"]
    assert len(results) == 2
    blocked_result = next(e for e in results if e["custom_tool_use_id"] == "u2")
    assert blocked_result.get("is_error") is True


def test_draft_tool_allowed_in_drafts_phase():
    sent: list[dict] = []
    events = [_tool_use("wp_create_seo_draft", "u1"), _idle_terminal()]
    runtime = ManagedAgentsRuntime(
        agent_id="agent_x", environment_id="env_x", client=_FakeClient(events, sent)
    )
    result = runtime.run_session(task="go", tools=_registry(), phase=Phase.DRAFTS)
    assert [c["tool"] for c in result.tool_calls] == ["wp_create_seo_draft"]
    assert result.blocked_calls == []


def test_always_ask_tool_blocked_without_confirmation_even_at_phase3():
    sent: list[dict] = []
    events = [_tool_use("publish_seo_draft", "u1"), _idle_terminal()]
    runtime = ManagedAgentsRuntime(
        agent_id="agent_x", environment_id="env_x", client=_FakeClient(events, sent)
    )
    result = runtime.run_session(task="go", tools=_registry(), phase=Phase.CONTROLLED_EXECUTION)
    assert result.tool_calls == []
    assert result.blocked_calls and result.blocked_calls[0]["reason"] == "confirmation"


def test_always_ask_tool_runs_with_confirmation_at_phase3():
    sent: list[dict] = []
    events = [_tool_use("publish_seo_draft", "u1"), _idle_terminal()]
    runtime = ManagedAgentsRuntime(
        agent_id="agent_x", environment_id="env_x",
        client=_FakeClient(events, sent), confirm=lambda name, args: True,
    )
    result = runtime.run_session(task="go", tools=_registry(), phase=Phase.CONTROLLED_EXECUTION)
    assert [c["tool"] for c in result.tool_calls] == ["publish_seo_draft"]
    assert result.blocked_calls == []
