"""WP-U4d.1 increment 2 — the privileged boundary, executed (PR #80).

Every test in this file drives the **real installed root-owned program**. Nothing is mocked, and
nothing is asserted from reading the script's source: PR #79's root cause was claims about code
that had never been executed, and a source-inspection test for a privilege boundary reproduces
exactly that failure in a form that looks like evidence.

**These tests require root, and skip without it.** CI runs unprivileged, so a green CI run does
NOT mean they passed — it means they were skipped. Their verbatim output from a root run is
attached to the PR, which is the same shape as the systemd phases: proof comes from the run, not
from the badge.

What still cannot be proven anywhere here: anything needing a booted systemd — daemon-reload,
service restart, restart survival, health, and the transient unit. The privileged program reports
those as `unavailable` and exits 3 rather than claiming them, and `test_apply_reports_the_systemd
_phases_as_unavailable_rather_than_claiming_them` pins that it does.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tc_growth import deploy, deploy_harness, deploy_target

pytestmark = pytest.mark.skipif(
    os.geteuid() != 0,
    reason="the privileged boundary can only be exercised as root; a run that silently proved "
           "less than it claimed is the failure this work package exists to end")

SHA = "a" * 40


@pytest.fixture(scope="session")
def shared_venv(tmp_path_factory):
    """One root-owned interpreter for the whole file.

    Provisioning a virtualenv costs about four seconds; at one per test that is five minutes of
    setup for a suite whose subject is not virtualenv creation. Production shares a single venv
    across releases, so sharing one across disposable targets is the faithful shape as well as the
    fast one — and `test_the_installer_provisions_a_root_owned_interpreter` still exercises the
    provisioning path itself.
    """
    venv = tmp_path_factory.mktemp("shared-venv") / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(venv)],
                   check=True, capture_output=True, timeout=300)
    subprocess.run(["chown", "-R", "root:root", str(venv)], check=True, timeout=120)
    subprocess.run(["chmod", "-R", "go-w", str(venv)], check=True, timeout=120)
    return venv


@pytest.fixture()
def target(tmp_path, shared_venv):
    """A disposable target with the REAL privileged program installed for it."""
    deploy_target._reset_for_tests()
    deploy_target.open_cli_target_gate()
    try:
        built = deploy_harness.build(tmp_path / "target", name="probe", privileged=True,
                                     venv_dir=shared_venv)
    finally:
        deploy_target.close_cli_target_gate()
    try:
        yield built
    finally:
        deploy_harness.teardown(built)
        deploy_target._reset_for_tests()


def run_verb(target, *argv, env: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the installed privileged program exactly as the runner does."""
    return subprocess.run([target.target.privileged_entry, *argv], capture_output=True, text=True,
                          timeout=300.0, env=env)


def staged_release(target, sha: str | None = None) -> Path:
    """A REAL release worktree at a real commit.

    It has to be real: root now authenticates the runtime tree against the commit itself, so a
    fabricated directory at an invented SHA is refused — correctly. Building this from `git
    worktree add` is what makes the apply-path tests exercise the honest case rather than an
    accident of the fixture.
    """
    sha = sha or target.target_sha
    release = Path(target.target.releases_dir) / sha
    if not release.exists():
        subprocess.run(["git", "-C", target.target.app_dir, "worktree", "add", "--detach",
                        str(release), sha], capture_output=True, timeout=120, check=True)
    return release


# --- the trust anchor exists, and is what the program checks ------------------------------------

def test_the_installer_writes_a_real_root_owned_trust_anchor(target):
    """PR #79 defect 3: the anchor appeared in the code, the docs and the PR description, and
    existed in none of them. These are the files on disk after a real install."""
    prefix = Path(target.target.privileged_prefix)
    expected = {"tc-deploy-privileged.sh", "permission-guard.sh", "wp-integrity-scan.sh",
                "target.conf", "manifest.sha256"}
    assert expected <= {p.name for p in prefix.iterdir()}
    for name in expected:
        info = (prefix / name).stat()
        assert info.st_uid == 0 and info.st_gid == 0, f"{name} is not root-owned"
        assert not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH), f"{name} is writable by others"
    manifest = (prefix / "manifest.sha256").read_text()
    for name in expected - {"manifest.sha256"}:
        assert name in manifest, f"the manifest does not cover {name}"


