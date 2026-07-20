"""WP-06 Site Intelligence slice 2: snapshot assembly, drift detection, store round-trip.

The three-state discipline under test: snapshots are OBSERVED state; SITE_PROFILE.md is
APPROVED knowledge (no code path here touches it — asserted below); the snapshot-to-snapshot
diff is UNEXPLAINED drift until a report or human accounts for it.
"""

from __future__ import annotations

import json
import pathlib

from tc_growth.core.approval import Phase, is_tool_allowed, needs_confirmation
from tc_growth.core.site_intel import build_snapshot, diff_snapshots, query_snapshot
from tc_growth.store.sqlite import SqliteStore
from tc_growth.tools.load import load_all


def _item(id_, slug, title, type_="page", parent=0, template=""):
    return {"id": id_, "slug": slug, "title": title, "type": type_, "parent": parent,
            "template": template, "url": f"https://x/{slug}/"}


def _snap(items, menus=None, post_types=None):
    return {
        "items": {str(i["id"]): i for i in items},
        "menus": menus or [],
        "post_types": post_types or [],
    }


def test_build_snapshot_drains_all_pages_and_keeps_menus_from_page_one():
    pages = {
        1: {"items": [_item(1, "home", "[:es]Inicio[:en]Home[:]")], "total_pages": 2,
            "total": 2, "menus": [{"name": "Main", "items": []}], "post_types": [{"type": "page", "published": 2}]},
        2: {"items": [_item(2, "tours", "Tours")], "total_pages": 2, "total": 2,
            "menus": [], "post_types": []},
    }
    snap = build_snapshot(lambda p: pages[p])
    assert set(snap["items"]) == {"1", "2"}
    assert snap["menus"][0]["name"] == "Main"
    assert snap["items"]["1"]["title"] == "[:es]Inicio[:en]Home[:]"  # raw, tags intact


def test_build_snapshot_refuses_silent_truncation():
    big = {"items": [], "total_pages": 99, "total": 0, "menus": [], "post_types": []}
    try:
        build_snapshot(lambda p: big, max_pages=5)
    except ValueError as exc:
        assert "max_pages" in str(exc)
    else:
        raise AssertionError("oversized site must raise, never snapshot partially")


def test_first_snapshot_is_baseline_not_drift():
    d = diff_snapshots(None, _snap([_item(1, "home", "Home")]))
    assert d["baseline"] is True and "added" not in d


def test_diff_detects_added_removed_changed_and_menu_drift():
    old = _snap(
        [_item(1, "home", "Home"), _item(2, "tours", "Tours")],
        menus=[{"name": "Main", "items": [{"title": "Tours", "url": "/tours/"}]}],
        post_types=[{"type": "page", "published": 2}],
    )
    new = _snap(
        [_item(1, "home", "Home v2"), _item(3, "rental", "Rental")],
        menus=[{"name": "Main", "items": [{"title": "Rental", "url": "/rental/"}]}],
        post_types=[{"type": "page", "published": 2}],
    )
    d = diff_snapshots(old, new)
    assert d["has_drift"] is True
    assert [i["id"] for i in d["added"]] == [3]
    assert [i["id"] for i in d["removed"]] == [2]
    assert d["changed"][0]["id"] == 1 and d["changed"][0]["changes"]["title"]["after"] == "Home v2"
    assert d["menus_changed"] is True


def test_identical_snapshots_report_no_drift():
    s = _snap([_item(1, "home", "Home")], menus=[{"name": "M", "items": []}],
              post_types=[{"type": "page", "published": 1}])
    d = diff_snapshots(s, json.loads(json.dumps(s)))
    assert d["has_drift"] is False and d["baseline"] is False


def test_query_snapshot_slug_type_and_text():
    s = _snap([_item(1, "home", "[:es]Inicio[:en]Home[:]"),
               _item(2, "scott-addict", "Scott Addict 50", type_="product")])
    assert query_snapshot(s, slug="scott-addict")[0]["id"] == 2
    assert [i["id"] for i in query_snapshot(s, post_type="product")] == [2]
    assert query_snapshot(s, text="inicio")[0]["id"] == 1  # matches inside raw tagged title


def test_store_round_trip_and_listing_stays_light(tmp_path):
    store = SqliteStore(tmp_path / "t.db")
    payload = json.dumps(_snap([_item(1, "home", "Home")]))
    sid = store.save_snapshot(payload=payload, item_count=1, drift=json.dumps({"baseline": True}))
    row = store.latest_snapshot()
    assert row is not None and row.id == sid and json.loads(row.payload)["items"]["1"]["slug"] == "home"
    listing = store.list_snapshots()
    assert listing[0].item_count == 1
    assert int(listing[0].payload) == len(payload)  # listings carry payload LENGTH, not payload
    store.close()


def test_tools_registered_read_only_and_unconfirmed():
    names = {t.name for t in load_all().all()}
    assert {"site_snapshot_refresh", "site_map_query"} <= names
    for name in ("site_snapshot_refresh", "site_map_query"):
        assert is_tool_allowed(name, Phase.READ_ONLY)
        assert not needs_confirmation(name)


