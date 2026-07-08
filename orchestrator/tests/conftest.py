"""Global test isolation.

Found 2026-07-08 by the maiden auto-deploy run: pytest executed on the VPS wrote a fake
'investigate' row into the LIVE run ledger, because a test exercised a persistence path and the
process inherited the real store location. Tests must never be able to touch a real store, no
matter what any individual test forgets — so every test gets a throwaway TC_DB_PATH by default
(tests that need a specific path still override it explicitly).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path, monkeypatch):
    monkeypatch.setenv("TC_DB_PATH", str(tmp_path / "test-isolated-store.db"))