def test_the_privileged_prefix_cannot_be_inside_the_writable_tree(tmp_path):
    """Enforced at target construction, because a prefix that drifts into the deployable tree
    makes every ownership and digest check below it decorative."""
    deploy_target._reset_for_tests()
    deploy_target.open_cli_target_gate()
    try:
        with pytest.raises(deploy.DeployRefused) as exc:
            deploy_target.make_disposable_target(
                name="bad", app_dir=str(tmp_path / "app"),
                releases_dir=str(tmp_path / "releases"), backup_dir=str(tmp_path / "b"),
                db_path=str(tmp_path / "s.db"), venv=str(tmp_path / "v"),
                service="tc-console-bad", unit_prefix="tc-deploy-bad",
                evidence_namespace="disposable/bad", port="1",
                privileged_prefix=str(tmp_path / "app" / "lib"))
        assert "service-user-writable tree" in str(exc.value)
    finally:
        deploy_target._reset_for_tests()


def test_self_check_verifies_and_reports_what_it_verified(target):
    proc = run_verb(target, "self-check")
    assert proc.returncode in (0, 3), proc.stderr
    assert "phase=verify-machinery       status=ok" in proc.stdout
    for name in ("tc-deploy-privileged.sh", "permission-guard.sh", "wp-integrity-scan.sh",
                 "target.conf"):
        assert name in proc.stdout


# --- root runs only its own machinery -----------------------------------------------------------

@pytest.mark.parametrize("victim", ["tc-deploy-privileged.sh", "permission-guard.sh",
                                    "target.conf", "wp-integrity-scan.sh"])
def test_altered_machinery_is_refused_at_every_invocation(target, victim):
    """Criterion: helper, manifest, guard, owner, mode and digest checked EVERY time — not once at
    install. Each of these four files is altered in turn and the program must refuse."""
    path = Path(target.target.privileged_prefix) / victim
    path.write_bytes(path.read_bytes() + b"\n# tampered\n")
    proc = run_verb(target, "self-check")
    assert proc.returncode == 2
    assert "does not match the root-owned manifest" in proc.stderr
    assert victim in proc.stderr


def test_an_incomplete_manifest_is_refused_rather_than_trusted(target):
    """Dropping an entry is easier than forging a digest, so a manifest that simply omits the
    inspector must not be accepted as covering it."""
    manifest = Path(target.target.privileged_prefix) / "manifest.sha256"
    manifest.write_text("".join(line for line in manifest.read_text().splitlines(keepends=True)
                               if "wp-integrity-scan.sh" not in line))
    proc = run_verb(target, "self-check")
    assert proc.returncode == 2
    assert "does not cover wp-integrity-scan.sh" in proc.stderr


@pytest.mark.parametrize("mode", [0o777, 0o775, 0o757, 0o733, 0o702])
def test_an_unsafe_prefix_mode_is_refused(target, mode):
    """The modes the old glob accepted while claiming to reject them (PR #79 defect 4), now
    against the real program rather than a shell function in isolation."""
    os.chmod(target.target.privileged_prefix, mode)
    proc = run_verb(target, "self-check")
    assert proc.returncode == 2
    assert "writable" in proc.stderr


def test_a_non_root_caller_is_refused_by_the_program_itself(target):
    """Not by filesystem permissions — the program is 0755 and reachable, exactly as it is on a
    real host. The refusal has to come from the program."""
    prefix = Path(target.target.privileged_prefix)
    probe = prefix
    while probe != probe.parent:            # make the path traversable, as /usr/local/lib is
        os.chmod(probe, os.stat(probe).st_mode | stat.S_IXOTH | stat.S_IROTH)
        probe = probe.parent
    proc = subprocess.run(
        ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups",
         target.target.privileged_entry, "self-check"],
        capture_output=True, text=True, timeout=120.0)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "only runs as root" in proc.stderr


