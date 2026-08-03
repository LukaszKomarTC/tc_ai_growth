"""U3a — immutable report artifact persistence (WP-CONSOLE-USABILITY).

The trust chain under test: generation → validated immutable artifact → hash → persisted
artifact → email delivery → (dashboard display, U3b). The body stored must be byte-identical to
the body delivered; the hash is computed over exactly what is stored; the storage layer itself
refuses mutation of the artifact core (SQLite trigger, not API politeness); delivery status is
the only sanctioned mutation and is keyed BY HASH so it can only ever mark the bytes actually
sent."""

from __future__ import annotations

import hashlib
import pathlib
import sqlite3

import pytest

from tc_growth.report import VALIDATOR_VERSION, validate_report_artifact
from tc_growth.runtime.base import RuntimeResult
from tc_growth.store.sqlite import SqliteStore


class _FakeRuntime:
    """Minimal runtime double (kept local: test modules must not import each other — the
    `from tests.…` form broke under CI's pytest invocation, 2026-08-03)."""

    def __init__(self, text: str) -> None:
        self._text = text

    def run(self, *, system, task, tools, phase, model=None, max_iterations=12):
        return RuntimeResult(text=self._text)

BODY = ("# Tossa Cycling — Growth Report (2026-08-03)\n"
        "**Reporting window:** 2026-07-07 → 2026-08-03\n\n"
        "## SEO Opportunities\n- something\n\n## Ads Efficiency\n- something\n\n"
        "## Revenue Insights\n- something\n\n## Recommended Actions\n1. something\n")


def _store() -> SqliteStore:
    return SqliteStore(":memory:")


def _persist(s: SqliteStore, body: str = BODY, **over) -> int:
    kw = dict(kind="weekly-report", body=body, validator_ok=True, validator_reason=None,
              validator_version=VALIDATOR_VERSION, run_id=None, profile="Tossa Cycling",
              window="2026-07-07 → 2026-08-03", model="claude-test", cost_usd=0.5)
    kw.update(over)
    return s.persist_report_artifact(**kw)


def test_roundtrip_hash_and_fields():
    s = _store()
    aid = _persist(s)
    a = s.get_report_artifact(aid)
    assert a is not None
    assert a.body == BODY                                            # byte-identical
    assert a.content_sha256 == hashlib.sha256(BODY.encode("utf-8")).hexdigest()
    assert a.validator_ok == 1 and a.validator_version == VALIDATOR_VERSION
    assert a.delivery_status == "pending" and a.delivered_at is None
    assert a.kind == "weekly-report" and a.window == "2026-07-07 → 2026-08-03"


def test_artifact_core_is_immutable_at_the_database_layer():
    """Not API convention — the trigger aborts ANY write to the core, even raw SQL."""
    s = _store()
    aid = _persist(s)
    conn = s._conn
    for stmt, args in (
        ("UPDATE report_artifacts SET body = 'tampered' WHERE id = ?;", (aid,)),
        ("UPDATE report_artifacts SET content_sha256 = 'feedface' WHERE id = ?;", (aid,)),
        ("UPDATE report_artifacts SET validator_ok = 0 WHERE id = ?;", (aid,)),
        ("UPDATE report_artifacts SET generated_at = '1999-01-01' WHERE id = ?;", (aid,)),
    ):
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute(stmt, args)
    # ...while the sanctioned delivery mutation still works.
    s.set_artifact_delivery(aid, "delivered")
    a = s.get_report_artifact(aid)
    assert a.delivery_status == "delivered" and a.delivered_at is not None
    assert a.body == BODY                                            # core untouched


def test_delivery_marking_is_hash_keyed():
    """Delivery must attach to the exact bytes sent — not to 'the newest row'."""
    s = _store()
    first = _persist(s, body=BODY)
    second = _persist(s, body=BODY + "\nP.S. different bytes\n")
    sha_first = hashlib.sha256(BODY.encode("utf-8")).hexdigest()
    assert s.set_artifact_delivery_by_hash(sha_first, "delivered") is True
    assert s.get_report_artifact(first).delivery_status == "delivered"
    assert s.get_report_artifact(second).delivery_status == "pending"   # untouched
    assert s.set_artifact_delivery_by_hash("no-such-hash", "delivered") is False


def test_rejected_artifacts_are_stored_as_evidence():
    s = _store()
    aid = _persist(s, body="Good — all the data is in. Now I'll write the report.",
                   validator_ok=False, validator_reason="incomplete_report_artifact:too_short")
    a = s.get_report_artifact(aid)
    assert a.validator_ok == 0
    assert a.validator_reason == "incomplete_report_artifact:too_short"


def test_oversize_artifact_is_refused():
    s = _store()
    with pytest.raises(ValueError, match="too large"):
        _persist(s, body="x" * 2_000_001)


def test_build_and_deliver_close_the_chain(monkeypatch):
    """End-to-end through the real code path: build_weekly_report persists the artifact linked to
    its ledger run; deliver() marks THAT artifact delivered by hash. One shared store, no email."""
    import tc_growth.store as store_mod
    from tc_growth.report import build_weekly_report, deliver

    shared = SqliteStore(":memory:")

    class _NoClose:
        """memory.py closes the store it opens; the shared in-memory store must survive that."""
        def __getattr__(self, name):
            return (lambda: None) if name == "close" else getattr(shared, name)

    monkeypatch.setattr(store_mod, "open_store", lambda: _NoClose())
    monkeypatch.setattr("tc_growth.report.send_email", lambda subject, body, **kw: True)

    body = build_weekly_report(_FakeRuntime(text=BODY), persist=True)

    a = shared.latest_report_artifact(kind="weekly-report")
    assert a is not None
    assert a.body == body                                            # exactly what the caller got
    assert a.content_sha256 == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert a.run_id is not None                                      # ledger linkage
    runs = shared.list_runs(kind="weekly-report")
    assert runs and runs[0].id == a.run_id
    assert a.delivery_status == "pending"                            # persisted BEFORE delivery

    deliver(body, ok=True)
    a2 = shared.get_report_artifact(a.id)
    assert a2.delivery_status == "delivered" and a2.delivered_at is not None


