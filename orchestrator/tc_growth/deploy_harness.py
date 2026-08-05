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
}

_EXECUTABLE = {"orchestrator/scripts/deploy-console.sh"}


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


def build(root: Path, *, name: str = "disposable") -> Disposable:
    """Create a complete, isolated deployment target under `root`.

    Requires the command-line target gate to be open — that is the seam, and the harness is
    subject to it like everything else rather than being exempt from it.
    """
    root = Path(root).resolve()
    app, releases, backups = root / "app", root / "releases", root / "backups"
    state, privileged, venv = root / "state", root / "privileged", root / "venv"
    for directory in (app, releases, backups, state, privileged, venv / "bin"):
        directory.mkdir(parents=True, exist_ok=True)

    # Its own interpreter, reachable exactly the way the target says it is. A symlink rather than
    # a real virtualenv: building one per run would cost seconds for no property gained, and the
    # chain only ever invokes `<venv>/bin/python`.
    python_link = venv / "bin" / "python"
    if not python_link.exists():
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

    _write_privileged_standin(privileged, state)

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
    )
    return Disposable(target=target, root=root, origin=origin, state_dir=state,
                      privileged_dir=privileged, base_sha=base_sha, target_sha=target_sha)


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


def run(disposable: Disposable, *, requested_by: str | None = None) -> dict:
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
        executors["release"] = _privileged_standin_executor(disposable)
        outcome = deploy.execute(store, run_id, context=deploy.context_for(target),
                                 executors=executors, steps=DISPOSABLE_STEPS)
        row = store.get_deploy_run(run_id)
        steps = store.list_deploy_steps(run_id)
    finally:
        store.close()
    return {
        "target": target.name,
        "evidence_namespace": target.evidence_namespace,
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


def report_text(report: dict) -> str:
    """The report as lines an operator reads, including the two markers — which are the whole
    point and must not be something you have to go looking for."""
    lines = [
        f"target ................. {report['target']}  ({report['evidence_namespace']})",
        f"deploy run ............. #{report['run_id']}",
        f"terminal status ........ {report['status'].upper()}",
        f"terminal message ....... {report['terminal_message']}",
        "",
        "steps, as recorded:",
    ]
    for step in report["step_records"]:
        if step["status"] in ("ok", "failed"):
            lines.append(f"  [{step['status']:<6}] {step['name']:<10} {step['summary']}")
    lines += [
        "",
        f"privileged mutation reached ... {'YES' if report['privileged_mutation_reached'] else 'no'}",
        f"substituted payload executed .. {'YES' if report['payload_executed'] else 'no'}",
        "",
        "steps not part of the disposable chain: "
        + ", ".join(s.name for s in deploy.STEPS if s.name not in report["steps_declared"])
        + " (no Console serves the disposable target)",
    ]
    return "\n".join(lines)