# --- the interface is verbs, and only verbs -----------------------------------------------------

@pytest.mark.parametrize("argv", [
    ("--apply",), ("",), ("apply;id",), ("exec",), ("bash",), ("-c", "id"),
    ("self-check", "extra"), ("apply",), ("apply", SHA, "extra"), ("rollback", "now"),
    ("start-run", "../../x"), ("start-run", "1;id"), ("Apply", SHA),
])
def test_anything_that_is_not_a_verb_is_refused(target, argv):
    proc = run_verb(target, *argv)
    assert proc.returncode == 2, f"{argv} was not refused: {proc.stdout}"
    assert "REFUSED" in proc.stderr


@pytest.mark.parametrize("bad", [
    "../../etc", f"{SHA}/../../../etc", "AAAA", "aaa", "a" * 39, "a" * 41, "", "  ",
    "$(id)", "a" * 39 + "/", "/etc/passwd",
])
def test_apply_accepts_an_exact_sha_and_nothing_that_could_be_a_path(target, bad):
    """`apply` takes the ONLY caller-supplied value in the whole interface. Everything root
    touches is derived from it plus internal constants, so this is the value that has to be
    airtight."""
    proc = run_verb(target, "apply", bad)
    assert proc.returncode == 2
    assert "exact 40-character lowercase hex SHA" in proc.stderr


def test_a_caller_cannot_name_the_service_unit_port_or_any_path(target):
    """There is no argument for them, and the environment is not consulted. Proven by running
    apply with every one of them forged and checking what root actually wrote."""
    release = staged_release(target)
    hostile = dict(os.environ,
                   TC_SERVICE="sshd", TC_UNIT_PATH="/etc/systemd/system/sshd.service",
                   TC_INSPECTOR_DEST="/usr/bin/id", TC_SUDOERS_FILE="/etc/sudoers.d/pwn",
                   TC_APP_DIR="/etc", TC_RELEASES_DIR="/etc", TC_SNAPSHOT_DIR="/etc",
                   TC_SERVICE_USER="root", TC_CONSOLE_PORT="22", PATH="/nonexistent:" + os.environ["PATH"])
    proc = run_verb(target, "apply", release.name, env=hostile)
    assert proc.returncode in (0, 3), proc.stdout + proc.stderr

    # Root wrote where target.conf said, not where the environment asked.
    assert Path(target.target.unit_path).exists()
    assert target.target.service in Path(target.target.unit_path).read_text()
    assert not Path("/etc/systemd/system/sshd.service").exists()
    assert not Path("/etc/sudoers.d/pwn").exists()


# --- the release cannot redirect what root installs or executes ---------------------------------

def test_root_installs_the_inspector_from_its_own_copy_not_from_the_release(target):
    """The laundering defect, inverted into a property: the bytes at the executable destination
    must equal ROOT'S copy, whatever the release contains."""
    release = staged_release(target)
    (release / "orchestrator" / "scripts" / "wp-integrity-scan.sh").write_text("#!/bin/sh\nid\n")

    proc = run_verb(target, "apply", target.target_sha)
    assert proc.returncode == 2
    assert "does not match the root-owned copy" in proc.stderr
    assert not Path(target.target.inspector_dest).exists(), \
        "root installed something despite refusing"


def test_a_release_matching_roots_copy_is_installed_from_roots_copy(target):
    """The control: with the release honest, apply proceeds and what lands is byte-identical to
    root's own copy — so the refusal above is the check, not an inability to ever install."""
    release = staged_release(target)
    proc = run_verb(target, "apply", target.target_sha)
    assert proc.returncode in (0, 3), proc.stdout + proc.stderr
    assert Path(target.target.inspector_dest).read_bytes() == \
        (Path(target.target.privileged_prefix) / "wp-integrity-scan.sh").read_bytes()