def test_genuine_run20_body_persists_with_stable_hash():
    """Real-corpus check: the owner-graded run #20 body persists, validates, and its stored hash
    equals an independent hash of the fixture bytes — the U3a acceptance shape."""
    body = (pathlib.Path(__file__).parent / "fixtures" / "weekly_report_run20.md").read_text(
        encoding="utf-8")
    ok, reason = validate_report_artifact(body)
    assert ok, reason
    s = _store()
    aid = _persist(s, body=body)
    a = s.get_report_artifact(aid)
    assert a.content_sha256 == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert a.body == body


def test_one_artifact_many_delivery_attempts(monkeypatch):
    """The review's approval condition: a failed Monday delivery is retried Tuesday against the
    SAME artifact — no regeneration, no duplicate rows, attempts counted on the one row."""
    import tc_growth.store as store_mod
    from tc_growth.cli import cmd_report_redeliver

    shared = SqliteStore(":memory:")
    monkeypatch.setattr(store_mod, "open_store", lambda: shared)
    aid = _persist(shared)

    # Monday: SMTP down.
    monkeypatch.setattr("tc_growth.report.send_email", lambda *a, **k: False)
    assert cmd_report_redeliver(str(aid)) == 1
    a = shared.get_report_artifact(aid)
    assert a.delivery_status == "send_failed" and a.delivery_attempts == 1

    # Tuesday: SMTP back.
    monkeypatch.setattr("tc_growth.report.send_email", lambda *a, **k: True)
    assert cmd_report_redeliver(str(aid)) == 0
    a = shared.get_report_artifact(aid)
    assert a.delivery_status == "delivered" and a.delivery_attempts == 2
    assert a.body == BODY                                      # same immutable artifact
    assert len(shared.list_report_artifacts()) == 1            # exactly one row, ever


def test_identical_twin_artifacts_redeliver_binds_to_the_requested_row(monkeypatch):
    """Review condition 3 (2026-08-03): two artifacts with the SAME body/hash exist; redelivering
    the OLDER must update only the older. Hash-only lookup would mark the newest — the exact
    ambiguity the id-binding fix removes."""
    import tc_growth.store as store_mod
    from tc_growth.cli import cmd_report_redeliver

    shared = SqliteStore(":memory:")
    monkeypatch.setattr(store_mod, "open_store", lambda: shared)
    monkeypatch.setattr("tc_growth.report.send_email", lambda *a, **k: True)

    older = _persist(shared, body=BODY)
    newer = _persist(shared, body=BODY)                 # byte-identical twin, same sha256
    assert (shared.get_report_artifact(older).content_sha256
            == shared.get_report_artifact(newer).content_sha256)

    assert cmd_report_redeliver(str(older)) == 0
    assert shared.get_report_artifact(older).delivery_status == "delivered"
    assert shared.get_report_artifact(older).delivery_attempts == 1
    assert shared.get_report_artifact(newer).delivery_status == "pending"   # twin untouched
    assert shared.get_report_artifact(newer).delivery_attempts == 0


def test_weekly_path_carries_artifact_id_past_a_newer_twin(monkeypatch):
    """The normal Monday path binds by id too: the body returned by build carries its artifact
    id (ArtifactBody), so even if a NEWER identical-hash row appears before delivery, deliver()
    marks the row build created — not the newest match."""
    import tc_growth.store as store_mod
    from tc_growth.report import build_weekly_report, deliver

    shared = SqliteStore(":memory:")

    class _NoClose:
        def __getattr__(self, name):
            return (lambda: None) if name == "close" else getattr(shared, name)

    monkeypatch.setattr(store_mod, "open_store", lambda: _NoClose())
    monkeypatch.setattr("tc_growth.report.send_email", lambda *a, **k: True)

    body = build_weekly_report(_FakeRuntime(text=BODY), persist=True)
    built_id = getattr(body, "artifact_id", None)
    assert built_id is not None

    interloper = _persist(shared, body=str(body))       # newer identical-hash row
    deliver(body, ok=True)
    assert shared.get_report_artifact(built_id).delivery_status == "delivered"
    assert shared.get_report_artifact(interloper).delivery_status == "pending"


def test_id_hash_mismatch_marks_nothing(monkeypatch):
    """Fail closed: an artifact_id whose stored hash does not match the bytes being sent must
    record NOTHING (identity and integrity must agree before the chain closes)."""
    import tc_growth.store as store_mod
    from tc_growth.report import deliver

    shared = SqliteStore(":memory:")
    monkeypatch.setattr(store_mod, "open_store", lambda: shared)
    monkeypatch.setattr("tc_growth.report.send_email", lambda *a, **k: True)

    aid = _persist(shared, body=BODY)
    deliver(BODY + "tampered", ok=True, artifact_id=aid)
    a = shared.get_report_artifact(aid)
    assert a.delivery_status == "pending" and a.delivery_attempts == 0
