"""WP-U4d — the governed deployment runner (issue #77, Decision 2).

The platform deploys itself through ONE narrowly-defined operation the owner clicks, never
through a shell and never through a remote identity. Three properties carry the whole design:

**The authorization is a row, not an argument.** `plan_deploy` writes the exact 40-hex target
SHA and the plan the owner is about to read. `start_deploy` will only run a target that already
exists as a `planned` row whose plan digest matches what was displayed. A SHA that nobody
planned cannot be deployed, however it arrives — there is no code path that takes a commit from
a request and runs it.

**The runner is detached on purpose.** Phase 4 of the deploy restarts `tc-console` — the very
process a naive implementation would be running inside. It would kill itself mid-deploy and the
outcome would never be recorded. So the Console *spawns* the runner and then only *observes* it:
the runner is `setsid`-detached, writes every step to the shared store itself, and survives the
restart. After the Console comes back it reconnects to the same run by id and shows the terminal
result. Evidence therefore does not depend on the web process staying alive.

**Nothing here composes a command.** `EXECUTORS` is a closed table of fixed argv builders keyed
by step name. The only value that ever varies is the SHA, and it is validated as 40 lowercase
hex characters before it reaches any of them. There is no string interpolation into a shell, no
`shell=True`, and no argument that originates in an HTTP request.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

# --------------------------------------------------------------------------- closed allowlists

SHA_RE = re.compile(r"^[0-9a-f]{40}$")

#: The only repository this runner will ever touch, and the only paths it may write.
APP_DIR = "/opt/tc_ai_growth/app"
RELEASES_DIR = "/opt/tc_ai_growth/releases"
SERVICE = "tc-console"
REMOTE_REF = "origin/main"

#: Fixed deployment surface. Anything outside these is refused before a process is spawned —
#: the check is on the value, not on the caller's good intentions.
ALLOWED_PATHS = (APP_DIR, RELEASES_DIR)
ALLOWED_SERVICES = (SERVICE,)

#: Secrets never reach Evidence. Redaction is by PATTERN, not by remembering to omit things:
#: anything shaped like an assignment to a sensitive name is masked wherever it appears.
_SECRET_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|KEY|CREDENTIAL)[A-Z0-9_]*)\s*[=:]\s*\S+")
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")


def redact(text: str) -> str:
    """Mask secret-shaped values. Applied to EVERY summary and detail before it is stored, so a
    step that accidentally echoes an env line cannot leak it into the durable record."""
    if not text:
        return text
    out = _SECRET_RE.sub(lambda m: f"{m.group(1)}=***redacted***", text)
    out = _BEARER_RE.sub(lambda m: f"{m.group(1)} ***redacted***", out)
    # Absolute paths are fine, but the token file's CONTENTS must never be echoed wholesale.
    return out


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class DeployRefused(ValueError):
    """A request that policy refuses. Distinct from a defect: refusals are expected and are
    reported to the owner in their own words. Anything unexpected must raise something else, so
    a bug can never be presented as policy (the U4c lesson, applied here from the start)."""


def validate_sha(sha: str) -> str:
    """Exact 40-hex or nothing. Short SHAs, refs, branch names and `HEAD` are all refused: a
    deployment target must be unambiguous and must mean the same thing tomorrow."""
    s = (sha or "").strip()
    if not SHA_RE.match(s):
        raise DeployRefused(
            "the deployment target must be an exact 40-character commit SHA in lowercase hex; "
            "branch names, short SHAs and refs are refused because they can change meaning")
    return s


def release_dir(sha: str) -> str:
    return f"{RELEASES_DIR}/{validate_sha(sha)}"


def _assert_allowed_path(path: str) -> str:
    """A path must sit inside the allowlist, after normalization. `..` cannot walk out."""
    norm = os.path.normpath(path)
    for root in ALLOWED_PATHS:
        if norm == root or norm.startswith(root + "/"):
            return norm
    raise DeployRefused(f"path outside the deployment allowlist: {path}")


def _assert_allowed_service(name: str) -> str:
    if name not in ALLOWED_SERVICES:
        raise DeployRefused(f"service outside the deployment allowlist: {name}")
    return name


# --------------------------------------------------------------------------- the plan

@dataclass(frozen=True)
class Step:
    name: str
    title: str
    reversible: bool
    detail: str


#: The deployment, as data. Order is load-bearing and enforced by position: the backup is
#: VERIFIED before anything migrates, and the migration runs from the converged app checkout
#: before the Console release, because both open the same store.
STEPS: tuple[Step, ...] = (
    Step("preflight", "Verify the target is a reviewed commit on origin/main", True,
         "Fetches origin/main and refuses unless the exact SHA is an ancestor of it. A commit "
         "that is not on the reviewed line cannot be deployed."),
    Step("backup", "Back up the evidence store and VERIFY the copy", True,
         "sqlite .backup of the shared store, then the copy is proven two ways: SQLite's own "
         "PRAGMA integrity_check, and a full content digest of every row in every table compared "
         "against the source. Equal row counts are NOT accepted as proof. A copy that cannot be "
         "proven faithful is treated as no backup at all and stops the deployment."),
    Step("converge", "Fast-forward the app checkout to the target commit", False,
         "git merge --ff-only to the exact SHA, as the tcgrowth user. Reversible only by "
         "deploying the previous SHA — recorded as irreversible so it is never a surprise."),
    Step("suite", "Run the full test suite on the VPS", True,
         "Any failure stops the deployment here, before the store is migrated."),
    Step("migrate", "Migrate the shared store from the converged checkout", False,
         "db-init. Schema migrations are additive but NOT undoable; the verified backup from "
         "step 2 is the recovery path."),
    Step("release", "Create the release worktree and deploy the Console", False,
         "Detached worktree at releases/<sha>, then deploy-console.sh --apply. Reversible via "
         "the script's own --rollback, which restores the previous unit, inspector and sudoers."),
    Step("health", "Check the Console answers on loopback", True,
         "HTTP 200 from 127.0.0.1 on the service port, and the running unit pins the target SHA."),
)

IRREVERSIBLE = tuple(s.name for s in STEPS if not s.reversible)


def build_plan(sha: str, *, current_sha: str | None = None) -> dict:
    """The plan the owner reviews BEFORE authorizing. It names the target, the fixed paths and
    service, every step in order, and — separately and prominently — which steps cannot be
    undone. `plan_digest` binds the authorization to exactly this text."""
    sha = validate_sha(sha)
    plan = {
        "target_sha": sha,
        "current_sha": current_sha,
        "repository": APP_DIR,
        "release_dir": release_dir(sha),
        "service": SERVICE,
        "remote_ref": REMOTE_REF,
        "touches_production_wordpress": False,
        "steps": [{"name": s.name, "title": s.title, "reversible": s.reversible,
                   "detail": s.detail} for s in STEPS],
        "irreversible_steps": list(IRREVERSIBLE),
        "stop_on_failure": True,
        "rollback": "scripts/deploy-console.sh --rollback restores the previous unit, inspector "
                    "and sudoers state. The store is recovered from the step-2 backup, which is "
                    "proven by SQLite integrity_check AND a full row-content digest match — not "
                    "by row counts. A converged checkout is returned by deploying the previous "
                    "SHA.",
    }
    return plan


def plan_digest(plan: dict) -> str:
    """Canonical digest of the plan, so authorization binds to what was displayed — the same
    consent-binding discipline U4c uses for adopt-live."""
    blob = json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- the executors

@dataclass
class StepResult:
    ok: bool
    summary: str
    detail: str = ""


def _run(argv: list[str], *, timeout: float = 900.0, cwd: str | None = None) -> tuple[int, str]:
    """Run a FIXED argv. No shell, no string interpolation, no caller-supplied words."""
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, redact((proc.stdout or "") + (proc.stderr or ""))


SERVICE_USER = "tcgrowth"

#: The ONE root-privileged action in the entire runner. Everything else happens as the service
#: user, which the runner already is. See docs/workpackages/WP-U4D-ENABLEMENT-GATE.md.
DEPLOY_WRAPPER = "/usr/local/bin/tc-deploy-release.sh"


def assert_not_root() -> None:
    """Refuse to run as root (WP-U4d enablement review).

    The runner is a child of the Console, which runs as `tcgrowth`. If it ever finds itself
    running as root, something about the deployment surface is not what this code believes, and
    every allowlist below was written for the unprivileged case. Refusing is the honest response
    to that, and it is cheap.
    """
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise DeployRefused(
            "the deployment runner must not run as root — it runs as the unprivileged service "
            f"user and escalates only through {DEPLOY_WRAPPER}")


def ex_preflight(sha: str, ctx: dict) -> StepResult:
    _assert_allowed_path(APP_DIR)
    code, out = _run(["git", "-C", APP_DIR, "fetch", "origin", "main"])
    if code != 0:
        return StepResult(False, "could not fetch origin/main", out)
    code, out = _run(["git", "-C", APP_DIR, "merge-base", "--is-ancestor", sha, REMOTE_REF])
    if code != 0:
        return StepResult(False, f"{sha[:12]} is not an ancestor of {REMOTE_REF} — refusing to "
                                 "deploy a commit that is not on the reviewed line", out)
    return StepResult(True, f"target {sha[:12]} is on {REMOTE_REF}", out)


def _table_names(conn) -> list[str]:
    return sorted(r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))


def content_digest(path: str) -> tuple[str, int, int]:
    """A deterministic digest of every row in every table (review #78 blocker 2).

    Equal row COUNTS prove almost nothing — two databases can agree on counts and disagree on
    every value. This hashes the full content: each row is serialised with its table name and
    column names, the serialised rows are sorted (so row order and rowid allocation cannot
    change the result), and the whole thing is hashed. Returns (digest, tables, rows).
    """
    import sqlite3
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        h = hashlib.sha256()
        tables = _table_names(conn)
        total = 0
        for table in tables:
            cur = conn.execute(f"SELECT * FROM {table}")
            cols = [d[0] for d in cur.description]
            rows = sorted(json.dumps([table, cols, list(r)], sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), default=str)
                          for r in cur.fetchall())
            total += len(rows)
            h.update(f"\x00table:{table}\x00".encode("utf-8"))
            for row in rows:
                h.update(row.encode("utf-8"))
                h.update(b"\x00")
        return h.hexdigest(), len(tables), total
    finally:
        conn.close()


def verify_backup(src: str, dst: str) -> tuple[bool, str]:
    """Is `dst` a recovery copy of `src`? Two independent checks, both required.

    1. SQLite's own `PRAGMA integrity_check` — the copy must be a structurally sound database,
       not merely a file of the right size.
    2. A full content digest of both — the copy must contain the same rows, not the same count
       of rows.

    Anything less would let the plan promise a recovery path it cannot deliver.
    """
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
        try:
            integrity = [r[0] for r in conn.execute("PRAGMA integrity_check")]
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return False, f"the backup is not a readable SQLite database: {exc}"
    if integrity != ["ok"]:
        return False, "the backup failed SQLite integrity_check: " + "; ".join(integrity[:5])

    src_digest, tables, rows = content_digest(src)
    dst_digest, dst_tables, dst_rows = content_digest(dst)
    if src_digest != dst_digest:
        return False, (f"the backup's CONTENT differs from the original "
                       f"(source {tables} tables/{rows} rows, copy {dst_tables}/{dst_rows}) — "
                       "equal counts would not have been enough to notice this")
    return True, (f"integrity_check ok and content digest {src_digest[:12]} matches across "
                  f"{tables} tables / {rows} rows")


def ex_backup(sha: str, ctx: dict) -> StepResult:
    """Back up, then VERIFY — integrity plus full content, never just counts (#78 blocker 2).

    Retried once: the store is live, so a write landing between the copy and the digest is a
    real possibility. If the second attempt still disagrees we refuse rather than guess, because
    a backup we cannot prove faithful is not a recovery path.
    """
    import sqlite3
    src = ctx["db_path"]
    dst = f"{src}.pre-{sha[:12]}.bak"
    last = "not attempted"
    for attempt in (1, 2):
        with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
            s.backup(d)
        ok, last = verify_backup(src, dst)
        if ok:
            ctx["backup_path"] = dst
            return StepResult(True, f"verified backup: {last}", dst)
    return StepResult(False, "backup could NOT be verified — treating this as no backup and "
                             f"stopping before anything irreversible runs: {last}", dst)


def ex_converge(sha: str, ctx: dict) -> StepResult:
    code, out = _run(["git", "-C", APP_DIR, "merge", "--ff-only", sha])
    if code != 0:
        return StepResult(False, "fast-forward to the target failed", out)
    return StepResult(True, f"app checkout converged to {sha[:12]}", out)


def ex_suite(sha: str, ctx: dict) -> StepResult:
    code, out = _run([ctx["venv_python"], "-m", "pytest", "-q"],
                     cwd=f"{APP_DIR}/orchestrator", timeout=1800.0)
    tail = "\n".join(out.strip().splitlines()[-5:])
    if code != 0:
        return StepResult(False, "test suite FAILED — stopping before the store is migrated", tail)
    return StepResult(True, tail.splitlines()[-1] if tail else "suite green", tail)


def ex_migrate(sha: str, ctx: dict) -> StepResult:
    code, out = _run([ctx["venv_python"], "-m", "tc_growth.cli", "db-init"],
                     cwd=f"{APP_DIR}/orchestrator")
    if code != 0:
        return StepResult(False, "store migration failed", out)
    return StepResult(True, "store migrated from the converged checkout", out)


def ex_release(sha: str, ctx: dict) -> StepResult:
    # The guard sits HERE, beside the one escalation it protects, rather than at the entry to
    # execute(): the property being defended is "the privileged step runs as the unprivileged
    # service user and escalates only through the wrapper", which is a statement about this
    # step. Gating the whole run on it would also refuse deployments whose executors never
    # escalate at all.
    assert_not_root()
    rel = _assert_allowed_path(release_dir(sha))
    if not os.path.isdir(rel):
        code, out = _run(["git", "-C", APP_DIR, "worktree", "add", "--detach", rel, sha])
        if code != 0:
            return StepResult(False, "could not create the release worktree", out)
    # Both files belong to the service user we already are — no privilege needed to stage it.
    try:
        shutil.copyfile(f"{APP_DIR}/orchestrator/.env", f"{rel}/orchestrator/.env")
        os.chmod(f"{rel}/orchestrator/.env", 0o600)
    except OSError as exc:
        return StepResult(False, "could not stage the release environment file",
                          redact(f"{type(exc).__name__}: {exc}"))
    # THE one escalation: a fixed root-owned wrapper taking a single validated SHA. Not
    # `sudo <script>` from inside the release worktree — that would make a tree this runner can
    # write into the thing root executes.
    # Fixed verb + validated SHA. The wrapper re-validates both and ignores everything we
    # export — the environment below reaches nothing privileged (PR #79 review round 2).
    code, out = _run(["sudo", "-n", DEPLOY_WRAPPER, "apply", sha], timeout=900.0)
    if code != 0:
        return StepResult(False, "the release step failed — rollback is available",
                          "\n".join(out.strip().splitlines()[-25:]))
    return StepResult(True, f"Console released from {sha[:12]}",
                      "\n".join(out.strip().splitlines()[-25:]))


def ex_health(sha: str, ctx: dict) -> StepResult:
    _assert_allowed_service(SERVICE)
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{ctx['port']}/", timeout=15) as r:
            code = r.status
    except Exception as exc:  # noqa: BLE001 — a failed health check is a RESULT, not a crash
        return StepResult(False, "Console did not answer on loopback", redact(f"{type(exc).__name__}: {exc}"))
    rc, out = _run(["systemctl", "show", SERVICE, "--no-pager", "-p", "Environment"])
    pinned = sha in out
    if code != 200 or not pinned:
        return StepResult(False, f"health check failed (HTTP {code}, target pinned: {pinned})", out)
    return StepResult(True, f"HTTP {code} and the running service pins {sha[:12]}", out)


#: Closed dispatch table. A step name that is not a key here cannot execute — there is no
#: fallback that would run "whatever was asked for".
EXECUTORS = {
    "preflight": ex_preflight, "backup": ex_backup, "converge": ex_converge,
    "suite": ex_suite, "migrate": ex_migrate, "release": ex_release, "health": ex_health,
}


def default_context() -> dict:
    return {
        "db_path": os.environ.get("TC_DB_PATH", f"{APP_DIR}/orchestrator/data/tc_growth.db"),
        "venv": os.environ.get("TC_VENV", f"{APP_DIR}/orchestrator/.venv"),
        "venv_python": os.environ.get("TC_VENV", f"{APP_DIR}/orchestrator/.venv") + "/bin/python",
        "port": os.environ.get("TC_CONSOLE_PORT", "8385"),
    }


# --------------------------------------------------------------------------- the runner

def execute(store, run_id: int, *, context: dict | None = None, executors: dict | None = None,
            steps: tuple[Step, ...] = STEPS) -> str:
    """Run the authorized deployment, writing each step to the store as it happens.

    This function is what the DETACHED process runs. It never returns anything the Console
    depends on: the store is the channel. Stop-on-failure is absolute — the first failed step
    marks the run `failed` and no later step is attempted, so a deployment can never limp past
    a failed migration or a red suite.
    """
    # NOT `context or default_context()`: an empty dict is falsy, so that form silently ran the
    # PRODUCTION context whenever a caller passed `{}`. And not a copy either — the context is a
    # scratchpad the steps hand forward (the backup path reaches the recovery text through it),
    # so the caller must see what the steps recorded.
    ctx = context if context is not None else default_context()
    ex = dict(executors or EXECUTORS)
    run = store.get_deploy_run(run_id)
    if run is None:
        raise DeployRefused(f"no such deploy run: {run_id}")
    if run["status"] != "planned":
        raise DeployRefused(f"deploy run {run_id} is {run['status']}, not planned — refusing to "
                            "re-run; a deployment is authorized once")
    sha = validate_sha(run["sha"])
    # The atomic planned -> running claim IS the mutual exclusion (review #78 blocker 1). Reading
    # `planned` above is necessary but NOT sufficient: two detached runners can both pass that
    # read. The LOSER must stop here — before any step is recorded and before any executor runs —
    # so it can neither duplicate the migration/release/restart nor overwrite the winner's
    # terminal result.
    if not store.start_deploy_run(run_id, pid=os.getpid()):
        raise DeployRefused(
            f"deploy run {run_id} was already claimed by another runner — refusing to execute it "
            "a second time")

    seq = 0
    for step in steps:
        seq += 1
        store.record_deploy_step(run_id, seq=seq, name=step.name, status="running",
                                 summary=redact(step.title))
        try:
            result = ex[step.name](sha, ctx)
        except DeployRefused as exc:
            seq += 1
            store.record_deploy_step(run_id, seq=seq, name=step.name, status="failed",
                                     summary=redact(str(exc)))
            store.finish_deploy_run(run_id, status="refused", outcome=redact(str(exc)))
            return "refused"
        except Exception as exc:  # noqa: BLE001 — a DEFECT, and it must say so
            import traceback
            seq += 1
            store.record_deploy_step(
                run_id, seq=seq, name=step.name, status="failed",
                summary=f"defect in the deployment runner at step '{step.name}': "
                        f"{type(exc).__name__} — this is a bug, not a policy refusal",
                detail=redact(traceback.format_exc()))
            store.finish_deploy_run(run_id, status="failed",
                                    outcome=f"runner defect at step '{step.name}'")
            return "failed"
        seq += 1
        store.record_deploy_step(run_id, seq=seq, name=step.name,
                                 status="ok" if result.ok else "failed",
                                 summary=redact(result.summary), detail=redact(result.detail))
        if not result.ok:
            store.finish_deploy_run(run_id, status="failed",
                                    outcome=redact(f"stopped at '{step.name}': {result.summary}"))
            return "failed"

    store.finish_deploy_run(run_id, status="succeeded",
                            outcome=f"deployed {sha[:12]} and verified on loopback")
    return "succeeded"


def spawn_detached(run_id: int, *, python: str | None = None) -> int:
    """Start the runner in its own session so it OUTLIVES the Console restart.

    `setsid` + detached stdio puts the runner outside the Console's process group. Combined with
    `KillMode=process` on tc-console.service (so a restart signals only the main process), the
    deployment continues across the very restart it performs, and writes its own terminal result.
    """
    argv = [python or sys.executable, "-m", "tc_growth.cli", "deploy-run", str(int(run_id))]
    proc = subprocess.Popen(
        argv, start_new_session=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=dict(os.environ), cwd=f"{APP_DIR}/orchestrator" if os.path.isdir(APP_DIR) else None)
    return proc.pid


def plan_text(plan: dict) -> str:
    """The plan as owner-readable lines — the same text whose digest binds the authorization."""
    lines = [
        f"target commit .......... {plan['target_sha']}",
        f"currently deployed ..... {plan.get('current_sha') or 'unknown'}",
        f"repository ............. {plan['repository']}",
        f"release directory ...... {plan['release_dir']}",
        f"service ................ {plan['service']}",
        f"touches production WP .. {'YES' if plan['touches_production_wordpress'] else 'NO'}",
        "",
        "steps, in order (stops at the first failure):",
    ]
    for i, s in enumerate(plan["steps"], 1):
        mark = "reversible" if s["reversible"] else "NOT REVERSIBLE"
        lines.append(f"  {i}. {s['title']}  [{mark}]")
    lines += ["", "irreversible steps: " + ", ".join(plan["irreversible_steps"]),
              "", "rollback: " + plan["rollback"]]
    return "\n".join(lines)


def quoted(argv: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)


@dataclass
class FakeClock:
    """Test seam so step ordering can be asserted without sleeping."""
    ticks: list[str] = field(default_factory=list)
