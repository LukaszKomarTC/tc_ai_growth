"""WP-U5.3a — Backup Guardian policy and the coverage collector.

Issue #82 §8 asks a harder question than a backup dashboard answers:

    Backup Guardian must answer "How confident are we that we can recover?", not merely
    "Did some backup process run?"

The tests below are organised around the ways that question gets answered dishonestly. Every one
of them is a way a real monitoring system has reassured a real business shortly before it lost
its data:

* a config file saying backups run, mistaken for backups running;
* somebody's recollection of a successful restore, mistaken for a restore test;
* four components averaged into one green tick, hiding the one that failed;
* an archive counted as coverage that must never be restored;
* a source nobody can reach, rendered as zero problems rather than zero knowledge.

U5.3a adds no credential and no privilege (issue #82 §12, §13), so on this host every layer is
unobservable. The tests therefore also pin the *shape* of that honesty: each gap names the exact
missing dependency, because "unknown" without a named dependency is not an answer anyone can act
on.
"""

from __future__ import annotations

import json

import pytest

from tc_growth import backup_policy as bp
from tc_growth import inspection, store as store_mod
from tc_growth.collectors import default_collectors
from tc_growth.collectors.backup_coverage import BackupCoverageCollector, judge


@pytest.fixture()
def store():
    s = store_mod.open_store(":memory:")
    try:
        yield s
    finally:
        s.close()


def ctx(profile="tossa-cycling", environment="production"):
    return inspection.CollectionContext(profile=profile, environment=environment,
                                        repo_commit="deadbeef")


def layer(**kw):
    base = dict(key=bp.LAYER_APPLICATION, title="Application backup",
                protects="restores the site", missing_dependency="nothing can read it")
    base.update(kw)
    return bp.BackupLayer(**base)


def policy(*layers, tainted=()):
    return bp.BackupPolicy(profile="tossa-cycling", layers=tuple(layers), tainted=tainted)


# === provenance decides the verdict ===============================================================

def test_only_an_observed_layer_can_be_healthy():
    """The rule the whole module exists to enforce: a declaration cannot promote itself."""
    observed = layer(observed_via="read the package directory", missing_dependency="",
                     state=bp.PolicyValue("current", bp.OBSERVED))
    assert judge(observed)[0] == inspection.STATUS_OK

    for provenance, extra in ((bp.OWNER_ATTESTED, {"as_of": "2026-08-08"}),
                              (bp.PROPOSED, {})):
        declared = layer(state=bp.PolicyValue("current", provenance, **extra))
        assert judge(declared)[0] == inspection.STATUS_UNKNOWN, provenance


def test_an_owner_statement_is_recorded_credited_and_dated_but_never_green():
    """Not scepticism about the owner — R3 records a Duplicator chain that IS configured and HAS
    been tested, which is more than most small businesses manage.

    It is that a monitoring system whose green light can be produced by somebody's recollection
    will be green on the day it matters. The statement is kept, attributed and dated; what it
    cannot do is stand in for a reading.
    """
    attested = layer(state=bp.PolicyValue("configured and tested", bp.OWNER_ATTESTED,
                                          as_of="2026-08-08"))
    status, reason = judge(attested)

    assert status == inspection.STATUS_UNKNOWN
    assert "according to the owner" in reason
    assert "2026-08-08" in reason
    assert "nothing can read it" in reason          # the missing dependency, named


def test_an_undated_owner_statement_is_refused_outright():
    """An attestation with no date never ages, and a claim that never ages is one nobody
    revisits — it would still be reassuring in five years."""
    with pytest.raises(ValueError, match="date"):
        bp.PolicyValue("configured", bp.OWNER_ATTESTED)


def test_a_proposed_default_says_it_is_a_guess():
    proposed = layer(state=bp.PolicyValue("weekly", bp.PROPOSED))
    status, reason = judge(proposed)
    assert status == inspection.STATUS_UNKNOWN
    assert "proposed" in reason and "confirmed" in reason


