"""WP-U5.2b — one canonical runtime identity, stated by the runtime rather than remembered.

The U5.2 acceptance pre-flight found two apparently-current Console service identities in the
repository — `tc-console.service` (the U4 governed execution surface) and `tc-dashboard.service`
(the older read-only dashboard on another port) — and no way to tell from the browser which one
you had reached or whether `TC_SITE_DOCROOT` was configured at all. An owner served by the wrong
one would have been shown `platform.services: tc-console.service missing` and an `unknown`
journal while everything was in fact working, and the acceptance run would have produced findings
about deployment naming drift rather than about the Technical Inspector.

The review's instruction was not to hand the owner a `systemctl` command:

    Fix the deployment identity once; do not make the owner carry this inconsistency in Bash.

So these tests hold two properties: the unit name has exactly one author in the codebase, and the
runtime tells the truth about itself — including when the truth is a mismatch.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from tc_growth import runtime_identity as ri
from tc_growth.collectors import _exec
from tc_growth.collectors.logs_signatures import UNIT as LOGS_UNIT
from tc_growth.collectors.platform_services import UNITS, UNIT_POLICY
from tc_growth.collectors.wp_inventory import DOCROOT_ENV

REPO = Path(__file__).resolve().parents[2]


# --- one author for the contract ------------------------------------------------------------

def test_every_consumer_of_the_console_unit_name_imports_it():
    """Nothing spells the unit; everything imports it. Two independent spellings is exactly how
    the deployment acquired two service identities in the first place."""
    assert _exec.ALLOWED_UNITS == frozenset(ri.PROJECT_UNITS)
    assert UNITS == ri.PROJECT_UNITS
    assert LOGS_UNIT == ri.CONSOLE_UNIT
    assert DOCROOT_ENV == ri.DOCROOT_ENV
    assert set(UNIT_POLICY) == set(ri.PROJECT_UNITS)


def test_no_module_hardcodes_a_console_unit_name_beside_the_contract():
    """A grep is the right test here: the defect being prevented is a SECOND place naming the
    unit, and that is a property of the source text, not of any runtime value."""
    offenders = []
    for path in (REPO / "orchestrator" / "tc_growth").rglob("*.py"):
        if path.name == "runtime_identity.py" or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if re.search(r"[\"']tc-(console|dashboard)\.service[\"']", line):
                offenders.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    assert not offenders, "unit names must come from runtime_identity:\n" + "\n".join(offenders)


def test_the_legacy_dashboard_is_named_but_never_inspected():
    """Recorded so 'is it still installed?' has an answer in code — and kept out of the inspected
    set, because widening the boundary to keep a retired surface green is capability creep."""
    assert ri.LEGACY_DASHBOARD_UNIT == "tc-dashboard.service"
    assert ri.LEGACY_DASHBOARD_UNIT not in ri.PROJECT_UNITS
    assert ri.LEGACY_DASHBOARD_UNIT not in _exec.ALLOWED_UNITS


def test_the_legacy_unit_file_states_its_retirement_criteria():
    """Item 3 of the review: if both units temporarily coexist, the transition and the
    retirement criteria must be written down, not left to memory."""
    unit = (REPO / "orchestrator" / "deployments" / "systemd" / "tc-dashboard.service"
            ).read_text(encoding="utf-8")
    assert "TRANSITIONAL" in unit
    assert "tc-console.service" in unit
    assert "Retirement criteria" in unit


def test_widening_the_boundary_to_the_legacy_unit_is_still_refused():
    """The mismatch must not be solvable by loosening the command boundary."""
    assert not _exec.is_allowed(_exec.systemctl_show("tc-dashboard.service"))
    assert not _exec.is_allowed(_exec.journalctl_probe("tc-dashboard.service"))


# --- the runtime describes itself -------------------------------------------------------------

def test_the_unit_is_read_from_the_process_not_configured(tmp_path):
    """Derived, never declared. A constant saying 'we are tc-console.service' would keep saying
    so from a unit called something else, which is the failure this module exists to expose."""
    cgroup = tmp_path / "cgroup"
    cgroup.write_text("0::/system.slice/tc-console.service\n")
    assert ri.unit_of_this_process(cgroup_path=str(cgroup)) == "tc-console.service"


def test_a_nested_cgroup_resolves_to_the_leaf_unit(tmp_path):
    cgroup = tmp_path / "cgroup"
    cgroup.write_text("0::/user.slice/user-1000.slice/session-3.scope\n")
    assert ri.unit_of_this_process(cgroup_path=str(cgroup)) == "session-3.scope"


def test_an_unreadable_cgroup_is_none_rather_than_a_guess(tmp_path):
    assert ri.unit_of_this_process(cgroup_path=str(tmp_path / "absent")) is None


def test_an_unknown_unit_is_not_reported_as_a_mismatch(monkeypatch, tmp_path):
    """None means 'we cannot establish it' — a CLI run, a test, a container without systemd.
    Calling that a MISMATCH would be a claim we cannot make either, so the panel does not."""
    monkeypatch.setenv(ri.DOCROOT_ENV, str(tmp_path))
    identity = ri.describe(unit_reader=lambda: None)
    assert identity.unit is None
    assert identity.unit_matches
    assert not any("running under tc-" in p for p in identity.problems)


def test_an_unestablished_unit_is_not_acceptance_ready(monkeypatch, tmp_path):
    """The distinction `unit_matches` was quietly doing double duty over.

    "Not contradicted" and "confirmed" are different, and the acceptance pre-flight needs the
    second. Before this, a Console that could not read its own cgroup was `ready_to_inspect`
    while the panel said it was not running under systemd — the module docstring said an unknown
    must never be converted into something else, and readiness was converting it into `ready`
    (PR #88 review).
    """
    monkeypatch.setenv(ri.DOCROOT_ENV, str(tmp_path))
    identity = ri.describe(unit_reader=lambda: None)

    assert identity.unit_matches          # still not a mismatch
    assert not identity.unit_proven       # but never positively established
    assert not identity.ready_to_inspect
    assert any("cannot establish which systemd unit" in p for p in identity.problems)
    # And it says so without calling the reading dishonest — a sweep from here still tells the
    # truth; what is missing is proof of whose truth it is.
    assert any("still honest" in p for p in identity.problems)


def test_the_wrong_unit_is_reported_in_words_the_owner_can_act_on(monkeypatch, tmp_path):
    """The whole point: a Console served by the legacy unit says so on its own page, instead of
    letting the collectors report it missing while it renders that very report."""
    monkeypatch.setenv(ri.DOCROOT_ENV, str(tmp_path))
    identity = ri.describe(unit_reader=lambda: ri.LEGACY_DASHBOARD_UNIT)

    assert not identity.unit_matches
    assert not identity.ready_to_inspect
    problem = " ".join(identity.problems)
    assert ri.LEGACY_DASHBOARD_UNIT in problem and ri.CONSOLE_UNIT in problem
    assert "serving this page" in problem


def test_a_missing_docroot_is_a_problem_before_the_sweep_not_after(monkeypatch):
    """An acceptance run spent discovering an unset variable is an acceptance run wasted."""
    monkeypatch.delenv(ri.DOCROOT_ENV, raising=False)
    identity = ri.describe(unit_reader=lambda: ri.CONSOLE_UNIT)

    assert not identity.ready_to_inspect
    assert any(ri.DOCROOT_ENV in p and "not set" in p for p in identity.problems)


def test_a_docroot_that_is_not_a_directory_is_distinguished_from_an_unset_one(monkeypatch,
                                                                             tmp_path):
    """'You forgot to set it' and 'you set it to the wrong thing' need different fixes."""
    missing = tmp_path / "not-a-dir"
    monkeypatch.setenv(ri.DOCROOT_ENV, str(missing))
    identity = ri.describe(unit_reader=lambda: ri.CONSOLE_UNIT)

    assert identity.docroot_state == ri.DOCROOT_MISSING
    assert not identity.docroot_readable
    assert any("no directory at that path" in p for p in identity.problems)


def test_readability_is_exercised_rather_than_predicted(monkeypatch, tmp_path):
    """A directory that EXISTS but this process cannot open is a third state, not a pass.

    The first version asked `os.path.isdir()` and stored the answer in a field called
    `docroot_readable`. That is existence, and labelling existence as readability is exactly the
    kind of claim this project keeps having to correct (PR #88 review): the panel would have
    shown no problem while the runbook told the owner the docroot was readable.

    The probe is injected here because the real permission bits cannot be exercised as root,
    which bypasses them — see the unprivileged test below for the genuine filesystem case.
    """
    monkeypatch.setenv(ri.DOCROOT_ENV, str(tmp_path))

    def refuse(path):
        raise PermissionError(13, "Permission denied", path)

    identity = ri.describe(unit_reader=lambda: ri.CONSOLE_UNIT, docroot_probe=refuse)

    assert identity.docroot_state == ri.DOCROOT_INACCESSIBLE
    assert not identity.docroot_readable
    assert not identity.ready_to_inspect
    problem = " ".join(identity.problems)
    assert "cannot open" in problem and "wp-cli" in problem


@pytest.mark.skipif(os.geteuid() == 0,
                    reason="root bypasses the permission bits this test is about")
def test_an_existing_but_unopenable_docroot_is_detected_on_a_real_filesystem(tmp_path):
    """The same case without the injection seam — real directory, real mode, real refusal."""
    locked = tmp_path / "docroot"
    locked.mkdir()
    (locked / "index.php").write_text("<?php")
    locked.chmod(0o000)
    try:
        assert ri.probe_docroot(str(locked)) == ri.DOCROOT_INACCESSIBLE
    finally:
        locked.chmod(0o755)   # so tmp_path teardown can remove it


def test_an_empty_docroot_is_readable_because_we_got_into_it(tmp_path):
    """We opened the directory; there was simply nothing in it. That is a successful read, and
    calling it inaccessible would be its own overstatement in the other direction."""
    assert ri.probe_docroot(str(tmp_path)) == ri.DOCROOT_READABLE


def test_a_populated_docroot_reads_as_readable(tmp_path):
    (tmp_path / "wp-config.php").write_text("<?php")
    assert ri.probe_docroot(str(tmp_path)) == ri.DOCROOT_READABLE


def test_the_identity_fallbacks_are_unchanged_by_this_increment(monkeypatch):
    """Observations are keyed on (profile, environment). Relabelling either makes every scope's
    predecessor invisible and silently re-baselines the whole history, so a normalization
    increment must reproduce the Console's previous resolution exactly — empty profile is
    single-site `default`, empty environment is `staging`, never `unknown`."""
    import tc_growth.config as config

    class BlankSettings:
        env_kind = ""

    # Set explicitly rather than relying on ambient state: the property under test is the
    # FALLBACK, so both inputs have to be empty on purpose for the assertion to mean anything.
    monkeypatch.setattr(config, "active_site", lambda: "")
    monkeypatch.setattr(config, "get_settings", lambda: BlankSettings())

    assert ri.resolve_identity() == ("default", "staging")


def test_only_a_broken_configuration_yields_an_unresolved_identity(monkeypatch):
    """`unknown` is reserved for a configuration that genuinely could not be read — and that is
    a refusal to record, not a default to record under."""
    import tc_growth.config as config

    def explode():
        raise SystemExit("unknown site profile")

    monkeypatch.setattr(config, "active_site", explode)
    assert ri.resolve_identity() == (ri.UNRESOLVED, ri.UNRESOLVED)

    identity = ri.describe(unit_reader=lambda: ri.CONSOLE_UNIT)
    assert not identity.ready_to_inspect
    assert any("whose environment it is" in p for p in identity.problems)


def test_the_console_page_and_the_self_check_agree_on_identity():
    """One author. Two places computing it independently is how a panel ends up reassuring an
    owner about an identity the collectors are not using."""
    console = (REPO / "orchestrator" / "tc_growth" / "console.py").read_text(encoding="utf-8")
    assert "resolve_identity()" in console
    assert 'active_site() or "default"' not in console


def test_a_fully_configured_console_is_ready(monkeypatch, tmp_path):
    monkeypatch.setenv(ri.DOCROOT_ENV, str(tmp_path))
    monkeypatch.setenv("TC_BUILD_COMMIT", "f23094ca2a12")
    identity = ri.describe(unit_reader=lambda: ri.CONSOLE_UNIT)

    assert identity.ready_to_inspect
    assert identity.problems == ()
    assert identity.build_commit == "f23094ca2a12"


def test_describe_never_raises_even_when_configuration_is_broken(monkeypatch, tmp_path):
    """config.load_env() raises SystemExit for an unknown profile. A Console that cannot describe
    itself must still render the page saying so — a self-check that takes the surface down when
    it fails is worse than no self-check."""
    monkeypatch.setenv(ri.DOCROOT_ENV, str(tmp_path))

    def explode():
        raise SystemExit("unknown site profile")

    monkeypatch.setattr(ri, "unit_of_this_process", explode, raising=False)
    identity = ri.describe(unit_reader=lambda: ri.CONSOLE_UNIT)
    assert identity is not None


# --- the browser surface ----------------------------------------------------------------------

def _panel(**kw) -> str:
    from tc_growth import console_views

    defaults = dict(profile="tossa-cycling", environment="production", unit=ri.CONSOLE_UNIT,
                    expected_unit=ri.CONSOLE_UNIT, build_commit="f23094ca2a12b871",
                    docroot="/var/www/site", docroot_state=ri.DOCROOT_READABLE, problems=())
    defaults.update(kw)
    return console_views.runtime_panel(ri.RuntimeIdentity(**defaults))


def test_a_healthy_runtime_folds_away():
    """When everything is right this is reference material, not a banner competing with the
    health rollup the page exists to show."""
    html = _panel()
    assert "<details" in html
    assert "not fully configured" not in html


def test_a_broken_runtime_is_not_behind_a_fold():
    """The one thing that must not be missable. A collapsed <details> is exactly how a missing
    docroot gets discovered from the `unknown` row it produced instead of before the run."""
    html = _panel(docroot="", docroot_state=ri.DOCROOT_UNSET,
                  problems=("TC_SITE_DOCROOT is not set in this service's environment",))
    assert "<details" not in html
    assert "not fully configured" in html
    assert "TC_SITE_DOCROOT" in html


def test_the_panel_states_only_what_it_established_about_the_docroot():
    """"exists" and "this service can open it" are different claims; it makes only the proved
    one, in words rather than a bare boolean."""
    assert "opened by this service" in _panel()
    inaccessible = _panel(docroot_state=ri.DOCROOT_INACCESSIBLE,
                          problems=("cannot open",))
    assert "could not open it" in inaccessible
    assert "no directory at that path" in _panel(docroot_state=ri.DOCROOT_MISSING,
                                                 problems=("missing",))


def test_the_panel_marks_an_unverified_unit_as_unverified():
    """Not a mismatch, so no "expected" clause — but not silently fine either."""
    html = _panel(unit=None, problems=("cannot establish which systemd unit",))
    assert "could not be established" in html
    assert "unverified" in html
    assert "expected" not in html


def test_the_panel_says_which_unit_was_expected_when_they_differ():
    html = _panel(unit=ri.LEGACY_DASHBOARD_UNIT,
                  problems=("this process is running under tc-dashboard.service",))
    assert "tc-dashboard.service" in html
    assert "expected" in html and ri.CONSOLE_UNIT in html


def test_the_panel_carries_no_secret():
    """It is rendered in a browser and its whole job is to be shown, so nothing may be in it that
    could not be. Every field is a service name, an identity, a commit or a path."""
    html = _panel()
    for field in ("token", "TC_CONSOLE_TOKEN", "password", "secret", "api_key"):
        assert field.lower() not in html.lower()


def test_the_panel_escapes_what_it_renders():
    """Profile and docroot come from configuration, which is not the same as trusted."""
    html = _panel(profile="<script>alert(1)</script>", docroot="/var/www/<img src=x>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_the_health_page_renders_the_panel_and_still_renders_without_one():
    """`identity=None` keeps every existing caller and test working unchanged."""
    from tc_growth import console_views, inspection
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    common = dict(profile="p", environment="production", now=now,
                  effective=inspection.effective_status, freshness=inspection.freshness,
                  rollup=inspection.rollup, value_of=inspection.observation_value)

    without = console_views.operations_health_body(None, [], **common)
    assert "Runtime" not in without

    with_id = console_views.operations_health_body(
        None, [], identity=ri.RuntimeIdentity(
            profile="p", environment="production", unit=ri.CONSOLE_UNIT,
            expected_unit=ri.CONSOLE_UNIT, build_commit="abc123", docroot="/srv/w",
            docroot_state=ri.DOCROOT_READABLE), **common)
    assert "Runtime" in with_id


# --- the deployment writes it -----------------------------------------------------------------

def test_deploy_console_puts_the_docroot_into_the_governed_unit():
    """Item 4 of the review: the owner should not have to remember or paste this before every
    acceptance run. It belongs to the deployed service, like TC_DB_PATH already does."""
    script = (REPO / "orchestrator" / "scripts" / "deploy-console.sh").read_text(encoding="utf-8")
    assert 'SITE_DOCROOT="${TC_SITE_DOCROOT:-}"' in script
    assert "Environment=TC_SITE_DOCROOT=$SITE_DOCROOT" in script
    # And the dry-run plan states it, so an unset docroot is visible before --apply, not after.
    assert "WordPress docroot" in script


def test_autodeploy_records_why_it_does_not_restart_the_console():
    """The Console is pinned at a reviewed commit and advanced deliberately. That is the governed
    design; writing it down stops the next reader 'fixing' it into an auto-advancing execution
    surface."""
    script = (REPO / "orchestrator" / "scripts" / "autodeploy.sh").read_text(encoding="utf-8")
    assert "deliberately NOT" in script and "tc-console.service" in script
    assert "sudo -n systemctl restart tc-console.service" not in script