def test_substitution_in_the_toctou_window_after_stage_cannot_redirect_root(target):
    """The reviewer's criterion 4, executed through the full chain.

    `stage` verifies the release against the committed objects and returns ok. The release tree is
    still writable by the service account after that verdict, so the harness substitutes the
    inspector in the gap and lets the privileged consumer run. Root must not inherit the
    unprivileged half's confidence.
    """
    report = deploy_harness.run(target, tamper_after_stage=True)

    stage_step = [s for s in report["step_records"] if s["name"] == "stage"]
    assert any(s["status"] == "ok" for s in stage_step), \
        "stage must PASS, or the TOCTOU window is not what is being tested"

    assert report["status"] == "failed"
    assert report["steps_executed"][-1] == "release"
    assert report["installed_inspector_digest"] is None, "root installed substituted content"
    assert report["payload_executed"] is False
    assert not target.payload_marker.exists()


# --- blocker 1: the COMPLETE runtime is pinned, not one artifact --------------------------------

def test_substituting_an_ordinary_module_after_stage_cannot_change_what_runs(target):
    """Review blocker 1, executed.

    Not the inspector — an ordinary application module the service imports on every start. It is
    substituted in the window after `stage` returns ok, which is precisely where pinning only the
    inspector left the door open.
    """
    report = deploy_harness.run(target, tamper_after_stage="module")

    assert any(s["name"] == "stage" and s["status"] == "ok" for s in report["step_records"]), \
        "stage must PASS, or this is not the post-stage window"
    assert report["status"] == "failed"
    assert report["payload_executed"] is False
    assert not target.payload_marker.exists()
    assert not Path(target.target.unit_path).exists(), \
        "root wrote a unit despite the runtime failing authentication"


def test_the_control_the_substituted_module_really_would_execute(target):
    """Without this the test above proves only that something refused.

    The substituted module is run from the release tree — where the unit used to point — and it
    executes for real and drops its marker. Then the same module is run from root's runtime copy
    and does not, because root's copy holds the authentic bytes. Two real interpreter invocations,
    not an argument.
    """
    release = target.release_path()
    subprocess.run(["git", "-C", target.target.app_dir, "worktree", "add", "--detach",
                    str(release), target.target_sha], capture_output=True, timeout=120, check=True)
    deploy_harness.substitute_application_module(target)

    # 1. From the release tree — the pre-fix ExecStart location.
    assert not target.payload_marker.exists()
    subprocess.run([sys.executable, "-m", "tc_growth.cli"], cwd=str(release / "orchestrator"),
                   capture_output=True, timeout=120,
                   env={"PATH": os.environ["PATH"], "HOME": "/root"})
    assert target.payload_marker.exists(), \
        "the substituted module did not execute even from the release tree — the control is broken"
    target.payload_marker.unlink()

    # 2. Now let the privileged program materialise and authenticate the runtime, then run from
    #    root's copy. Same command, different tree.
    proc = run_verb(target, "apply", target.target_sha)
    assert proc.returncode == 2, "apply should refuse the substituted release"

    # And with an honest release, root's copy is what runs and it is clean.
    deploy_harness.teardown_release(target)
    staged_release(target)                      # re-stage from the commit, unsubstituted
    proc = run_verb(target, "apply", target.target_sha)
    assert proc.returncode in (0, 3), proc.stdout + proc.stderr
    runtime = Path(target.target.runtime_dir) / target.target_sha
    subprocess.run([sys.executable, "-m", "tc_growth.cli"], cwd=str(runtime / "orchestrator"),
                   capture_output=True, timeout=120,
                   env={"PATH": os.environ["PATH"], "HOME": "/root"})
    assert not target.payload_marker.exists(), "root's runtime copy carried the payload"


def test_the_unit_points_at_root_owned_storage_not_the_release_tree(target):
    staged_release(target)
    assert run_verb(target, "apply", target.target_sha).returncode in (0, 3)
    unit = Path(target.target.unit_path).read_text()
    assert target.target.runtime_dir in unit
    assert f"WorkingDirectory={target.target.runtime_dir}/{target.target_sha}/orchestrator" in unit
    assert target.target.releases_dir not in unit, \
        "the unit still names the service-user-writable release tree"


