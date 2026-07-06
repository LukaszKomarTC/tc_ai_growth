"""Multi-site profiles: selection, isolation, the write cap beneath the phase gate, labeling."""

from __future__ import annotations

import pytest

import tc_growth.config as config
from tc_growth.config import Settings, load_env, resolved_env_path, site_label, writes_allowed
from tc_growth.core.approval import Phase, is_tool_allowed


@pytest.fixture(autouse=True)
def _clean_site(monkeypatch):
    monkeypatch.delenv("TC_SITE", raising=False)
    monkeypatch.delenv("TC_ALLOW_WRITES", raising=False)


def test_no_site_falls_back_to_classic_env():
    # Backward compatible: existing single-site deployments keep working unchanged.
    assert resolved_env_path() == config.ENV_PATH


def test_site_selects_profile_and_exports_it(tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "prodtest.env").write_text(
        "TC_SITE_NAME=Prod Test\nTC_ENV_KIND=production\nTC_ALLOW_WRITES=false\n"
    )
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setenv("TC_SITE", "prodtest")
    monkeypatch.delenv("TC_SITE_NAME", raising=False)
    monkeypatch.delenv("TC_ENV_KIND", raising=False)

    assert resolved_env_path() == profiles / "prodtest.env"
    load_env()
    s = Settings()
    assert s.site_name == "Prod Test"
    assert s.env_kind == "production"
    assert s.allow_writes is False
    assert site_label(s) == "Prod Test · PRODUCTION"


def test_unknown_site_fails_loudly(tmp_path, monkeypatch):
    # Silently falling back to another site's credentials is the one unforgivable mistake.
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setenv("TC_SITE", "nope")
    with pytest.raises(SystemExit):
        load_env()


def test_write_cap_blocks_draft_tools_beneath_the_phase_gate(monkeypatch):
    # A read-only profile blocks every write tool EVEN at DRAFTS/CONTROLLED phase —
    # this is what makes production read-only by construction, not by convention.
    monkeypatch.setenv("TC_ALLOW_WRITES", "false")
    assert not writes_allowed()
    assert not is_tool_allowed("wp_create_seo_draft", Phase.DRAFTS)
    assert not is_tool_allowed("publish_seo_draft", Phase.CONTROLLED_EXECUTION)
    # Reads are unaffected — production shadow mode still observes everything.
    assert is_tool_allowed("gsc_search_analytics", Phase.READ_ONLY)
    assert is_tool_allowed("case_search", Phase.READ_ONLY)

    monkeypatch.setenv("TC_ALLOW_WRITES", "true")
    assert is_tool_allowed("wp_create_seo_draft", Phase.DRAFTS)


def test_each_site_gets_its_own_store(tmp_path, monkeypatch):
    from tc_growth.store.db import resolved_db_path

    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "siteb.env").write_text("TC_SITE_NAME=B\n")
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr("tc_growth.store.db.BASE_DIR", tmp_path)
    monkeypatch.delenv("TC_DB_PATH", raising=False)

    assert resolved_db_path().name == "tc_growth.db"          # classic mode
    monkeypatch.setenv("TC_SITE", "siteb")
    assert resolved_db_path().name == "tc_growth-siteb.db"    # per-site memory isolation


def test_report_header_carries_site_label(monkeypatch):
    from tc_growth import report
    from tc_growth.runtime.base import RuntimeResult

    class _RT:
        def run(self, **kw):
            return RuntimeResult(text="ok")

    monkeypatch.setenv("TC_SITE_NAME", "Tossa Staging")
    monkeypatch.setenv("TC_ENV_KIND", "staging")
    out = report.build_weekly_report(_RT(), phase=Phase.READ_ONLY, persist=False)
    assert "Tossa Staging · STAGING" in out


def test_dashboard_banner_shows_environment(monkeypatch):
    from tc_growth import store
    from tc_growth.dashboard import render_overview

    monkeypatch.setenv("TC_SITE_NAME", "Prod X")
    monkeypatch.setenv("TC_ENV_KIND", "production")
    monkeypatch.setenv("TC_ALLOW_WRITES", "false")
    s = store.open_store(":memory:")
    page = render_overview(s)
    assert "Prod X · PRODUCTION" in page
    assert "READ-ONLY PROFILE" in page
    assert "Deployment" in page                     # GitOps observability section present
    s.close()


def test_cli_site_flag_sets_env(tmp_path, monkeypatch, capsys):
    from tc_growth.cli import main

    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "s1.env").write_text("TC_SITE_NAME=S1\n")
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    # Register TC_SITE with monkeypatch BEFORE main() overwrites it, so teardown restores
    # the pre-test state even though main() sets os.environ directly.
    monkeypatch.setenv("TC_SITE", "")
    rc = main(["--site", "s1", "validation"])
    import os

    assert os.environ.get("TC_SITE") == "s1"
    assert rc in (0, 1)  # validation report may be empty in test env; flag handling is the point