"""WP-U4d.1 — the disposable target, run for real (PR #80, first executable increment).

These are not tests of a description. Each one builds a genuine deployment target on disk — its
own git repository with its own remote, its own SQLite store, its own backup directory, its own
service and transient-unit names, its own evidence namespace — and runs the **production
executors** against it as real subprocesses.

The one that matters is `test_substituted_release_content_is_refused...`: content is replaced in
the staged release worktree AFTER checkout (PR #79 defect 2, made concrete), and the chain must
refuse before the privileged step. Immediately below it is the control that stops that from being
a hollow result — with the content check, and only the content check, disabled, the substituted
payload really does execute. So the refusal is doing the work.

Cost: each full run is a handful of git invocations, a real pytest subprocess and a real sqlite
migration. That is the price of a claim that comes from executing rather than reading.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys

import pytest

from tc_growth import deploy, deploy_harness, deploy_target
from tc_growth.store.sqlite import SqliteStore


@pytest.fixture()
def disposable(tmp_path):
    """A built disposable target, torn down afterwards.

    The gate is opened exactly the way `tc_growth.cli deploy-harness` opens it and closed again as
    soon as the target exists — the harness is subject to the seam, not exempt from it.
    """
    deploy_target._reset_for_tests()
    deploy_target.open_cli_target_gate()
    try:
        built = deploy_harness.build(tmp_path / "target", name="probe")
    finally:
        deploy_target.close_cli_target_gate()
    try:
        yield built
    finally:
        deploy_harness.teardown(built)
        deploy_target._reset_for_tests()


# --- the target really is separate -------------------------------------------------------------

def test_the_disposable_target_owns_every_path_it_uses(disposable, tmp_path):
    target = disposable.target
    assert target.disposable is True
    assert target.evidence_namespace == "disposable/probe"
    assert target.service == "tc-console-probe" != deploy_target.PRODUCTION.service
    assert target.unit_prefix == "tc-deploy-probe"
    for path in (target.app_dir, target.releases_dir, target.backup_dir, target.db_path,
                 target.venv):
        assert path.startswith(str(tmp_path)), f"{path} escapes the throwaway root"
        assert not path.startswith("/opt/tc_ai_growth"), "the disposable target touches production"
    assert os.path.isdir(os.path.join(target.app_dir, ".git"))
    assert os.path.isdir(disposable.origin)
    assert os.path.exists(target.db_path)


def test_the_checkout_starts_behind_its_remote_so_the_chain_has_real_work(disposable):
    """If the app checkout were already at the target commit, `preflight` and `converge` would be
    restating an assumption instead of answering a question."""
    head = subprocess.run(["git", "-C", disposable.target.app_dir, "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=60).stdout.strip()
    assert head == disposable.base_sha
    assert disposable.base_sha != disposable.target_sha


# --- the clean run, executed end to end --------------------------------------------------------

def test_the_real_chain_runs_end_to_end_against_the_disposable_target(disposable):
    report = deploy_harness.run(disposable)
    assert report["status"] == "succeeded", report["terminal_message"]
    assert report["steps_executed"] == ["preflight", "backup", "converge", "suite", "migrate",
                                        "stage", "release"]
    assert report["privileged_mutation_reached"] is True
    assert report["payload_executed"] is False

    # The checkout really converged, the store really migrated, the backup really exists.
    head = subprocess.run(["git", "-C", disposable.target.app_dir, "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=60).stdout.strip()
    assert head == disposable.target_sha
    backups = os.listdir(disposable.target.backup_dir)
    assert backups and all(b.endswith(".bak") for b in backups)
    conn = __import__("sqlite3").connect(disposable.target.db_path)
    try:
        assert conn.execute("SELECT count(*) FROM disposable_migrations").fetchone()[0] >= 1
    finally:
        conn.close()


def test_the_terminal_message_names_only_the_steps_that_ran(disposable):
    """`health` is not in the disposable chain, and the record must not imply it was. The runner
    used to end every successful run with 'verified on loopback' regardless of the step list."""
    report = deploy_harness.run(disposable)
    assert "health" not in report["terminal_message"]
    assert "loopback" not in report["terminal_message"]
    assert "completed: preflight, backup, converge, suite, migrate, stage, release" in \
        report["terminal_message"]


def test_the_disposable_run_is_recorded_in_its_own_store_under_its_own_namespace(disposable):
    report = deploy_harness.run(disposable)
    store = SqliteStore(disposable.target.db_path)
    try:
        row = store.get_deploy_run(report["run_id"])
        assert row["requested_by"] == "harness:disposable/probe"
        assert __import__("json").loads(row["plan"])["target"] == "probe"
        assert __import__("json").loads(row["plan"])["disposable"] is True
    finally:
        store.close()


# --- the adversarial case: content substituted after checkout ----------------------------------

def test_substituted_release_content_is_refused_before_any_privileged_mutation(disposable):
    """The milestone's criterion 4, executed through the full process chain.

    The release worktree is a legitimate checkout of the reviewed commit — `git rev-parse HEAD` in
    it still answers with the right SHA — and one file in it has been replaced afterwards. The run
    must end refused, at `stage`, with the privileged stand-in never started and the substituted
    payload never executed. Both of those are files on disk, not mock call counts.
    """
    payload = deploy_harness.tamper_with_release(disposable)
    assert payload.exists()

    report = deploy_harness.run(disposable)

    assert report["status"] == "refused"
    assert report["steps_executed"][-1] == "stage"
    assert "release" not in report["steps_executed"]
    assert "does not match commit" in report["terminal_message"]
    assert "orchestrator/scripts/deploy-console.sh" in report["terminal_message"]

    assert report["privileged_mutation_reached"] is False
    assert report["payload_executed"] is False
    assert not disposable.privileged_marker.exists()
    assert not disposable.payload_marker.exists()

    # The tampered file is still exactly as the adversary left it: the chain refused it, it did not
    # quietly repair it and carry on. A silent repair would hide the incident.
    assert "payload executed" in payload.read_text()


def test_the_control_the_refusal_depends_on_the_payload_really_would_execute(disposable,
                                                                             monkeypatch):
    """Without this, the test above proves only that the harness never reaches the release step.

    Exactly one thing is disabled — the release-content comparison — and everything else runs
    unchanged. The substituted payload then executes for real and drops its marker, which is what
    makes the refusal above a property of the check rather than of the harness's shape.
    """
    monkeypatch.setattr(deploy, "verify_release_content", lambda path, manifest: (True, "disabled"))
    deploy_harness.tamper_with_release(disposable)

    report = deploy_harness.run(disposable)

    assert report["status"] == "succeeded"
    assert report["privileged_mutation_reached"] is True
    assert report["payload_executed"] is True, (
        "the harness could not observe the payload executing, so the refusal test proves nothing")


@pytest.mark.parametrize("kind", ["added", "removed", "mode"])
def test_every_kind_of_release_tampering_is_refused_not_just_edits(disposable, kind):
    """An edited file is the obvious case. A file ADDED to the release, one REMOVED from it, and
    one whose executable bit was flipped are all ways to change what runs, and each has to be
    caught by content comparison rather than assumed away."""
    release = disposable.release_path()
    subprocess.run(["git", "-C", disposable.target.app_dir, "worktree", "add", "--detach",
                    str(release), disposable.target_sha], capture_output=True, timeout=120,
                   check=True)
    victim = release / "orchestrator" / "scripts" / "deploy-console.sh"
    if kind == "added":
        (release / "orchestrator" / "scripts" / "extra.sh").write_text("#!/bin/sh\nexit 0\n")
    elif kind == "removed":
        victim.unlink()
    else:
        victim.chmod(victim.stat().st_mode & ~stat.S_IXUSR)

    report = deploy_harness.run(disposable)
    assert report["status"] == "refused"
    assert report["privileged_mutation_reached"] is False
    expected = {"added": "added: 1", "removed": "removed: 1", "mode": "changed: 1"}[kind]
    assert expected in report["terminal_message"], report["terminal_message"]


# --- the verifier itself -----------------------------------------------------------------------

def test_the_manifest_is_read_from_the_committed_objects_not_from_the_worktree(disposable):
    """The trust anchor question, as far as this increment answers it: the manifest must describe
    what was committed, so editing the checkout cannot edit the manifest.

    What this does NOT establish — stated here because it is the next increment's whole job — is
    that the object store is trustworthy to a ROOT process. It is writable by the same
    unprivileged account, so this proves the release tree matches the commit, not that the commit
    is what root should trust. That needs a root-owned manifest.
    """
    manifest = deploy.commit_manifest(disposable.target.app_dir, disposable.target_sha)
    assert "orchestrator/scripts/deploy-console.sh" in manifest
    before = dict(manifest)

    edited = os.path.join(disposable.target.app_dir, "orchestrator", "scripts",
                          "deploy-console.sh")
    with open(edited, "w") as fh:
        fh.write("#!/bin/sh\n# edited in the checkout\n")

    assert deploy.commit_manifest(disposable.target.app_dir, disposable.target_sha) == before


def test_the_verifier_reports_what_differs_rather_than_only_that_something_does(tmp_path):
    root = tmp_path / "release"
    (root / "sub").mkdir(parents=True)
    (root / "kept.txt").write_text("same")
    (root / "sub" / "changed.txt").write_text("after")
    (root / "sub" / "added.txt").write_text("new")
    digest_of = lambda text: __import__("hashlib").sha256(text.encode()).hexdigest()  # noqa: E731
    manifest = {
        "kept.txt": ("100644", digest_of("same")),
        "sub/changed.txt": ("100644", digest_of("before")),
        "sub/gone.txt": ("100644", digest_of("gone")),
    }
    ok, detail = deploy.verify_release_content(str(root), manifest)
    assert not ok
    assert "added: 1 (sub/added.txt)" in detail
    assert "removed: 1 (sub/gone.txt)" in detail
    assert "changed: 1 (sub/changed.txt)" in detail


def test_a_matching_worktree_verifies_clean(disposable):
    release = disposable.release_path()
    subprocess.run(["git", "-C", disposable.target.app_dir, "worktree", "add", "--detach",
                    str(release), disposable.target_sha], capture_output=True, timeout=120,
                   check=True)
    manifest = deploy.commit_manifest(disposable.target.app_dir, disposable.target_sha)
    ok, detail = deploy.verify_release_content(str(release), manifest)
    assert ok, detail
    assert f"{len(manifest)} files match" in detail


def test_the_worktrees_git_pointer_is_not_treated_as_release_content(disposable):
    """A worktree's `.git` is a FILE pointing into the parent repository's administrative
    directory. It is not in the commit, so counting it would make every clean release look
    tampered — and excluding it is why the check must be explicit about what it walks."""
    release = disposable.release_path()
    subprocess.run(["git", "-C", disposable.target.app_dir, "worktree", "add", "--detach",
                    str(release), disposable.target_sha], capture_output=True, timeout=120,
                   check=True)
    assert (release / ".git").is_file()
    assert ".git" not in deploy._worktree_paths(str(release))


# --- the CLI verb is the entry point, and it is a CLI verb -------------------------------------

def test_the_harness_runs_from_the_command_line_and_reports_the_adversarial_result(tmp_path):
    """End to end through `python -m tc_growth.cli`, in its own process — the way an operator runs
    it, and the only place the target gate is ever opened."""
    root = tmp_path / "cli-target"
    proc = subprocess.run(
        [sys.executable, "-m", "tc_growth.cli", "deploy-harness", str(root), "--tamper"],
        cwd=os.path.dirname(os.path.dirname(deploy.__file__)),
        capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "terminal status ........ REFUSED" in proc.stdout
    assert "privileged mutation reached ... no" in proc.stdout
    assert "substituted payload executed .. no" in proc.stdout
    assert "EXPECTED: refused before any privileged mutation — CONFIRMED" in proc.stdout
    assert not root.exists(), "the disposable target was not torn down"


def test_the_harness_refuses_to_build_over_an_existing_directory(tmp_path):
    root = tmp_path / "occupied"
    root.mkdir()
    (root / "something-important.txt").write_text("do not delete me")
    proc = subprocess.run(
        [sys.executable, "-m", "tc_growth.cli", "deploy-harness", str(root)],
        cwd=os.path.dirname(os.path.dirname(deploy.__file__)),
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2
    assert "non-empty directory" in proc.stdout
    assert (root / "something-important.txt").exists()


# --- the operation stays refused throughout ----------------------------------------------------

def test_deploy_release_is_still_disabled_after_all_of_this():
    """Criterion 7, restated where the harness work would be tempted to change it: a disposable
    proof of ONE fail-closed case is not the disposable proof of the whole chain, and the operation
    stays server-refused until the privileged increment lands and is proven too."""
    from tc_growth.core.actions import get_operation

    assert get_operation("deploy_release").enabled is False