def test_the_runtime_copy_is_root_owned_and_unwritable_by_anyone_else(target):
    staged_release(target)
    assert run_verb(target, "apply", target.target_sha).returncode in (0, 3)
    runtime = Path(target.target.runtime_dir) / target.target_sha
    assert runtime.is_dir()
    for path in [runtime, *runtime.rglob("*")]:
        info = path.stat()
        assert info.st_uid == 0, f"{path} is not root-owned"
        assert not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH), f"{path} is writable by others"
    assert not (runtime / ".git").exists(), \
        "the worktree's .git pointer was carried into root-owned storage"


def test_a_service_user_writable_interpreter_is_refused(target):
    """The venv is part of what the SHA has to cover: swapping the interpreter changes what runs
    without touching one application file."""
    staged_release(target)
    entry_dir = Path(target.target.venv) / "bin"
    original = entry_dir.stat().st_mode
    try:
        os.chmod(entry_dir, 0o777)
        proc = run_verb(target, "apply", target.target_sha)
        assert proc.returncode == 2
        assert "writable" in proc.stderr
    finally:
        # The interpreter is shared across this file's targets, so a test that loosens it must put
        # it back. Leaving it 0777 poisoned every subsequent fixture — which is how a suite ends up
        # reporting failures that belong to its own setup rather than to the code.
        os.chmod(entry_dir, original)


# --- blocker 2: rollback restores ABSENCE, not just content -------------------------------------

def test_a_first_deployment_rolls_back_to_nothing(target):
    """Review blocker 2, executed. Before the first apply none of the managed artifacts exist, so
    a rollback that only restores files leaves all three in place and calls it success."""
    for artifact in (target.target.unit_path, target.target.inspector_dest,
                     target.target.sudoers_file):
        assert not Path(artifact).exists(), "the fixture is not a first deployment"

    staged_release(target)
    assert run_verb(target, "apply", target.target_sha).returncode in (0, 3)
    for artifact in (target.target.unit_path, target.target.inspector_dest,
                     target.target.sudoers_file):
        assert Path(artifact).exists(), f"apply did not install {artifact}"

    proc = run_verb(target, "rollback")
    assert proc.returncode in (0, 3), proc.stdout + proc.stderr
    for name in ("unit", "inspector", "sudoers", "current"):
        assert f"phase=rollback-{name}" in proc.stdout
        assert "removed" in proc.stdout
    # Four, not three: the current-runtime pointer is a managed artifact too, and its prior
    # ABSENCE has to be restored or start-run would keep naming a rolled-back runtime.
    assert "restored=0 removed=4 failed=0" in proc.stdout

    for artifact in (target.target.unit_path, target.target.inspector_dest,
                     target.target.sudoers_file):
        assert not Path(artifact).exists(), \
            f"rollback left {artifact} behind — it did not exist before apply"


def test_rollback_reports_each_artifact_separately(target):
    """Criterion 6: full, partial and failed must be distinguishable. A generic success after a
    skipped removal is the defect."""
    staged_release(target)
    Path(target.target.inspector_dest).parent.mkdir(parents=True, exist_ok=True)
    Path(target.target.inspector_dest).write_text("#!/bin/sh\n# pre-existing\n")
    assert run_verb(target, "apply", target.target_sha).returncode in (0, 3)

    proc = run_verb(target, "rollback")
    assert proc.returncode in (0, 3), proc.stdout + proc.stderr
    assert "phase=rollback-inspector     status=restored" in proc.stdout
    assert "phase=rollback-unit          status=removed" in proc.stdout
    assert "restored=1 removed=3 failed=0" in proc.stdout
    assert Path(target.target.inspector_dest).read_text() == "#!/bin/sh\n# pre-existing\n"
    assert not Path(target.target.unit_path).exists()


