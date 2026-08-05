"""WP-U4d.1 — the bounded VPS acceptance run (PR #80).

One command, so the owner never assembles plan rows, permissions, services or failure injection by
hand. The previous runbook asked them to do exactly that and review found five defects in it —
three of which existed only because the steps were manual.

What this command is, and is not
--------------------------------
It adds **no privilege**. It composes verbs the privileged program already exposes — `bootstrap`,
`apply`, `start-run`, `rollback` — and the sudoers surface is unchanged. The escalation surface
after this file exists is identical to the surface before it.

The order matters and is not negotiable:

1. **Refuse before mutating.** `assert_nothing_production` resolves every value the run will touch
   and refuses if any of them is production's. It runs before a single directory is created,
   because a guard that fires after provisioning has already done the thing it was meant to stop.
2. **Split ownership the way production splits it.** The unprivileged trees — app, releases, store,
   backups — belong to the service account. The privileged prefix, runtime, snapshots and host
   artifacts belong to root. A probe where root owns everything would either fail for irrelevant
   reasons or prove less than production needs.
3. Then, and only then, provision, bootstrap, deploy, fail, roll back and tear down.

What this command cannot do, on any machine without a booted service manager
----------------------------------------------------------------------------
Transient-unit creation, `daemon-reload`, restart survival, loopback health and durable Evidence
across a restart. Those phases report `unavailable`, the report records them as **not executed**,
and no summary line claims them. They are the VPS gate, and they are the reason this command's
report distinguishes `executed` from `deferred` rather than printing a single pass/fail.
"""

from __future__ import annotations

import json
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

from . import deploy, deploy_harness, deploy_target
from .store.sqlite import SqliteStore

#: Everything a disposable run must never resolve to. Substring matching on purpose: a probe that
#: merely *contains* a production path is as dangerous as one that equals it.
PRODUCTION_MARKERS = (
    "/opt/tc_ai_growth/app",
    "/opt/tc_ai_growth/releases",
    "/etc/systemd/system/tc-console.service",
    "/etc/sudoers.d/tc-console-scan",
    "/usr/local/lib/tc-deploy",
    "/usr/local/bin/wp-integrity-scan.sh",
    "/var/backups/tc-console",
)


class AcceptanceRefused(RuntimeError):
    """The run refused to start. Distinct from a deployment failure: nothing has been mutated."""


#: The complete phase vocabulary, in execution order. The Console-driven acceptance (WP-U4d.2)
#: reads these same names for its durable evidence and its verdict — a second list would be a
#: second implementation path, drifting the moment either changed.
PHASE_ORDER = (
    "preflight-refuses-production",
    "ownership-split",
    "install-and-self-check",
    "bootstrap",
    "target-bound-plan",
    "transient-unit",
    "apply-file-phases",
    "daemon-reload",
    "restart-service",
    "health-check",
    "import-origin",
    "failure-injection",
    "rollback-file-semantics",
    "rollback-service-action",
    "evidence-dump",
    "teardown-and-production-check",
)

#: The phases that need a booted service manager. Without one they are recorded `deferred`,
#: and a deferred phase is never success — the verdict logic in `acceptance_run` degrades it
#: to BLOCKED.
SYSTEMD_PHASES = (
    "transient-unit",
    "daemon-reload",
    "restart-service",
    "health-check",
    "failure-injection",
    "rollback-service-action",
)


