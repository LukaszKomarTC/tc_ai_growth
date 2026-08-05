"""WP-U4d.1 — the disposable target harness (PR #80, first executable increment).

Across PR #79's eight review rounds the failure was never a missing check. It was a check whose
inputs I controlled, a check that looked right and wasn't, a trust anchor that existed only in
prose, and — the root cause — **claims about code that had never been executed**. This module is
the answer to that: it builds a throwaway deployment target on disk and runs the real chain
against it, so properties are recorded rather than argued.

What is real here
-----------------
The disposable target is a genuine git repository with a genuine remote, a genuine SQLite store, a
genuine Python interpreter reachable through its own `bin/python`, and its own service name,
transient-unit prefix and evidence namespace. `preflight`, `backup`, `converge`, `suite`,
`migrate` and `stage` run the **production executors**, unmodified, as real subprocesses.

What is a stand-in, and why it is labelled one
----------------------------------------------
`release` performs the privileged host mutation, and the redesigned privileged program does not
exist yet — it is deliberately not in this increment. So the harness substitutes a stand-in: a
real executable, kept outside the target's application tree, which records that the privileged
boundary was reached and then executes the release worktree's own deploy script exactly as a real
privileged step would.

That last part is the point. It means an adversarial payload written into the release tree WOULD
run if the chain reached this step, so "the payload did not execute" is a fact about a process
that was never started, not an assertion about a mock that was never called. Both markers are
files on disk; the harness reports whether they exist.

`health` is not part of the disposable chain — there is no Console serving on the disposable
target to answer on loopback. The chain is run with an explicit step list, and the report says
which steps were executed, so nothing here can be read as covering more than it did.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import deploy, deploy_target
from .store.sqlite import SqliteStore

#: Steps the disposable chain runs. `health` is excluded on purpose — see the module docstring.
DISPOSABLE_STEPS = tuple(s for s in deploy.STEPS if s.name != "health")

PRIVILEGED_MARKER = "PRIVILEGED-MUTATION-REACHED"
PAYLOAD_MARKER = "PAYLOAD-EXECUTED"

#: The disposable target's own application, committed into its own repository. It is a small,
#: separate program on purpose: the chain deploys whatever the target's tree contains, and using a
#: copy of this repository would make the run circular and slow without proving anything more.
_APP_FILES = {
    "README.md": "Disposable deployment target. Built by tc_growth.deploy_harness; safe to delete.\n",
    "orchestrator/tc_growth/__init__.py": "",
    "orchestrator/tc_growth/cli.py": '''"""The disposable target's application. `db-init` is what the migrate step runs."""

import os
import sqlite3
import sys


def db_init() -> int:
    path = os.environ.get("TC_DB_PATH")
    if not path:
        print("TC_DB_PATH is not set", file=sys.stderr)
        return 2
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS disposable_migrations "
                 "(id INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("INSERT INTO disposable_migrations (id) VALUES (NULL)")
    conn.commit()
    conn.close()
    print("disposable store migrated")
    return 0


if __name__ == "__main__":
    sys.exit(db_init() if sys.argv[1:2] == ["db-init"] else 1)