# === absence, acknowledged and not ================================================================

def test_an_unacknowledged_absence_is_action():
    missing = layer(state=bp.PolicyValue("not configured", bp.ABSENT))
    status, reason = judge(missing)
    assert status == inspection.STATUS_ACTION
    assert "not recorded as accepted" in reason


def test_an_acknowledged_gap_warns_instead_of_shouting():
    """§7 forbids alert fatigue. A gap the owner has already decided about, screaming `action`
    every sweep, trains them to ignore the page — which is how the NEXT gap gets missed."""
    known = layer(state=bp.PolicyValue("not configured", bp.ABSENT),
                  acknowledged=True,
                  acknowledged_reason="deliberately deferred",
                  tracked_as="issue #82 — R3")
    status, reason = judge(known)

    assert status == inspection.STATUS_WARN
    assert "known gap" in reason
    assert "issue #82 — R3" in reason


def test_an_acknowledgement_without_a_reason_or_a_tracker_is_refused():
    """Otherwise `acknowledged=True` is a mute button rather than a decision."""
    with pytest.raises(ValueError, match="silenced alarm"):
        layer(state=bp.PolicyValue("not configured", bp.ABSENT), acknowledged=True)
    with pytest.raises(ValueError, match="silenced alarm"):
        layer(state=bp.PolicyValue("not configured", bp.ABSENT), acknowledged=True,
              acknowledged_reason="because")


def test_an_unobservable_layer_must_name_what_is_missing():
    """"Unknown" with no named dependency is not an answer the owner can act on."""
    with pytest.raises(ValueError, match="not an answer"):
        bp.BackupLayer(key=bp.LAYER_HOST, title="Whole-server backup", protects="everything")


# === the policy cannot claim more than the code can back ==========================================

def test_a_policy_claiming_observation_without_a_source_is_refused():
    """Modelled on `core.actions.validate_registry`. The "only observed is healthy" rule lives in
    `judge()`, and a rule that lives only in the function applying it can be undone by editing the
    data that function reads. So a layer claiming OBSERVED must also say HOW."""
    with pytest.raises(ValueError, match="cannot promote itself"):
        bp.validate_policy(policy(layer(state=bp.PolicyValue("current", bp.OBSERVED))))


def test_a_policy_missing_a_layer_is_refused():
    """§8.3 requires the components to be distinguished; a layer omitted from the policy is one
    nobody will notice is missing."""
    with pytest.raises(ValueError, match="does not cover"):
        bp.validate_policy(policy(layer(state=bp.PolicyValue("x", bp.PROPOSED))))


def test_the_shipped_policy_is_valid_and_covers_every_layer():
    bp.validate_policy(bp.DEFAULT_POLICY)
    assert {entry.key for entry in bp.DEFAULT_POLICY.layers} == set(bp.LAYERS)


def test_nothing_in_the_shipped_policy_claims_to_have_been_observed():
    """U5.3a adds no credential and no privilege, so the honest state of every layer is that the
    platform has not seen it. If this test ever fails, either a real source was wired up — in
    which case it belongs in a reviewed increment with its own tests — or a layer was quietly
    promoted."""
    assert bp.DEFAULT_POLICY.unverified == bp.DEFAULT_POLICY.layers


# === the four layers are never averaged ===========================================================