def assert_nothing_production(target: deploy_target.Target) -> list[str]:
    """Fail closed before any mutation if the run would touch production.

    Checked on the RESOLVED values rather than on the arguments, because the danger is a default
    leaking through — which is exactly the defect the last review found in the runbook, where every
    shell value said "probe" and Python still resolved production.
    """
    resolved = {
        "app_dir": target.app_dir, "releases_dir": target.releases_dir,
        "backup_dir": target.backup_dir, "db_path": target.db_path, "venv": target.venv,
        "privileged_prefix": target.privileged_prefix, "runtime_dir": target.runtime_dir,
        "unit_path": target.unit_path, "inspector_dest": target.inspector_dest,
        "sudoers_file": target.sudoers_file, "snapshot_dir": target.snapshot_dir,
        "console_env_file": target.console_env_file,
    }
    problems = []
    if not target.disposable:
        problems.append("the target is not disposable")
    if target.service == deploy_target.PRODUCTION.service:
        problems.append(f"service is production's ({target.service})")
    if target.unit_prefix == deploy_target.PRODUCTION.unit_prefix:
        problems.append(f"unit prefix is production's ({target.unit_prefix})")
    if target.port == deploy_target.PRODUCTION.port:
        problems.append(f"port is production's ({target.port})")
    if not target.evidence_namespace.startswith("disposable/"):
        problems.append(f"evidence namespace is not disposable ({target.evidence_namespace})")
    for field, value in resolved.items():
        for marker in PRODUCTION_MARKERS:
            if value == marker or value.startswith(marker + "/") or marker in value:
                problems.append(f"{field} resolves into production: {value}")
    if problems:
        raise AcceptanceRefused(
            "refusing to start: this run would touch production.\n  - " + "\n  - ".join(problems))
    return sorted(resolved)


# --------------------------------------------------------------------------- ownership

def resolve_service_account() -> str:
    """Which account the unprivileged half will run as. READ ONLY — creates nothing.

    Split from `ensure_service_account` because `useradd` is a host mutation, and the production
    guard has to be able to refuse before any mutation including that one.
    """
    for candidate in ("tcgrowth", "tcgrowth-probe"):
        try:
            pwd.getpwnam(candidate)
            return candidate
        except KeyError:
            continue
    return "tcgrowth-probe"


def ensure_service_account(account: str) -> None:
    """Create the account if it is missing. The first mutation the run performs."""
    try:
        pwd.getpwnam(account)
    except KeyError:
        subprocess.run(["useradd", "-M", "-s", "/usr/sbin/nologin", account],
                       capture_output=True, timeout=120)


#: The only parent an acceptance root may live under without further argument. Fixed, so the
#: command cannot be pointed at a home directory whose ancestors would need loosening.
SAFE_ACCEPTANCE_PARENT = "/srv/tc-u4d-acceptance"


def assert_acceptance_root(root: Path) -> list[str]:
    """The root must be usable WITHOUT changing any mode outside it.

    The previous version walked from the supplied root to `/` adding `o+x` to every ancestor that
    lacked it. That is a host permission mutation outside the disposable tree, on a path the owner
    supplied — under a private home directory it would have quietly widened traversal to somebody's
    files. A security acceptance run does not get to do that.

    So this CHECKS and refuses, naming the directory and the one command that fixes it. A root
    under the fixed safe parent needs nothing; anywhere else has to already be traversable.
    """
    root = Path(root).resolve()
    if str(root).startswith(SAFE_ACCEPTANCE_PARENT + "/") or str(root) == SAFE_ACCEPTANCE_PARENT:
        return []
    blocking = []
    current = root.parent if root.exists() else root.parent
    while current != current.parent:
        if current.exists() and not current.stat().st_mode & 0o001:
            blocking.append(str(current))
        current = current.parent
    if blocking:
        raise AcceptanceRefused(
            "the service account could not traverse to the acceptance root, and this command will "
            "NOT loosen directories outside its own tree.\n"
            "  not traversable: " + ", ".join(blocking) + "\n"
            f"  either use a root under {SAFE_ACCEPTANCE_PARENT}/<run-id>, or make those "
            "directories traversable yourself (chmod o+x) if that is what you intend.")
    return []


def apply_ownership_split(target: deploy_target.Target, account: str) -> dict:
    """Give the unprivileged trees to the service account and keep the rest root's.

    Production runs the executors as `tcgrowth` against trees that account owns. A probe where root
    owns everything runs with more authority than the thing being modelled, and would hide exactly
    the permission problems the real deployment has to survive.
    """
    entry = pwd.getpwnam(account)
    # The bare remote belongs to the unprivileged half too — `preflight` fetches from it and the
    # acceptance run pushes to it. Missing it produced a dubious-ownership failure that looked like
    # a deployment bug and was a setup bug.
    origin = os.path.join(os.path.dirname(target.app_dir), "origin.git")
    for path in (target.app_dir, target.releases_dir, target.backup_dir,
                 os.path.dirname(target.db_path), origin):
        if not os.path.exists(path):
            continue
        subprocess.run(["chown", "-R", f"{entry.pw_uid}:{entry.pw_gid}", path],
                       capture_output=True, timeout=300)
    if os.path.exists(target.db_path):
        os.chown(target.db_path, entry.pw_uid, entry.pw_gid)
    return verify_ownership_split(target, account)