def test_a_snapshot_without_recorded_state_is_refused_rather_than_guessed(target):
    staged_release(target)
    assert run_verb(target, "apply", target.target_sha).returncode in (0, 3)
    previous = (Path(target.target.snapshot_dir) / "previous").read_text().strip()
    (Path(target.target.snapshot_dir) / previous / "state").unlink()
    proc = run_verb(target, "rollback")
    assert proc.returncode == 2
    assert "refusing to roll back blind" in proc.stderr


def test_a_partial_rollback_is_never_reported_as_complete(target):
    """The snapshot says a file was present, but its saved copy is gone. Rollback must say
    partial and exit non-zero rather than reporting the artifacts it did manage."""
    staged_release(target)
    Path(target.target.inspector_dest).parent.mkdir(parents=True, exist_ok=True)
    Path(target.target.inspector_dest).write_text("#!/bin/sh\n# pre-existing\n")
    assert run_verb(target, "apply", target.target_sha).returncode in (0, 3)
    previous = (Path(target.target.snapshot_dir) / "previous").read_text().strip()
    (Path(target.target.snapshot_dir) / previous / "inspector.prev").unlink()

    proc = run_verb(target, "rollback")
    assert proc.returncode == 2
    assert "phase=rollback-inspector     status=failed" in proc.stdout
    assert "status=partial" in proc.stdout
    assert "failed=1" in proc.stdout
    assert "NOT a completed rollback" in proc.stdout


# --- rollback selects nothing the caller can influence -------------------------------------------

def test_rollback_restores_from_root_owned_state(target):
    release = staged_release(target)
    Path(target.target.inspector_dest).parent.mkdir(parents=True, exist_ok=True)
    Path(target.target.inspector_dest).write_text("#!/bin/sh\n# the previous release\n")
    previous = Path(target.target.inspector_dest).read_bytes()

    assert run_verb(target, "apply", target.target_sha).returncode in (0, 3)
    assert Path(target.target.inspector_dest).read_bytes() != previous

    proc = run_verb(target, "rollback")
    assert proc.returncode in (0, 3), proc.stdout + proc.stderr
    assert "selected by root-written pointer" in proc.stdout
    assert Path(target.target.inspector_dest).read_bytes() == previous


def test_a_poisoned_rollback_pointer_is_refused(target):
    """Round 4's defect was rollback selecting through a caller-influenced value. The pointer is
    root-written now, and still validated — a value is a value."""
    release = staged_release(target)
    assert run_verb(target, "apply", target.target_sha).returncode in (0, 3)
    (Path(target.target.snapshot_dir) / "previous").write_text("../../etc\n")
    proc = run_verb(target, "rollback")
    assert proc.returncode == 2
    assert "not a SHA" in proc.stderr


# --- git object replacement cannot forge root's authentication ----------------------------------

def test_a_replace_ref_cannot_make_root_authenticate_substituted_content(target):
    """Review blocker 2, executed.

    `refs/replace/<oid>` substitutes objects TRANSPARENTLY: `ls-tree`/`cat-file` return the
    attacker's tree while every command still names the authorized SHA. The service user owns this
    repository, so they can write that ref. Root reads with `--no-replace-objects` and
    `GIT_NO_REPLACE_OBJECTS=1`, so its authentication is against the real objects.
    """
    staged_release(target)
    deploy_harness.substitute_application_module(target)
    deploy_harness.install_replace_ref(target)

    # The control: plain git IS fooled. Without it this test could pass because of any refusal.
    fooled = subprocess.run(["git", "-C", target.target.app_dir, "ls-tree", "-r",
                             target.target_sha], capture_output=True, text=True,
                            timeout=120).stdout
    honest = subprocess.run(["git", "-C", target.target.app_dir, "--no-replace-objects",
                             "ls-tree", "-r", target.target_sha], capture_output=True, text=True,
                            timeout=120, env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}).stdout
    fooled_line = [ln for ln in fooled.splitlines() if "cli.py" in ln][0]
    honest_line = [ln for ln in honest.splitlines() if "cli.py" in ln][0]
    assert fooled_line != honest_line, \
        "the replace ref had no effect, so this proves nothing about disabling it"

    proc = run_verb(target, "apply", target.target_sha)
    assert proc.returncode == 2
    assert "does not match commit" in proc.stderr
    assert not target.payload_marker.exists()
    assert not Path(target.target.unit_path).exists()