def test_site_intel_modules_have_no_filesystem_write_capability():
    """SITE_PROFILE.md is the human-approved baseline and snapshots must never rewrite it.
    Structural tripwire: the site_intel modules perform NO file I/O at all — observations go
    to the store (SQLite via open_store), documentation stays documentation."""
    root = pathlib.Path(__file__).resolve().parents[1] / "tc_growth"
    banned = ("open(", "write_text", "write_bytes", "Path(", "os.remove", "shutil.")
    for rel in ("core/site_intel.py", "tools/site_intel.py"):
        text = (root / rel).read_text(encoding="utf-8")
        offenders = [tok for tok in banned if tok in text]
        assert not offenders, f"{rel} must not touch the filesystem: {offenders}"


# --- Slice 4: digest formatting + task injection ------------------------------------------

def test_digest_baseline_and_no_drift_render_compactly():
    from tc_growth.core.site_intel import format_digest
    s = _snap([_item(1, "home", "Home")], menus=[{"name": "Main", "items": [1, 2]}],
              post_types=[{"type": "page", "published": 1}])
    d = format_digest("2026-07-20T07:00:00+00:00", s, {"baseline": True})
    assert "baseline established" in d and "site_map_query" in d and "page (1)" in d
    d2 = format_digest("t", s, {"baseline": False, "has_drift": False})
    assert "none since the previous snapshot" in d2


def test_digest_caps_drift_lists_and_labels_them_unexplained():
    from tc_growth.core.site_intel import format_digest
    s = _snap([_item(1, "home", "Home")])
    drift = {
        "baseline": False, "has_drift": True,
        "added": [_item(100 + n, f"new-{n}", "x") for n in range(12)],
        "removed": [], "changed": [], "menus_changed": True, "type_changes": {},
    }
    d = format_digest("t", s, drift, max_items=10)
    assert "OBSERVED CHANGES" in d and "NOT approved-baseline drift" in d and "+2 more" in d
    assert "menus changed" in d  # hub moves are called out


def test_site_intel_block_states_are_always_distinguishable(tmp_path):
    """Reviewer correction: absence of evidence must be explicit, never an empty string.
    Three deterministic states: unavailable (no snapshot), failed (broken read), present."""
    from tc_growth.memory import site_intel_block
    store = SqliteStore(tmp_path / "s.db")
    missing = site_intel_block(store)
    assert "SITE INTELLIGENCE: unavailable" in missing
    assert "Do not make claims" in missing  # structural claims prohibited, stated in-band

    store.save_snapshot(payload=json.dumps(_snap([_item(1, "home", "Home")])), item_count=1,
                        drift=json.dumps({"baseline": True}))
    block = site_intel_block(store)
    assert block.startswith("## SITE INTELLIGENCE") and "baseline established" in block
    store.close()

    class _Broken:
        def latest_snapshot(self):
            raise RuntimeError("disk on fire")
    failed = site_intel_block(_Broken())
    assert "SITE INTELLIGENCE: failed to load" in failed and "prohibited" in failed


# --- Reviewer hardening round (2026-07-20) ------------------------------------------------

def test_crawl_rejects_midcrawl_mutation_and_duplicates():
    from tc_growth.core.site_intel import build_snapshot
    total_changed = {
        1: {"items": [_item(1, "a", "A")], "total_pages": 2, "total": 3, "menus": [], "post_types": []},
        2: {"items": [_item(2, "b", "B")], "total_pages": 2, "total": 4, "menus": [], "post_types": []},
    }
    try:
        build_snapshot(lambda p: total_changed[p])
    except ValueError as exc:
        assert "changed during crawl" in str(exc)
    else:
        raise AssertionError("total drift mid-crawl must reject the snapshot")

    duplicated = {
        1: {"items": [_item(1, "a", "A"), _item(2, "b", "B")], "total_pages": 2, "total": 3,
            "menus": [], "post_types": []},
        2: {"items": [_item(2, "b", "B")], "total_pages": 2, "total": 3, "menus": [], "post_types": []},
    }
    try:
        build_snapshot(lambda p: duplicated[p])
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("offset-shift duplication must reject the snapshot")


def test_expectation_violation_surfaces_even_at_baseline():
    """The reviewer's key example: a defect present at the FIRST snapshot (hub missing from every
    menu) can never appear as change — approved expectations catch it anyway."""
    from tc_growth.core.site_intel import check_expectations, format_digest
    snap = _snap([_item(1, "home", "Home")],
                 menus=[{"name": "Main", "items": [{"title": "Home", "url": "/"}]}])
    violations = check_expectations(snap)
    kinds = {v["violation"] for v in violations}
    assert any("tour_de_girona-listado" in k for k in kinds)  # hub page + menu both flagged
    for v in violations:
        assert v.get("source") and v.get("why")  # provenance rides along
    d = format_digest("t", snap, {"baseline": True, "expectation_violations": violations})
    assert "APPROVED-EXPECTATION VIOLATIONS" in d and "pre-existing defects surface too" in d