def verify_ownership_split(target: deploy_target.Target, account: str) -> dict:
    """Read the split back off disk. Printed before mutation so it is a fact, not an intention."""
    entry = pwd.getpwnam(account)
    observed = {}
    for label, path, expected in (
            ("app_dir", target.app_dir, account),
            ("releases_dir", target.releases_dir, account),
            ("backup_dir", target.backup_dir, account),
            ("store_dir", os.path.dirname(target.db_path), account),
            ("privileged_prefix", target.privileged_prefix, "root"),
            ("runtime_dir", target.runtime_dir, "root"),
            ("snapshot_dir", target.snapshot_dir, "root"),
            ("venv", target.venv, "root")):
        if not os.path.exists(path):
            observed[label] = {"path": path, "owner": None, "expected": expected, "ok": None}
            continue
        uid = os.stat(path).st_uid
        owner = pwd.getpwuid(uid).pw_name if uid in (0, entry.pw_uid) else str(uid)
        observed[label] = {"path": path, "owner": owner, "expected": expected,
                           "ok": owner == expected}
    return observed


# --------------------------------------------------------------------------- the failing release

FAILING_APP = (
    '"""A release whose Console exits immediately. The failure lives in the COMMITTED CONTENT,\n'
    "so it survives root regenerating the unit from its own config — the previous runbook's\n"
    "injection edited the unit and `apply` simply rewrote it away.\"\"\"\n"
    "import sys\n"
    "print('disposable console: failing on purpose', file=sys.stderr)\n"
    "sys.exit(1)\n"
)