def test_root_reads_git_with_replacement_disabled(target):
    """Supporting, and labelled: both the flag and the variable, because the flag covers this
    invocation and the variable covers anything git re-execs."""
    source = (Path(target.target.privileged_prefix) / "tc-deploy-privileged.sh").read_text()
    assert "GIT_NO_REPLACE_OBJECTS=1" in source
    assert "--no-replace-objects" in source


# --- start-run is reachable, and runs immutable code --------------------------------------------

def test_the_sudoers_drop_in_grants_the_transient_unit_verb(target):
    """Review blocker 1, first half: the verb existed in the script and was unreachable in the
    installed system, so the accepted criterion-3 architecture was present but not usable."""
    staged_release(target)
    assert run_verb(target, "apply", target.target_sha).returncode in (0, 3)
    sudoers = Path(target.target.sudoers_file).read_text()
    entry = target.target.privileged_entry
    assert f"{entry} start-run [0-9]*" in sudoers
    for verb in ("apply", "rollback", "self-check"):
        assert f"{entry} {verb}" in sudoers
    assert "systemd-run" not in sudoers, "systemd-run must never be granted as a capability"


def test_start_run_refuses_before_any_deployment_has_been_applied(target):
    """There is no root-owned runtime yet, so there is no immutable code path to run the runner
    from. Refusing beats falling back to the service-user-writable checkout."""
    proc = run_verb(target, "start-run", "7")
    assert proc.returncode == 2
    assert "no deployment has been applied" in proc.stderr


def test_start_run_uses_the_root_owned_runtime_and_verified_interpreter(target):
    """Review blocker 1, second half: it used to launch from TC_APP_DIR and TC_VENV — both the
    service-user side of the boundary. Root creating a unit that executes mutable code is the
    boundary ending one process early, again."""
    staged_release(target)
    assert run_verb(target, "apply", target.target_sha).returncode in (0, 3)

    proc = run_verb(target, "start-run", "7")
    assert proc.returncode in (0, 3), proc.stdout + proc.stderr
    assert "phase=verify-runtime         status=ok" in proc.stdout
    assert "phase=verify-interpreter     status=ok" in proc.stdout
    assert target.target.runtime_dir in proc.stdout
    assert f"{target.target.app_dir}/orchestrator" not in proc.stdout, \
        "the runner would execute from the service-user-writable checkout"


def test_the_current_runtime_pointer_is_restored_by_rollback(target):
    """`current` is what start-run executes from, so it is snapshotted and restored like any other
    managed artifact — including its prior ABSENCE on a first deployment."""
    staged_release(target)
    assert run_verb(target, "apply", target.target_sha).returncode in (0, 3)
    assert (Path(target.target.snapshot_dir) / "current").exists()

    assert run_verb(target, "rollback").returncode in (0, 3)
    assert not (Path(target.target.snapshot_dir) / "current").exists(), \
        "rollback left a current-runtime pointer that did not exist before apply"
    assert run_verb(target, "start-run", "7").returncode == 2


# --- the interpreter is deployable, not merely refused ------------------------------------------

def test_the_installer_provisions_a_root_owned_interpreter(tmp_path):
    """Review blocker 3: refusing a service-user-owned venv is safe but leaves the real host apply
    path non-functional. The installer provisions and locks one instead.

    Builds its own target rather than using the shared-venv fixture, because the thing under test
    IS the provisioning path."""
    deploy_target._reset_for_tests()
    deploy_target.open_cli_target_gate()
    try:
        target = deploy_harness.build(tmp_path / "provisioned", name="probe", privileged=True)
    finally:
        deploy_target.close_cli_target_gate()
    venv = Path(target.target.venv)
    assert (venv / "bin" / "python").exists()
    real = (venv / "bin" / "python").resolve()
    assert real.stat().st_uid == 0
    assert not real.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    assert (venv / "bin").stat().st_uid == 0
    assert not (venv / "bin").stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    deploy_harness.teardown(target)
    deploy_target._reset_for_tests()