''',
    "orchestrator/tests/test_disposable_app.py": (
        "def test_the_disposable_application_has_a_real_suite_that_really_runs():\n"
        "    assert True\n"),
    "orchestrator/scripts/deploy-console.sh": (
        "#!/usr/bin/env bash\n"
        "# The release script the privileged step executes FROM the release worktree. In the\n"
        "# tampered run this file is replaced, which is how the harness proves the substituted\n"
        "# content never reaches execution.\n"
        "set -euo pipefail\n"
        'echo "disposable deploy-console.sh: $*"\n'),
    # The inspector is the file the privileged program authenticates against its ROOT-OWNED copy
    # before installing. It is the disposable target's own, so the installer's copy and the
    # release's copy start identical and a post-checkout substitution makes them differ.
    "orchestrator/scripts/wp-integrity-scan.sh": (
        "#!/usr/bin/env bash\n"
        "# The disposable target's integrity inspector. Root installs this from ITS OWN copy,\n"
        "# never from the release tree.\n"
        "set -euo pipefail\n"
        'echo "disposable inspector ok"\n'),
}

_EXECUTABLE = {"orchestrator/scripts/deploy-console.sh",
               "orchestrator/scripts/wp-integrity-scan.sh"}


#: Where the reviewed privileged sources live in this checkout.
REPO_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@dataclass(frozen=True)
class Disposable:
    """A built disposable target and the facts a test or an operator needs about it."""

    target: deploy_target.Target
    root: Path
    origin: Path
    state_dir: Path
    privileged_dir: Path
    base_sha: str
    target_sha: str
    #: True when the REAL root-owned privileged program was installed for this target. False means
    #: the run uses the increment-1 stand-in, which proves nothing about the root boundary — the
    #: report says which, so a reader never has to guess.
    privileged: bool = False

    @property
    def privileged_marker(self) -> Path:
        return self.state_dir / PRIVILEGED_MARKER

    @property
    def payload_marker(self) -> Path:
        return self.state_dir / PAYLOAD_MARKER

    def release_path(self, sha: str | None = None) -> Path:
        return Path(self.target.release_dir(sha or self.target_sha))


# --------------------------------------------------------------------------- building the target

def _git(cwd: Path, *args: str, env_extra: dict | None = None) -> str:
    """Run git with a CONSTRUCTED identity and no user configuration.

    The harness must not depend on whoever's machine it runs on: `GIT_CONFIG_GLOBAL=/dev/null`
    keeps a developer's `~/.gitconfig` (hooks, templates, `core.autocrlf`, a default branch name)
    out of a run whose whole purpose is to be reproducible.
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(cwd),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "deploy harness",
        "GIT_AUTHOR_EMAIL": "harness@invalid",
        "GIT_COMMITTER_NAME": "deploy harness",
        "GIT_COMMITTER_EMAIL": "harness@invalid",
    }
    env.update(env_extra or {})
    proc = subprocess.run(["git", *args], cwd=str(cwd), env=env, capture_output=True, text=True,
                          timeout=300.0)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if rel in _EXECUTABLE:
        path.chmod(0o755)


def build(root: Path, *, name: str = "disposable", privileged: bool | None = None,
          venv_dir: Path | None = None) -> Disposable:
    """Create a complete, isolated deployment target under `root`.

    Requires the command-line target gate to be open — that is the seam, and the harness is
    subject to it like everything else rather than being exempt from it.

    `privileged` installs the REAL root-owned program for this target, which needs root. Left as
    `None` it follows whether we are root, so a CI run (unprivileged) transparently gets the
    increment-1 stand-in while a root run gets the real boundary. Asking for it explicitly
    without root is an error rather than a silent downgrade — a harness that quietly proves less
    than it was asked to is worse than one that refuses.
    """
    if privileged and os.geteuid() != 0:
        raise deploy_target.DeployRefused(
            "the privileged boundary can only be installed as root; refusing to silently fall "
            "back to the stand-in, which proves nothing about root")
    if privileged is None:
        privileged = os.geteuid() == 0

    root = Path(root).resolve()
    app, releases, backups = root / "app", root / "releases", root / "backups"
    state, privileged_dir = root / "state", root / "privileged"
    # A caller may supply an already-provisioned root-owned venv. Production shares one across
    # releases, so sharing one across disposable targets is the faithful shape — and provisioning
    # a fresh virtualenv per target costs about four seconds each, which is minutes across a suite.
    venv = Path(venv_dir).resolve() if venv_dir else root / "venv"
    # The host-shaped locations the privileged program mutates. Under the disposable root, and
    # NOT under app/ or releases/ — the target refuses to construct otherwise.
    host = root / "host"
    for directory in (app, releases, backups, state, privileged_dir, host):
        directory.mkdir(parents=True, exist_ok=True)
    if venv_dir is None:
        (venv / "bin").mkdir(parents=True, exist_ok=True)

    # Its own interpreter, reachable exactly the way the target says it is. A symlink rather than
    # a real virtualenv: building one per run would cost seconds for no property gained, and the
    # chain only ever invokes `<venv>/bin/python`.
    python_link = venv / "bin" / "python"
    if venv_dir is None and not python_link.exists():
        python_link.symlink_to(sys.executable)

    origin = root / "origin.git"
    _git(root, "init", "--bare", "--initial-branch=main", str(origin))

    _git(root, "init", "--initial-branch=main", str(app))
    for rel, content in _APP_FILES.items():
        _write(app, rel, content)
    _git(app, "add", "-A")
    _git(app, "commit", "-m", "disposable target: base revision")
    base_sha = _git(app, "rev-parse", "HEAD")

    _write(app, "orchestrator/tc_growth/version.py", f'VERSION = "{name}-2"\n')
    _git(app, "add", "-A")
    _git(app, "commit", "-m", "disposable target: the revision under deployment")
    target_sha = _git(app, "rev-parse", "HEAD")

    _git(app, "remote", "add", "origin", str(origin))
    _git(app, "push", "origin", "main")
    # The app checkout sits one commit BEHIND its remote, so `converge` has real work to do and
    # `preflight`'s ancestry check is answering a question rather than restating an assumption.
    _git(app, "reset", "--hard", base_sha)

    _write_privileged_standin(privileged_dir, state)

    SqliteStore(str(state / "store.db")).close()

    target = deploy_target.make_disposable_target(
        name=name,
        app_dir=str(app),
        releases_dir=str(releases),
        backup_dir=str(backups),
        db_path=str(state / "store.db"),
        venv=str(venv),
        service=f"tc-console-{name}",
        unit_prefix=f"tc-deploy-{name}",
        evidence_namespace=f"disposable/{name}",
        port="0",
        remote_ref="origin/main",
        privileged_prefix=str(privileged_dir / "lib"),
        runtime_dir=str(privileged_dir / "runtime"),
        unit_path=str(host / f"tc-console-{name}.service"),
        inspector_dest=str(host / "wp-integrity-scan.sh"),
        sudoers_file=str(host / f"sudoers-{name}"),
        snapshot_dir=str(host / "snapshots"),
        console_env_file=str(host / f"{name}.env"),
        service_user=_service_user(),
    )
    if privileged:
        # The interpreter is part of what the authorized SHA has to cover (review blocker 1): a
        # venv the service user can write is a way to change what executes without touching a
        # single application file. Production's answer is a root-owned venv; the disposable
        # target's is the same, made so here. `apply` refuses a writable one either way.
        # The installer provisions and locks a REAL root-owned venv (review blocker 3), so the
        # harness no longer fakes one. `python -m venv` needs the directory not to be a
        # half-built symlink farm, so the placeholder is cleared first.
        if venv_dir is None:
            shutil.rmtree(venv, ignore_errors=True)
        install_privileged(target, app, provision_venv=venv_dir is None)
    return Disposable(target=target, root=root, origin=origin, state_dir=state,
                      privileged_dir=privileged_dir, base_sha=base_sha, target_sha=target_sha,
                      privileged=privileged)


def _service_user() -> str:
    """The account the disposable deployment runs as.

    Production's is `tcgrowth`. The disposable target names whoever is actually running, because
    the sudoers drop-in the privileged program writes has to name a real account for `visudo -c`
    to validate it — and a rule naming a user who does not exist would validate nothing.
    """
    import pwd
    return pwd.getpwuid(os.getuid()).pw_name


def install_privileged(target: deploy_target.Target, app: Path, *,
                       provision_venv: bool = True) -> str:
    """Install the real root-owned privileged program for this target, and return the output.

    The `--source` directory is assembled rather than pointed at the repository, because the
    inspector root will authenticate against must be THE TARGET'S OWN reviewed inspector. For
    production that is the repo's; for the disposable target it is the one committed into the
    disposable application. Root's copy is taken here, at install time, from the reviewed source —
    and never again from the release.
    """
    with tempfile.TemporaryDirectory() as staging_str:
        staging = Path(staging_str)
        (staging / "lib").mkdir()
        shutil.copy2(REPO_SCRIPTS / "tc-deploy-privileged.sh", staging / "tc-deploy-privileged.sh")
        shutil.copy2(REPO_SCRIPTS / "lib" / "permission-guard.sh",
                     staging / "lib" / "permission-guard.sh")
        shutil.copy2(app / "orchestrator" / "scripts" / "wp-integrity-scan.sh",
                     staging / "wp-integrity-scan.sh")
        argv = [
            "bash", str(REPO_SCRIPTS / "install-tc-deploy.sh"),
            "--prefix", target.privileged_prefix,
            "--app-dir", target.app_dir,
            "--releases-dir", target.releases_dir,
            "--service", target.service,
            "--service-user", target.service_user,
            "--port", target.port or "8385",
            "--unit-path", target.unit_path,
            "--inspector-dest", target.inspector_dest,
            "--sudoers-file", target.sudoers_file,
            "--snapshot-dir", target.snapshot_dir,
            "--unit-prefix", target.unit_prefix,
            "--runtime-dir", target.runtime_dir,
            "--store-db", target.db_path,
            "--venv", target.venv,
            "--console-env-file", target.console_env_file,
            *(["--provision-venv", "--python", sys.executable,
               # The disposable app's suite needs pytest; on a real host root would install the
               # dependencies into this venv instead. Either way the interpreter stays root-owned.
               "--venv-system-site-packages"] if provision_venv else []),
            "--source", str(staging),
        ]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=300.0)
    if proc.returncode != 0:
        raise RuntimeError("installing the privileged program failed:\n"
                           + (proc.stdout or "") + (proc.stderr or ""))
    return (proc.stdout or "") + (proc.stderr or "")


def _write_privileged_standin(privileged_dir: Path, state_dir: Path) -> None:
    """The stand-in for the privileged host mutation that this increment does not implement.

    It lives OUTSIDE the target's application tree — the one structural property the real
    privileged program must have — and it does two things: record that the boundary was reached,
    and execute the release worktree's own script. The second is what makes a tampered release a
    real risk in this harness rather than a hypothetical one.
    """
    script = privileged_dir / "privileged-standin.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "# WP-U4d.1 STAND-IN — not the privileged program, and never installed on a real host.\n"
        "# It marks that the chain reached the point where root would act, then runs the release\n"
        "# worktree's script, so substituted release content would genuinely execute here.\n"
        "set -euo pipefail\n"
        f'state={json.dumps(str(state_dir))}\n'
        'release="$1"\n'
        f': > "$state/{PRIVILEGED_MARKER}"\n'
        'exec "$release/orchestrator/scripts/deploy-console.sh" --apply\n')
    script.chmod(0o755)


def teardown(disposable: Disposable) -> None:
    """Remove the target entirely. Worktrees are pruned first so the app repository does not keep
    administrative directories pointing at paths that no longer exist."""
    app = Path(disposable.target.app_dir)
    if app.is_dir():
        try:
            _git(app, "worktree", "prune")
        except RuntimeError:
            pass
    shutil.rmtree(disposable.root, ignore_errors=True)


# --------------------------------------------------------------------------- running the chain

def _privileged_standin_executor(disposable: Disposable):
    def ex_release_standin(sha: str, ctx: dict) -> deploy.StepResult:
        release = ctx.get("release_dir") or disposable.target.release_dir(sha)
        code, out = deploy._run(
            [str(disposable.privileged_dir / "privileged-standin.sh"), release],
            timeout=120.0, env=ctx.get("child_env"))
        if code != 0:
            return deploy.StepResult(False, "the privileged stand-in failed", out)
        return deploy.StepResult(True, f"privileged stand-in reached for {sha[:12]}", out)
    return ex_release_standin


def tamper_with_release(disposable: Disposable, *, sha: str | None = None) -> Path:
    """Stage the release worktree, then replace content in it AFTER checkout.

    This is PR #79 defect 2 made concrete. The worktree is a legitimate checkout of the reviewed
    commit — `git rev-parse HEAD` in it still answers with the right SHA, and its `.git` is
    writable by the same account — and a file in it has been replaced with a payload. Any check
    that asks the worktree about itself passes; only comparing its bytes against the committed
    objects notices.
    """
    sha = sha or disposable.target_sha
    release = disposable.release_path(sha)
    if not release.exists():
        _git(Path(disposable.target.app_dir), "worktree", "add", "--detach", str(release), sha)
    payload = release / "orchestrator" / "scripts" / "deploy-console.sh"
    payload.write_text(
        "#!/usr/bin/env bash\n"
        "# Substituted release content. If the chain ever executes this, the marker proves it.\n"
        f': > {json.dumps(str(disposable.state_dir / PAYLOAD_MARKER))}\n'
        'echo "payload executed"\n')
    payload.chmod(0o755)
    return payload


def substitute_inspector(disposable: Disposable) -> Path:
    """Replace the release's inspector with a payload, in place, after checkout.

    This is the file the PRIVILEGED program authenticates. Root compares it against its own
    root-owned copy and refuses on mismatch, and installs from its own copy regardless — so a
    substitution here can neither be installed nor executed.
    """
    victim = disposable.release_path() / "orchestrator" / "scripts" / "wp-integrity-scan.sh"
    victim.parent.mkdir(parents=True, exist_ok=True)
    victim.write_text(
        "#!/usr/bin/env bash\n"
        "# Substituted inspector. If root ever installs or runs THIS, the marker proves it.\n"
        f': > {json.dumps(str(disposable.state_dir / PAYLOAD_MARKER))}\n'
        'echo "payload executed"\n')
    victim.chmod(0o755)
    return victim


def substitute_application_module(disposable: Disposable) -> Path:
    """Replace an ORDINARY application module in the release, after checkout.

    Review blocker 1: pinning the inspector while the unit points into the release tree leaves the
    application itself mutable. This is the payload that matters — not a security artifact, just a
    normal module the service imports on every start. If it executes, the marker says so.
    """
    victim = disposable.release_path() / "orchestrator" / "tc_growth" / "cli.py"
    victim.parent.mkdir(parents=True, exist_ok=True)
    marker = json.dumps(str(disposable.state_dir / PAYLOAD_MARKER))
    victim.write_text(
        '"""Substituted application module."""\n'
        "import sys\n"
        f"open({marker}, 'w').close()\n"
        "print('payload executed')\n"
        "sys.exit(0)\n")
    return victim


def install_replace_ref(disposable: Disposable, sha: str | None = None) -> str:
    """Point `refs/replace/<sha>` at a commit whose tree carries the payload.

    This is the attack the reviewer named: git substitutes replaced objects TRANSPARENTLY, so
    `ls-tree`/`cat-file` return the attacker's tree while every command still names the authorized
    SHA. If root reads with replacement enabled, its "I authenticated this myself" is a statement
    about objects the adversary chose.

    Built with plumbing (`read-tree` into a scratch index, `write-tree`, `commit-tree`) so the
    working tree, HEAD and branches are all left exactly as the deployment expects them.
    """
    sha = sha or disposable.target_sha
    app = Path(disposable.target.app_dir)
    payload = ("import sys\n"
               f"open({json.dumps(str(disposable.state_dir / PAYLOAD_MARKER))}, 'w').close()\n"
               "print('payload executed')\nsys.exit(0)\n")

    blob = subprocess.run(["git", "-C", str(app), "hash-object", "-w", "--stdin"],
                          input=payload, capture_output=True, text=True, timeout=60,
                          check=True).stdout.strip()
    index = app / ".git" / "tc-harness-index"
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(app),
           "GIT_INDEX_FILE": str(index), "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "harness",
           "GIT_AUTHOR_EMAIL": "harness@invalid", "GIT_COMMITTER_NAME": "harness",
           "GIT_COMMITTER_EMAIL": "harness@invalid"}

    def git(*args, **kw):
        return subprocess.run(["git", "-C", str(app), *args], env=env, capture_output=True,
                              text=True, timeout=120, check=True, **kw).stdout.strip()

    git("read-tree", sha)
    git("update-index", "--add", "--cacheinfo",
        f"100644,{blob},orchestrator/tc_growth/cli.py")
    tree = git("write-tree")
    payload_commit = git("commit-tree", tree, "-m", "substituted via replace ref")
    git("replace", "-f", sha, payload_commit)
    index.unlink(missing_ok=True)
    return payload_commit


def _tamper_after_stage_executor(disposable: Disposable, what: str = "inspector"):
    """The TOCTOU window, made concrete and executed.

    `stage` verifies the release against the committed objects and returns ok. The release tree
    stays writable by the service account after that verdict, so this substitutes content in the
    gap between the unprivileged check passing and the privileged consumer acting. Root must not
    inherit the unprivileged half's confidence.
    """
    def ex_stage_then_tamper(sha: str, ctx: dict) -> deploy.StepResult:
        result = deploy.ex_stage(sha, ctx)
        if result.ok:
            (substitute_inspector if what == "inspector"
             else substitute_application_module)(disposable)
        return result
    return ex_stage_then_tamper


def teardown_release(disposable: Disposable, sha: str | None = None) -> None:
    """Remove a staged release worktree so a test can re-stage it cleanly. Used by the blocker-1
    control, which needs the same release both substituted and honest."""
    release = disposable.release_path(sha)
    if release.exists():
        shutil.rmtree(release, ignore_errors=True)
    try:
        _git(Path(disposable.target.app_dir), "worktree", "prune")
    except RuntimeError:
        pass


def run(disposable: Disposable, *, requested_by: str | None = None,
        tamper_after_stage: bool | str = False) -> dict:
    """Run the disposable chain end to end and return what actually happened.

    The report is assembled from the store and from the filesystem — the run's terminal status, the
    recorded steps, and whether each marker file exists — so a caller checks observed state rather
    than this function's opinion of it.
    """
    target = disposable.target
    store = SqliteStore(target.db_path)
    try:
        plan = deploy.build_plan(disposable.target_sha, current_sha=disposable.base_sha,
                                 target=target)
        run_id = store.plan_deploy(
            sha=disposable.target_sha, plan=plan, plan_digest=deploy.plan_digest(plan),
            requested_by=requested_by or f"harness:{target.evidence_namespace}")
        executors = dict(deploy.EXECUTORS)
        if not disposable.privileged:
            # Increment-1 mode: a labelled stand-in, which proves nothing about root. The report
            # carries `privileged_boundary: "stand-in"` so no reader can mistake the two.
            executors["release"] = _privileged_standin_executor(disposable)
        if tamper_after_stage:
            executors["stage"] = _tamper_after_stage_executor(
                disposable,
                tamper_after_stage if isinstance(tamper_after_stage, str) else "inspector")
        outcome = deploy.execute(store, run_id, context=deploy.context_for(target),
                                 executors=executors, steps=DISPOSABLE_STEPS)
        row = store.get_deploy_run(run_id)
        steps = store.list_deploy_steps(run_id)
    finally:
        store.close()
    return {
        "target": target.name,
        "evidence_namespace": target.evidence_namespace,
        "privileged_boundary": "real" if disposable.privileged else "stand-in",
        "installed_inspector_digest": _digest(target.inspector_dest),
        "root_owned_inspector_digest": _digest(
            os.path.join(target.privileged_prefix, "wp-integrity-scan.sh")),
        "run_id": run_id,
        "outcome": outcome,
        "status": row["status"],
        "terminal_message": row["outcome"],
        "steps_executed": [s["name"] for s in steps if s["status"] in ("ok", "failed")],
        "steps_declared": [s.name for s in DISPOSABLE_STEPS],
        "step_records": [{"name": s["name"], "status": s["status"], "summary": s["summary"]}
                         for s in steps],
        "privileged_mutation_reached": disposable.privileged_marker.exists(),
        "payload_executed": disposable.payload_marker.exists(),
    }


def _digest(path: str) -> str | None:
    """sha256 of a file, or None if it is not there. Used to show, in the report itself, that what
    root installed is root's own copy rather than whatever the release contained."""
    import hashlib
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def report_text(report: dict) -> str:
    """The report as lines an operator reads, including the two markers — which are the whole
    point and must not be something you have to go looking for."""
    lines = [
        f"target ................. {report['target']}  ({report['evidence_namespace']})",
        f"privileged boundary .... {report['privileged_boundary']}",
        f"deploy run ............. #{report['run_id']}",
        f"terminal status ........ {report['status'].upper()}",
        f"terminal message ....... {report['terminal_message']}",
        "",
        "steps, as recorded:",
    ]
    for step in report["step_records"]:
        if step["status"] in ("ok", "failed"):
            lines.append(f"  [{step['status']:<6}] {step['name']:<10} {step['summary']}")
    installed, owned = report["installed_inspector_digest"], report["root_owned_inspector_digest"]
    # The stand-in's marker is meaningless once the real boundary is in play — root does not write
    # it — and printing "no" there would read as "root never acted", which would be false.
    reached = ("n/a — the real privileged program was used, not the stand-in"
               if report["privileged_boundary"] == "real"
               else "YES" if report["privileged_mutation_reached"] else "no")
    lines += [
        "",
        f"privileged mutation reached ... {reached}",
        f"substituted payload executed .. {'YES' if report['payload_executed'] else 'no'}",
        f"inspector root installed ...... {installed[:12] if installed else 'NOT INSTALLED'}",
        f"inspector root owns ........... {owned[:12] if owned else 'not installed'}"
        + ("   (same bytes — installed from root's own copy)" if installed and installed == owned
           else "   (DIFFER)" if installed and owned else ""),
        "",
        "steps not part of the disposable chain: "
        + ", ".join(s.name for s in deploy.STEPS if s.name not in report["steps_declared"])
        + " (no Console serves the disposable target)",
    ]
    return "\n".join(lines)