def git_as(account: str, app: Path, *args: str) -> str:
    """Run git in the probe checkout AS THE SERVICE ACCOUNT.

    The ownership split is the point: the checkout belongs to the unprivileged half, so root
    running git in it is both wrong and — since git's dubious-ownership guard — broken. Doing it
    as the account is what production does, and it is how this command found that root's own
    read needed an explicit, scoped `safe.directory`.
    """
    entry = pwd.getpwnam(account)
    proc = subprocess.run(
        ["setpriv", f"--reuid={entry.pw_uid}", f"--regid={entry.pw_gid}", "--clear-groups",
         "git", "-C", str(app), *args],
        capture_output=True, text=True, timeout=300,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(app),
             "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
             "GIT_AUTHOR_NAME": "acceptance", "GIT_AUTHOR_EMAIL": "acceptance@invalid",
             "GIT_COMMITTER_NAME": "acceptance", "GIT_COMMITTER_EMAIL": "acceptance@invalid"})
    if proc.returncode != 0:
        raise AcceptanceRefused(f"git {' '.join(args)} failed as {account}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def commit_failing_release(disposable: deploy_harness.Disposable, account: str) -> str:
    """A second commit whose application fails after start. Returns its SHA."""
    app = Path(disposable.target.app_dir)
    # The harness leaves the checkout one commit BEHIND its remote so `converge` has real work.
    # Committing from there diverges from origin/main and the push is rejected — and `preflight`
    # would later refuse the SHA for not being an ancestor of the remote, correctly.
    git_as(account, app, "reset", "--hard", disposable.target_sha)
    victim = app / "orchestrator" / "tc_growth" / "console_entry.py"
    victim.write_text(FAILING_APP)
    entry = pwd.getpwnam(account)
    os.chown(victim, entry.pw_uid, entry.pw_gid)
    git_as(account, app, "add", "-A")
    git_as(account, app, "commit", "-m", "release that fails after start")
    head = git_as(account, app, "rev-parse", "HEAD")
    git_as(account, app, "push", "origin", "HEAD:main")
    return head


# --------------------------------------------------------------------------- the run

def _verb(target: deploy_target.Target, *argv: str) -> dict:
    proc = subprocess.run([target.privileged_entry, *argv], capture_output=True, text=True,
                          timeout=900.0)
    return {"argv": list(argv), "exit": proc.returncode,
            "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}


def systemd_is_booted() -> bool:
    return Path("/run/systemd/system").is_dir()


def run(root: Path, *, keep: bool = False, progress=None) -> dict:
    """The whole acceptance, as one call. Returns a structured report; raises only on refusal.

    `progress`, when given, is called as `progress(name, status, detail)` the moment each phase
    lands — status is `ok` or `deferred`, names come from PHASE_ORDER. It exists because a
    mid-run exception discards the report dict: a durable consumer (the Console-driven
    acceptance) must receive each phase as it happens, not hope the dict survives to the end.
    """
    if os.geteuid() != 0:
        raise AcceptanceRefused("this acceptance run installs root-owned machinery; run it as root")

    # ---------------------------------------------------------------- PURE RESOLUTION PHASE
    #
    # Nothing below this comment touches the host until the guard has passed. The previous version
    # called `build()` first and then checked — so the module said "refuses before a single
    # directory is created" while the code created directories, a git repository and a store
    # before looking. That is the explanation-ahead-of-implementation failure this work package
    # exists to end, in my own file.
    booted = systemd_is_booted()
    root = Path(root)
    deploy_target._reset_for_tests()
    deploy_target.open_cli_target_gate()
    try:
        target = deploy_harness.resolve_target(root, name="vpsprobe")
    finally:
        deploy_target.close_cli_target_gate()

    checked = assert_nothing_production(target)      # refuses; creates nothing
    assert_acceptance_root(root)                     # refuses; changes no mode
    account = resolve_service_account()              # reads; creates no account

    report: dict = {"service_account": account, "systemd_booted": booted,
                    "executed": [], "deferred": [], "steps": {},
                    "target_name": target.evidence_namespace, "target_sha": ""}

    def mark(name: str, *, needs_systemd: bool = False, detail: str = "") -> None:
        deferred = needs_systemd and not booted
        (report["deferred"] if deferred else report["executed"]).append(name)
        if progress is not None:
            progress(name, "deferred" if deferred else "ok", detail)

    report["steps"]["preflight"] = {"checked": checked, "root": str(root.resolve()),
                                    "resolved_before_any_mutation": True}
    mark("preflight-refuses-production")

    # ---------------------------------------------------------------- MUTATION BEGINS HERE
    ensure_service_account(account)
    deploy_target._reset_for_tests()
    deploy_target.open_cli_target_gate()
    try:
        disposable = deploy_harness.build(root, name="vpsprobe", privileged=False)
    finally:
        deploy_target.close_cli_target_gate()
    report["target_sha"] = disposable.target_sha
    # The thing built must be the thing approved. `build` uses the same resolver, so this is a
    # regression guard rather than a real possibility — which is exactly when they are cheap.
    if disposable.target != target:
        raise AcceptanceRefused("the materialised target differs from the approved one")

    report["steps"]["ownership"] = apply_ownership_split(target, account)
    mark("ownership-split")

    # 3. Install the privileged machinery for this target.
    deploy_target.open_cli_target_gate()
    try:
        report["steps"]["install"] = deploy_harness.install_privileged(
            target, Path(target.app_dir), provision_venv=True)
    finally:
        deploy_target.close_cli_target_gate()
    report["steps"]["ownership_after_install"] = verify_ownership_split(target, account)
    # install_privileged raises on a non-zero installer exit, so reaching here means the
    # installed program passed its own self-check.
    mark("install-and-self-check", detail="installer ran the installed program's self-check")

    # 4. Bootstrap the trusted runner runtime — the fresh-host path.
    git_as(account, Path(target.app_dir), "worktree", "add", "--detach",
           target.release_dir(disposable.target_sha), disposable.target_sha)
    report["steps"]["bootstrap"] = _verb(target, "bootstrap", disposable.target_sha)
    mark("bootstrap", detail=f"exit={report['steps']['bootstrap']['exit']}")

    # 5. A target-bound plan and run row — never a production plan.
    store = SqliteStore(target.db_path)
    try:
        plan = deploy.build_plan(disposable.target_sha, target=target)
        run_id = store.plan_deploy(sha=disposable.target_sha, plan=plan,
                                   plan_digest=deploy.plan_digest(plan),
                                   requested_by=f"acceptance:{target.evidence_namespace}")
    finally:
        store.close()
    report["steps"]["plan"] = {"run_id": run_id, "plan_target": plan["target"],
                               "repository": plan["repository"], "service": plan["service"]}
    mark("target-bound-plan", detail=f"run #{run_id} on {plan['target']}")

    # 6. The transient path.
    report["steps"]["start_run"] = _verb(target, "start-run", str(run_id))
    mark("transient-unit", needs_systemd=True,
         detail=f"exit={report['steps']['start_run']['exit']}")

    # 7. apply, and the import origin under the exact service command.
    report["steps"]["apply"] = _verb(target, "apply", disposable.target_sha)
    mark("apply-file-phases", detail=f"exit={report['steps']['apply']['exit']}")
    for phase in ("daemon-reload", "restart-service", "health-check"):
        mark(phase, needs_systemd=True)
    report["steps"]["import_origin"] = _import_origin(target, disposable.target_sha)
    mark("import-origin")

    # 8. A real failure, injected into committed content so unit regeneration cannot remove it.
    failing = commit_failing_release(disposable, account)
    git_as(account, Path(target.app_dir), "worktree", "add", "--detach",
           target.release_dir(failing), failing)
    report["steps"]["failing_release"] = {"sha": failing,
                                          "result": _verb(target, "apply", failing)}
    mark("failure-injection", needs_systemd=True,
         detail=f"exit={report['steps']['failing_release']['result']['exit']}")

    # 9. Rollback, and the per-artifact prior state.
    report["steps"]["rollback"] = _verb(target, "rollback")
    report["steps"]["artifacts_after_rollback"] = {
        name: os.path.exists(path) for name, path in (
            ("unit", target.unit_path), ("inspector", target.inspector_dest),
            ("sudoers", target.sudoers_file),
            ("current", os.path.join(target.snapshot_dir, "current")))}
    mark("rollback-file-semantics", detail=f"exit={report['steps']['rollback']['exit']}")
    mark("rollback-service-action", needs_systemd=True)

    # 10. Evidence, in full, for the by-eye read.
    report["steps"]["evidence"] = _evidence(target)
    mark("evidence-dump")
    # Re-read the split at the END, when the runtime and snapshot trees actually exist. Reporting
    # them as "absent" from a check taken before they were created would understate the run.
    report["steps"]["ownership_final"] = verify_ownership_split(target, account)

    # 11. Teardown, and proof that production is where it was.
    report["steps"]["production_untouched"] = production_untouched()
    if not keep:
        deploy_harness.teardown(disposable)
        report["steps"]["teardown"] = {"removed": str(root), "exists": Path(root).exists()}
    # production_untouched RECORDS the observed state rather than judging it (a real production
    # install legitimately exists on the VPS); the by-eye read and the report carry the verdict.
    mark("teardown-and-production-check", detail="production state recorded for the by-eye read")
    deploy_target._reset_for_tests()
    return report


def _import_origin(target: deploy_target.Target, sha: str) -> dict:
    runtime = Path(target.runtime_dir) / sha
    probe = ("import json, sys, tc_growth; "
             "print(json.dumps({'origin': tc_growth.__file__, "
             "'mutable': [p for p in sys.path if p.startswith(sys.argv[1]) "
             "or p.startswith(sys.argv[2])]}))")
    try:
        out = subprocess.run([f"{target.venv}/bin/python", "-c", probe, target.app_dir,
                              target.releases_dir], cwd=str(runtime / "orchestrator"),
                             capture_output=True, text=True, timeout=120, check=True).stdout
        return json.loads(out)
    except Exception as exc:  # noqa: BLE001 - a failed probe is a RESULT to record
        return {"error": f"{type(exc).__name__}: {exc}"}


def _evidence(target: deploy_target.Target) -> dict:
    store = SqliteStore(target.db_path)
    try:
        runs = store.list_deploy_runs(limit=20)
        return {"runs": [dict(r) for r in runs],
                "steps": {r["id"]: [dict(s) for s in store.list_deploy_steps(r["id"])]
                          for r in runs}}
    finally:
        store.close()


def production_untouched() -> dict:
    """Nothing about production may have changed. Recorded rather than assumed."""
    observed = {}
    for label, path in (("app", deploy_target.PRODUCTION.app_dir),
                        ("releases", deploy_target.PRODUCTION.releases_dir),
                        ("unit", deploy_target.PRODUCTION.unit_path),
                        ("sudoers", deploy_target.PRODUCTION.sudoers_file),
                        ("prefix", deploy_target.PRODUCTION.privileged_prefix),
                        ("inspector", deploy_target.PRODUCTION.inspector_dest),
                        ("store", deploy_target.PRODUCTION.db_path)):
        observed[label] = {"path": path, "exists": os.path.exists(path)}
    if systemd_is_booted():
        state = subprocess.run(["systemctl", "is-active", deploy_target.PRODUCTION.service],
                               capture_output=True, text=True, timeout=60).stdout.strip()
        observed["service_state"] = {"service": deploy_target.PRODUCTION.service, "state": state}
    return observed


def secret_scan(report: dict, needles: tuple[str, ...]) -> dict:
    """Criterion 6's mechanical half. It does NOT replace reading the evidence — it catches what a
    reader might skim past, and the report still has to be read."""
    blob = json.dumps(report, default=str)
    return {needle: (needle in blob) for needle in needles}


def report_text(report: dict) -> str:
    lines = [
        f"service account ........ {report['service_account']}",
        f"systemd booted ......... {'YES' if report['systemd_booted'] else 'NO'}",
        "",
        "EXECUTED (" + str(len(report["executed"])) + "):",
    ]
    lines += [f"  ok       {name}" for name in report["executed"]]
    if report["deferred"]:
        lines += ["", "NOT EXECUTED — needs a booted service manager ("
                  + str(len(report["deferred"])) + "):"]
        lines += [f"  deferred {name}" for name in report["deferred"]]
    own = (report["steps"].get("ownership_final")
           or report["steps"].get("ownership_after_install")
           or report["steps"].get("ownership", {}))
    lines += ["", "ownership split:"]
    for label, info in own.items():
        mark = {True: "ok ", False: "BAD", None: "-  "}[info["ok"]]
        lines.append(f"  [{mark}] {label:<20} {info['owner'] or 'absent':<16} "
                     f"(expected {info['expected']})")
    plan = report["steps"].get("plan", {})
    lines += ["", f"plan target ............ {plan.get('plan_target')}",
              f"plan repository ........ {plan.get('repository')}",
              f"deploy run ............. #{plan.get('run_id')}"]
    origin = report["steps"].get("import_origin", {})
    lines += ["", f"tc_growth origin ....... {origin.get('origin', origin.get('error'))}",
              f"sys.path in app/releases {origin.get('mutable')}"]
    # The rollback's OWN per-artifact verdict, not just whether files exist. "present=True" alone
    # cannot distinguish a correct restore from a failed removal, and those are opposite outcomes.
    rb = report["steps"].get("rollback", {}).get("stdout", "")
    lines += ["", "rollback, per artifact:"]
    lines += [f"  {ln.strip()}" for ln in rb.splitlines()
              if "rollback-" in ln or "service-action" in ln or "status=complete" in ln
              or "status=partial" in ln]
    art = report["steps"].get("artifacts_after_rollback", {})
    lines += ["  files afterwards: " + ", ".join(f"{k}={'present' if v else 'absent'}"
                                                 for k, v in art.items())]
    lines += ["  (a second apply snapshots a PRESENT prior state, so restore — not removal — is",
              "   the correct outcome there; the per-artifact lines above say which happened.)"]
    prod = report["steps"].get("production_untouched", {})
    lines += ["", "production, after the whole run:"]
    for label, info in prod.items():
        if label == "service_state":
            lines.append(f"  {label:<12} {info['service']} is {info['state']}")
        else:
            lines.append(f"  {label:<12} exists={info['exists']}  {info['path']}")
    return "\n".join(lines)