def test_the_installer_refuses_an_interpreter_the_service_user_could_write(tmp_path):
    """And says exactly how to fix it, rather than letting the deployment discover it later at the
    one moment nobody is watching."""
    venv = tmp_path / "writable-venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(sys.executable)
    os.chmod(venv / "bin", 0o777)
    root = tmp_path / "t"
    for sub in ("app", "releases", "priv", "host"):
        (root / sub).mkdir(parents=True)
    scripts = deploy_harness.REPO_SCRIPTS
    proc = subprocess.run(
        ["bash", str(scripts / "install-tc-deploy.sh"),
         "--prefix", str(root / "priv" / "lib"), "--app-dir", str(root / "app"),
         "--releases-dir", str(root / "releases"), "--service", "tc-console-x",
         "--service-user", "root", "--port", "8401",
         "--unit-path", str(root / "host" / "x.service"),
         "--inspector-dest", str(root / "host" / "insp.sh"),
         "--sudoers-file", str(root / "host" / "sudoers-x"),
         "--snapshot-dir", str(root / "host" / "snap"), "--unit-prefix", "tc-deploy-x",
         "--runtime-dir", str(root / "priv" / "runtime"), "--venv", str(venv)],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 2
    assert "does not satisfy the boundary" in proc.stderr
    assert "--provision-venv" in proc.stderr
    assert not (root / "priv" / "lib").exists(), "the install proceeded despite rejecting"


# --- what is NOT proven here, pinned so it cannot be quietly claimed -----------------------------

def test_apply_reports_the_systemd_phases_as_unavailable_rather_than_claiming_them(target):
    """The honesty property. Off-host, apply must complete its file phases, report the manager
    phases as `unavailable`, and exit 3 — never print ok for something it skipped."""
    if Path("/run/systemd/system").is_dir():
        pytest.skip("systemd IS booted here, so there is no unavailable path to observe")
    release = staged_release(target)
    proc = run_verb(target, "apply", target.target_sha)
    assert proc.returncode == 3
    for phase in ("daemon-reload", "restart-service", "health-check"):
        assert f"phase={phase:<22} status=unavailable" in proc.stdout
    assert "these phases did NOT run" in proc.stdout
    assert "status=ok" in proc.stdout, "the file phases should still have run"


def test_the_runner_treats_the_systemd_gap_as_a_failure_not_a_success(target):
    """Exit 3 must not become a green step. A deployment that did not restart the service did not
    deploy, and the record has to say so."""
    if Path("/run/systemd/system").is_dir():
        pytest.skip("systemd IS booted here")
    report = deploy_harness.run(target)
    assert report["status"] == "failed"
    assert "systemd is not booted" in report["terminal_message"]
    assert "did not run" in report["terminal_message"]


def test_the_transient_unit_verb_refuses_rather_than_pretending(target):
    """A deployment must have been applied first, or start-run refuses earlier for a different and
    better reason — no immutable runtime to launch from. That refusal has its own test; this one
    is about not claiming a unit it did not create."""
    if Path("/run/systemd/system").is_dir():
        pytest.skip("systemd IS booted here")
    staged_release(target)
    assert run_verb(target, "apply", target.target_sha).returncode in (0, 3)
    proc = run_verb(target, "start-run", "7")
    assert proc.returncode == 3
    assert "phase=transient-unit         status=unavailable" in proc.stdout
    assert "no transient unit was created" in proc.stdout


def test_deploy_release_is_still_disabled(target):
    from tc_growth.core.actions import get_operation

    assert get_operation("deploy_release").enabled is False
