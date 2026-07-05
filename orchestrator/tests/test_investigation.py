"""Investigation mode: epistemic calibration is present, and the runner uses the forensic prompt."""

from __future__ import annotations

from tc_growth import prompts
from tc_growth.core.approval import Phase
from tc_growth.investigate import build_investigation
from tc_growth.runtime.base import RuntimeResult


def test_calibration_is_woven_into_both_prompts():
    # The observation-vs-conclusion rule must be in the growth coordinator AND the investigator.
    for text in (prompts.COORDINATOR, prompts.INVESTIGATION):
        assert "OBSERVATION" in text or "observation" in text
        assert "verification" in text.lower()
    # Investigation mode must explicitly tie asserting a compromise to a verification step.
    inv = prompts.INVESTIGATION.lower()
    assert "compromise" in inv
    assert "unless" in inv or "verification" in inv


class _FakeRuntime:
    """Records the system prompt + phase it was called with."""

    def __init__(self):
        self.system = None
        self.phase = None

    def run(self, *, system, task, tools, phase, model=None, max_iterations=12):
        self.system = system
        self.phase = phase
        return RuntimeResult(text="Observations: ...\nConclusion: historical (confidence: medium).")


def test_build_investigation_uses_forensic_prompt_and_read_only():
    rt = _FakeRuntime()
    out = build_investigation(rt, "tobacco spam URLs — timeline and active-vs-historical")
    assert rt.system == prompts.INVESTIGATION      # forensic prompt, not the growth coordinator
    assert rt.phase == Phase.READ_ONLY             # read-only
    assert "Forensic Investigation" in out
    assert "tobacco spam URLs" in out
