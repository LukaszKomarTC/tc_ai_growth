"""load_env() must export .env into the PROCESS environment so third-party SDKs (Anthropic) and
os.environ lookups (Meta/Telegram) can see the keys — pydantic Settings alone does not do this."""

from __future__ import annotations

import os

import tc_growth.config as config


def test_load_env_exports_to_process_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TC_TEST_SENTINEL=hello-from-env\n")
    monkeypatch.setattr(config, "ENV_PATH", env_file)
    monkeypatch.delenv("TC_TEST_SENTINEL", raising=False)

    config.load_env()

    assert os.environ.get("TC_TEST_SENTINEL") == "hello-from-env"


def test_load_env_does_not_override_real_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TC_TEST_SENTINEL=from-file\n")
    monkeypatch.setattr(config, "ENV_PATH", env_file)
    monkeypatch.setenv("TC_TEST_SENTINEL", "from-real-env")

    config.load_env()  # override=False → the real env var wins (e.g. injected by systemd)

    assert os.environ["TC_TEST_SENTINEL"] == "from-real-env"


def test_secrets_path_is_absolute_and_cwd_independent(tmp_path, monkeypatch):
    # Running a CLI command from outside orchestrator/ must not change where credentials are
    # looked up (a CWD-relative path broke GSC/GA4 when invoked from the repo root).
    monkeypatch.chdir(tmp_path)  # simulate running from an arbitrary directory
    p = config.secrets_path("google-service-account.json")
    assert p.is_absolute()
    assert p == config.ENV_PATH.parent / "secrets" / "google-service-account.json"


def test_secrets_path_honours_override(monkeypatch):
    monkeypatch.setenv("TC_SECRETS_DIR", "/etc/tc-secrets")
    p = config.secrets_path("google-ads.yaml")
    assert str(p) == "/etc/tc-secrets/google-ads.yaml"
