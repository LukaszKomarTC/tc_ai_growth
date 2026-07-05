"""Slice 7: task-kind -> model policy (config-driven, measured before trusting cheap tiers)."""

from __future__ import annotations

from tc_growth.config import Settings, model_for
from tc_growth.core.approval import Phase
from tc_growth.runtime.base import RuntimeResult


def _settings(**kw) -> Settings:
    return Settings(**kw)


def test_default_tiers():
    s = _settings()
    assert model_for("weekly-report", s) == s.ai_model_mid       # routine reporting: mid tier
    assert model_for("investigate", s) == s.ai_model             # forensics: strong tier
    assert model_for("monitoring", s) == s.ai_model_cheap        # future checks: cheap tier
    assert model_for("anything-unknown", s) == s.ai_model        # fallback: strong


def test_explicit_policy_overrides_default_tier():
    s = _settings(model_policy={"weekly-report": "claude-opus-4-8"})
    assert model_for("weekly-report", s) == "claude-opus-4-8"
    # Other kinds untouched by the override.
    assert model_for("investigate", s) == s.ai_model


def test_policy_parses_from_env_json(monkeypatch):
    monkeypatch.setenv("TC_MODEL_POLICY", '{"weekly-report": "claude-haiku-4-5"}')
    s = Settings()
    assert model_for("weekly-report", s) == "claude-haiku-4-5"


class _CapturingRuntime:
    def __init__(self):
        self.model = None

    def run(self, *, system, task, tools, phase, model=None, max_iterations=12):
        self.model = model
        return RuntimeResult(text="ok")


def test_weekly_report_uses_policy_model(monkeypatch):
    from tc_growth import report

    monkeypatch.setattr(report, "model_for", lambda kind: {"weekly-report": "policy-model-x"}[kind])
    rt = _CapturingRuntime()
    report.build_weekly_report(rt, phase=Phase.READ_ONLY, persist=False)
    assert rt.model == "policy-model-x"