def test_a_fresh_backup_does_not_imply_a_tested_restore():
    """§18's Backup Guardian requirement, and the failure mode that ruins companies: every
    archive present and current, and nobody has ever restored one."""
    perfect_backups = policy(
        layer(key=bp.LAYER_APPLICATION, title="Application backup", protects="site",
              observed_via="package directory", missing_dependency="",
              state=bp.PolicyValue("current", bp.OBSERVED)),
        layer(key=bp.LAYER_OFFSITE, title="Off-site copy", protects="server loss",
              observed_via="drive listing", missing_dependency="",
              state=bp.PolicyValue("current", bp.OBSERVED)),
        layer(key=bp.LAYER_HOST, title="Whole-server backup", protects="the box",
              observed_via="dump store", missing_dependency="",
              state=bp.PolicyValue("current", bp.OBSERVED)),
        layer(key=bp.LAYER_RESTORE_TEST, title="Restore test", protects="proves the rest",
              state=bp.PolicyValue("no recorded evidence", bp.ABSENT)),
    )
    result = BackupCoverageCollector(the_policy=perfect_backups).collect(ctx())

    assert result.status == inspection.STATUS_ACTION
    assert "restore test" in result.reason.lower()
    # And the healthy layers are still individually visible — not erased by the failing one.
    assert result.value["layers"][bp.LAYER_APPLICATION]["status"] == inspection.STATUS_OK


def test_a_stale_offsite_copy_is_visible_even_when_local_is_fresh():
    """§18: stale off-site produces its state even when local is fresh. Averaging would hide the
    layer whose whole job is surviving the loss of the machine."""
    mixed = policy(
        layer(key=bp.LAYER_APPLICATION, title="Application backup", protects="site",
              observed_via="package directory", missing_dependency="",
              state=bp.PolicyValue("current", bp.OBSERVED)),
        layer(key=bp.LAYER_OFFSITE, title="Off-site copy", protects="server loss",
              state=bp.PolicyValue("not configured", bp.ABSENT)),
        layer(key=bp.LAYER_HOST, title="Whole-server backup", protects="the box",
              observed_via="dump store", missing_dependency="",
              state=bp.PolicyValue("current", bp.OBSERVED)),
        layer(key=bp.LAYER_RESTORE_TEST, title="Restore test", protects="proves the rest",
              observed_via="restore log", missing_dependency="",
              state=bp.PolicyValue("current", bp.OBSERVED)),
    )
    result = BackupCoverageCollector(the_policy=mixed).collect(ctx())

    assert result.status == inspection.STATUS_ACTION
    assert result.value["layers"][bp.LAYER_OFFSITE]["status"] == inspection.STATUS_ACTION
    assert "off-site" in result.reason.lower()


def test_a_missing_source_reports_unknown_rather_than_zero_backups():
    """§18 again, and §14: an unreachable source is not evidence of absence. "Zero backups found"
    and "we could not look" are opposite claims."""
    result = BackupCoverageCollector().collect(ctx())

    assert result.status == inspection.STATUS_UNKNOWN
    assert result.value["sources_reached"] == []
    assert "cannot currently see" in result.reason
    for entry in result.value["layers"].values():
        assert entry["missing_dependency"], entry["title"]


# === the archive that must never be restored ======================================================

def test_the_never_restore_archive_is_named_in_the_headline():
    """Recoverability is not a count of archives.

    `docs/STANDING-CAUTIONS.md` records a ~19 GB backup from the tobacco-spam compromise whose
    restoration would reintroduce it. The moment that matters is an incident — when somebody
    frightened is reaching for the biggest recent-looking archive on the box, and nobody is
    reading a markdown file. So it goes in the sentence, not behind a fold.
    """
    result = BackupCoverageCollector().collect(ctx())

    assert "DO NOT RESTORE" in result.reason
    recorded = result.value["do_not_restore"]
    assert len(recorded) == 1
    assert "19 GB" in recorded[0]["label"]
    assert "reintroduce the compromise" in recorded[0]["why"]
    assert recorded[0]["recorded_in"] == "docs/STANDING-CAUTIONS.md"


def test_a_never_restore_archive_appearing_is_a_material_change(store):
    """Adding or removing one changes what recovery is actually available, so it belongs in the
    comparison rather than only in the prose."""
    clean = policy(*bp.DEFAULT_POLICY.layers)
    with_tainted = policy(*bp.DEFAULT_POLICY.layers, tainted=bp.DEFAULT_POLICY.tainted)

    inspection.run_inspection(store, [BackupCoverageCollector(the_policy=clean)], ctx())
    run = inspection.run_inspection(
        store, [BackupCoverageCollector(the_policy=with_tainted)], ctx())

    assert store.list_observations(run)[0]["change_class"] == inspection.CHANGE_CHANGED


