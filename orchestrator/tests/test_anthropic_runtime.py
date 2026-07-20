"""AnthropicRuntime request-shape + usage-capture tests.

Uses a fake client so no `anthropic` package (and no network) is needed: the point is to prove
what our code SENDS (prompt caching enabled) and what it KEEPS (cache usage counters), not to
test the SDK itself. The runtime instance is built via __new__ to skip the SDK import in
__init__ — CI does not install the provider extra.
"""

from __future__ import annotations

from types import SimpleNamespace

from tc_growth.core.approval import Phase
from tc_growth.runtime.anthropic_runtime import AnthropicRuntime
from tc_growth.tools.base import Tool, ToolRegistry


def _text_response(text: str, *, cache_creation: int = 0, cache_read: int = 0):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=cache_read,
        ),
    )


def _tool_response(tool_name: str, *, cache_creation: int = 0, cache_read: int = 0):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id="tu_1", name=tool_name, input={})],
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=cache_read,
        ),
    )


class _FakeClient:
    def __init__(self, responses):
        self.calls: list[dict] = []
        self._responses = list(responses)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def _runtime(fake_client) -> AnthropicRuntime:
    rt = AnthropicRuntime.__new__(AnthropicRuntime)  # skip __init__ (would import anthropic)
    rt._client = fake_client
    rt._confirm = None
    return rt


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(Tool(
        name="case_search",
        description="stub",
        input_schema={"type": "object"},
        handler=lambda args: {"ok": True, "hits": []},
    ))
    return reg


def test_prompt_caching_enabled_on_every_request():
    """Every messages.create call must carry the top-level 1h-TTL cache_control."""
    client = _FakeClient([_tool_response("case_search"), _text_response("done")])
    result = _runtime(client).run(
        system="SYSTEM", task="TASK", tools=_registry(), phase=Phase.READ_ONLY,
    )
    assert result.text == "done"
    assert len(client.calls) == 2
    for call in client.calls:
        assert call["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_cache_usage_tokens_accumulate_into_result():
    """Cache counters from usage are summed across loop iterations and returned."""
    client = _FakeClient([
        _tool_response("case_search", cache_creation=5000, cache_read=0),
        _text_response("done", cache_creation=0, cache_read=5000),
    ])
    result = _runtime(client).run(
        system="SYSTEM", task="TASK", tools=_registry(), phase=Phase.READ_ONLY,
    )
    assert result.cache_creation_tokens == 5000
    assert result.cache_read_tokens == 5000
    assert result.prompt_tokens == 200
    assert result.completion_tokens == 40


def test_missing_cache_fields_degrade_to_zero():
    """A usage object without cache fields (older API shape) must not break the run."""
    resp = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="ok")],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    client = _FakeClient([resp])
    result = _runtime(client).run(
        system="SYSTEM", task="TASK", tools=_registry(), phase=Phase.READ_ONLY,
    )
    assert result.cache_creation_tokens == 0
    assert result.cache_read_tokens == 0


def test_persist_run_writes_cache_counters_to_ledger_detail(monkeypatch):
    """persist_run records cache usage in the runs.detail column (additive, no schema change)."""
    import json

    from tc_growth import store as store_mod
    from tc_growth.report import persist_run
    from tc_growth.runtime.base import RuntimeResult

    logged: dict = {}

    class _FakeStore:
        def log_run(self, **kwargs):
            logged.update(kwargs)
            return 1

    monkeypatch.setattr(store_mod, "open_store", lambda *a, **kw: _FakeStore())

    persist_run(
        "weekly_report",
        RuntimeResult(
            text="# Report", model="m", prompt_tokens=10, completion_tokens=5,
            cache_creation_tokens=4096, cache_read_tokens=0,
        ),
        started_at="2026-07-20T07:00:00", duration_s=1.0,
    )
    assert json.loads(logged["detail"]) == {
        "cache_creation_tokens": 4096,
        "cache_read_tokens": 0,
    }


def test_persist_run_detail_stays_null_without_cache_data(monkeypatch):
    """Runtimes that don't report caching keep detail NULL — no fake zeros in the ledger."""
    from tc_growth import store as store_mod
    from tc_growth.report import persist_run
    from tc_growth.runtime.base import RuntimeResult

    logged: dict = {}

    class _FakeStore:
        def log_run(self, **kwargs):
            logged.update(kwargs)
            return 1

    monkeypatch.setattr(store_mod, "open_store", lambda *a, **kw: _FakeStore())

    persist_run(
        "weekly_report",
        RuntimeResult(text="# Report", model="m"),
        started_at="2026-07-20T07:00:00", duration_s=1.0,
    )
    assert logged["detail"] is None
