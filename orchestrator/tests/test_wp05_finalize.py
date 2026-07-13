"""Integration tests for scripts/wp05_finalize.sh — the WP-05 store finalizer.

Runs the REAL script end-to-end against a throwaway profile + store using the test-only
overrides (WP05_APP/SITE/PY/NO_REEXEC). Covers the three states the script must handle:
correct pre-state -> seeds and reports COMPLETE; rerun -> ALREADY COMPLETE with no writes;
wrong pre-state -> blocks without touching the store.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tc_growth import store

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "wp05_finalize.sh"

EXPECTED_TITLES = 6


@pytest.fixture()
def wp05_env(tmp_path):
    """A temp profile + store shaped like the production pre-seed state (2 cases, 0/0)."""
    db = tmp_path / "wp05-test-store.db"
    site = "wp05test"
    profile = REPO / "orchestrator" / "profiles" / f"{site}.env"   # *.env is gitignored
    profile.write_text(
        "TC_SITE_NAME=Tossa Cycling\nTC_ENV_KIND=production\nTC_ALLOW_WRITES=false\n"
        f"TC_DB_PATH={db}\n"
    )
    s = store.SqliteStore(db)
    s.create_case(ref="INC-2026-02-01", title="Tobacco-spam URLs on tossacycling.com",
                  category="incident", status="monitoring", opened_by="human")
    s.create_case(ref="TRK-20260706-050158", title="GA4 purchase tracking verification",
                  category="tracking", status="monitoring", opened_by="human")
    s.close()
    env = {k: v for k, v in os.environ.items() if not k.startswith("TC_")}
    env.update({
        "WP05_APP": str(REPO), "WP05_SITE": site, "WP05_PY": sys.executable,
        "WP05_NO_REEXEC": "1", "TC_DB_PATH": str(db),
    })
    try:
        yield {"db": db, "site": site, "env": env}
    finally:
        profile.unlink(missing_ok=True)


def _run(env):
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)


def _counts(db):
    s = store.SqliteStore(db)
    out = (len(s.list_cases(limit=100)), len(s.list_decisions(limit=100)), len(s.list_runs(limit=100)))
    s.close()
    return out


def test_seeds_six_decisions_then_reruns_idempotently(wp05_env):
    r = _run(wp05_env["env"])
    assert r.returncode == 0, r.stderr
    assert "WP-05 COMPLETE" in r.stdout
    assert "store backup:" in r.stdout            # backup taken before writing
    assert _counts(wp05_env["db"]) == (2, EXPECTED_TITLES, 0)

    # Origin D#2 and D#6 must be linked to their documented cases.
    s = store.SqliteStore(wp05_env["db"])
    linked = {d.title: d.case_id for d in s.list_decisions(limit=100)}
    inc = s.get_case_by_ref("INC-2026-02-01").id
    trk = s.get_case_by_ref("TRK-20260706-050158").id
    s.close()
    assert linked["Origin D#2 — Serve 410 for verified tobacco/vape spam URL patterns and submit targeted GSC removals"] == inc
    assert linked["Origin D#6 — Apply noindex protection to order-received and order-pay URL patterns"] == trk

    # Rerun: no new rows, explicit ALREADY COMPLETE, still exit 0.
    r2 = _run(wp05_env["env"])
    assert r2.returncode == 0, r2.stderr
    assert "WP-05 ALREADY COMPLETE" in r2.stdout
    assert _counts(wp05_env["db"]) == (2, EXPECTED_TITLES, 0)


def test_blocks_on_wrong_state_without_writing(wp05_env):
    # Corrupt the expected pre-state: add a third, unexpected case.
    s = store.SqliteStore(wp05_env["db"])
    s.create_case(ref="XXX-1", title="unexpected", category="incident",
                  status="open", opened_by="human")
    s.close()
    r = _run(wp05_env["env"])
    assert r.returncode != 0
    assert "WP-05 BLOCKED" in r.stderr
    assert _counts(wp05_env["db"]) == (3, 0, 0)   # nothing was written


def test_blocks_when_write_cap_missing(wp05_env, tmp_path):
    profile = REPO / "orchestrator" / "profiles" / f"{wp05_env['site']}.env"
    profile.write_text(profile.read_text().replace("TC_ALLOW_WRITES=false", "TC_ALLOW_WRITES=true"))
    r = _run(wp05_env["env"])
    assert r.returncode != 0
    assert "TC_ALLOW_WRITES=false not set" in r.stderr
    assert _counts(wp05_env["db"]) == (2, 0, 0)