# === forecasting degrades honestly ================================================================

def test_no_forecast_is_invented_from_nothing():
    """§9: forecasting must degrade honestly. There is no size or retention series here at all,
    and "days remaining" from no samples is the fabrication that section forbids."""
    value = BackupCoverageCollector().collect(ctx()).value
    assert "not attempted" in value["forecast"]
    assert "no backup source is observable" in value["forecast"]


# === boundary =====================================================================================

def test_the_collector_uses_no_credential_and_no_command():
    """U5.3a adds no Plesk credential, no Drive credential and no new privilege. It reads a file
    in this repository and nothing else."""
    import inspect as _inspect

    from tc_growth.collectors import backup_coverage

    source = _inspect.getsource(backup_coverage)
    for forbidden in ("run_command", "subprocess", "requests", "urllib", "socket", "sudo"):
        assert forbidden not in source, forbidden

    result = BackupCoverageCollector().collect(ctx())
    assert result.value["external_access"].startswith("none")


def test_the_reading_is_comparable_because_the_policy_was_read():
    """The distinction U5.2d drew, applied here: the platform genuinely established the state of
    every layer — what it did NOT establish is what those layers describe. A reviewed policy edit
    must therefore be visible on the page, not swallowed because the health reads `unknown`."""
    result = BackupCoverageCollector().collect(ctx())
    assert result.comparable is True
    assert result.status == inspection.STATUS_UNKNOWN


def test_a_policy_edit_shows_up_as_a_change(store):
    before = policy(*bp.DEFAULT_POLICY.layers)
    after = bp.BackupPolicy(
        profile="tossa-cycling", layers=bp.DEFAULT_POLICY.layers, version="u5.3a/2")

    inspection.run_inspection(store, [BackupCoverageCollector(the_policy=before)], ctx())
    run = inspection.run_inspection(store, [BackupCoverageCollector(the_policy=after)], ctx())

    assert store.list_observations(run)[0]["change_class"] == inspection.CHANGE_CHANGED


def test_an_unchanged_policy_is_quiet(store):
    inspection.run_inspection(store, [BackupCoverageCollector()], ctx())
    run = inspection.run_inspection(store, [BackupCoverageCollector()], ctx())

    row = store.list_observations(run)[0]
    assert row["change_class"] == inspection.CHANGE_UNCHANGED
    assert row["severity"] == inspection.STATUS_UNKNOWN     # quiet, but never green


def test_the_collector_is_in_the_default_sweep():
    assert "backup.coverage" in [c.id for c in default_collectors()]


def test_the_owner_facing_value_carries_no_path_credential_or_command(store):
    """§8.2: never expose backup credentials or sensitive archive contents. There is nothing
    sensitive to expose here yet — this test is what keeps it that way as sources are added."""
    run = inspection.run_inspection(store, [BackupCoverageCollector()], ctx())
    stored = store.list_observations(run)[0]["value_json"]

    for forbidden in ("password", "token", "secret", "api_key", "client_id", "refresh_token"):
        assert forbidden not in stored.lower(), forbidden
    # Nothing needed redacting, because nothing sensitive is collected. Worth pinning: the first
    # draft named a field `credentials_used` and the boundary masked its value — correctly, since
    # the rule keys on the NAME and cannot afford to judge whether a given field is really a
    # secret. The field was renamed rather than the rule loosened.
    assert "***redacted***" not in stored


def test_every_layer_explains_why_the_owner_should_care():
    """§20: if the page mainly displays infrastructure jargon, U5 has failed product acceptance
    even when the backend is correct. Each layer must answer "why do I care?" in a sentence."""
    for entry in BackupCoverageCollector().collect(ctx()).value["layers"].values():
        assert len(entry["protects"]) > 40, entry["title"]
        assert entry["title"][0].isupper()
        assert "_" not in entry["title"]