def test_expectations_satisfied_produce_no_violations():
    from tc_growth.core.site_intel import check_expectations
    snap = _snap(
        [_item(1, "tour_de_girona-listado", "TdG"), _item(2, "alquiler_bicicletas", "Alquiler")],
        menus=[{"name": "Main", "items": [{"title": "TdG", "url": "https://x/tour_de_girona-listado/"}]}],
    )
    assert check_expectations(snap) == []


def test_parsed_titles_ride_alongside_raw():
    from tc_growth.core.site_intel import build_snapshot
    pages = {1: {"items": [_item(1, "home", "[:es]Inicio[:en]Home[:]")], "total_pages": 1,
                 "total": 1, "menus": [], "post_types": []}}
    snap = build_snapshot(lambda p: pages[p])
    item = snap["items"]["1"]
    assert item["title"] == "[:es]Inicio[:en]Home[:]"  # raw truth intact
    assert item["title_es"] == "Inicio" and item["title_en"] == "Home"


def test_snapshot_retention_prunes_and_history_is_insert_only(tmp_path):
    store = SqliteStore(tmp_path / "r.db")
    ids = [store.save_snapshot(payload="{}", item_count=0, keep=2) for _ in range(4)]
    listing = store.list_snapshots()
    assert [s.id for s in listing] == [ids[3], ids[2]]  # oldest pruned, newest kept
    assert len({*ids}) == 4  # every save was a NEW row — history is insert-only
    store.close()


def test_undated_page_is_likely_evergreen_low_confidence():
    import datetime as dt
    from tc_growth.core.lifecycle import classify_lifecycle
    v = classify_lifecycle({"id": 1, "slug": "servicios", "type": "page", "title": "", "url": ""},
                           today=dt.date(2026, 7, 20))
    assert v["state"] == "likely_evergreen" and v["confidence"] == "low" and v["tier"] == "inference"


# --- Reviewer round 2: integration wiring + provenance uniqueness -------------------------

def test_rule_and_expectation_identities_are_unique():
    """Two rules matching the same target or two expectations checking the same fact would
    create silent precedence surprises — identities must be unique."""
    from tc_growth.core.lifecycle import APPROVED_RULES
    from tc_growth.core.site_intel import EXPECTED_STRUCTURE
    rule_ids = [(r.get("slug"), r.get("type")) for r in APPROVED_RULES]
    assert len(rule_ids) == len(set(rule_ids))
    exp_ids = [(e["kind"], e["value"]) for e in EXPECTED_STRUCTURE]
    assert len(exp_ids) == len(set(exp_ids))
    for e in EXPECTED_STRUCTURE:  # expectations carry full provenance like rules do
        assert e.get("source") and e.get("approved") and e.get("scope") and e.get("why")


def test_report_task_wiring_carries_digest_with_snapshot_identity(tmp_path, monkeypatch):
    """Integration fixture (reviewer): prove the PROMPT ASSEMBLY is wired — the task handed to
    the runtime contains the digest, the snapshot identity for traceability, and the violation
    with its basis. (Whether the MODEL then obeys is the live acceptance run's job.)"""
    import tc_growth.store as store_pkg
    from tc_growth.memory import site_intel_block

    store = SqliteStore(tmp_path / "w.db")
    snap = _snap([_item(1, "home", "Home")])  # hub missing -> violations exist
    from tc_growth.core.site_intel import check_expectations
    drift = {"baseline": True, "expectation_violations": check_expectations(snap)}
    store.save_snapshot(payload=json.dumps(snap), item_count=1, drift=json.dumps(drift))

    block = site_intel_block(store)
    store.close()
    assert "id 1 ·" in block                       # snapshot identity -> traceable claims
    assert "APPROVED-EXPECTATION VIOLATIONS" in block
    assert "tour_de_girona-listado" in block       # the violated expectation, with...
    assert "source:" in block                      # ...its approved provenance cited
    assert "site_map_query" in block               # pointer to detail


def test_conflicting_lifecycle_survives_through_the_tool_path(tmp_path, monkeypatch):
    """End-to-end through store + JSON + tool: a year-only slug stays 'unknown' when queried
    with classify=true — uncertainty is preserved by the plumbing, not just the classifier."""
    import tc_growth.tools.site_intel as si_tools

    store = SqliteStore(tmp_path / "c.db")
    snap = _snap([_item(7, "tour-de-girona-2026-road-s1", "TdG 2026", type_="events")])
    store.save_snapshot(payload=json.dumps(snap), item_count=1, drift=None)
    monkeypatch.setattr(si_tools, "open_store", lambda: store)
    try:
        out = si_tools._query({"slug": "tour-de-girona-2026-road-s1", "classify": True})
    finally:
        store.close()
    life = out["matches"][0]["lifecycle"]
    assert life["state"] == "unknown" and life["confidence"] == "low" and life["basis"]
