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

**The target is a value, not a constant** (WP-U4d.1). The paths, store, service and evidence
namespace live on a `Target` from `deploy_target`, resolved from the run context. Production is
the default and the only target that exists unless the command-line gate is open — see that
module for what the seam does and does not claim. This is what lets a disposable target be
driven for real instead of argued about.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

# `DeployRefused` is imported, not redefined: it lives beside the target seam because that seam is
# the first thing able to refuse. Re-exporting it here keeps every existing
# `except deploy.DeployRefused` catching the same class.
from .deploy_target import PRODUCTION, DeployRefused, Target  # noqa: F401

# --------------------------------------------------------------------------- closed allowlists

SHA_RE = re.compile(r"^[0-9a-f]{40}$")

#: Production's surface, kept as names because the whole codebase and its tests read them. They
#: are now views onto the production `Target` rather than the runner's only possible world.
APP_DIR = PRODUCTION.app_dir
RELEASES_DIR = PRODUCTION.releases_dir
SERVICE = PRODUCTION.service
REMOTE_REF = PRODUCTION.remote_ref

#: Fixed deployment surface for production. Anything outside these is refused before a process is
#: spawned — the check is on the value, not on the caller's good intentions. A disposable target
#: carries its own allowlist; `_assert_allowed_path` takes the target it is checking against.
ALLOWED_PATHS = PRODUCTION.allowed_paths
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


def validate_sha(sha: str) -> str:
    """Exact 40-hex or nothing. Short SHAs, refs, branch names and `HEAD` are all refused: a
    deployment target must be unambiguous and must mean the same thing tomorrow."""
    s = (sha or "").strip()
    if not SHA_RE.match(s):
        raise DeployRefused(
            "the deployment target must be an exact 40-character commit SHA in lowercase hex; "
            "branch names, short SHAs and refs are refused because they can change meaning")
    return s


def target_of(ctx: dict | None) -> Target:
    """The target a run addresses. Absent from the context means production.

    Deliberately a plain lookup with a production default rather than anything cleverer: the ONLY
    way a non-production target enters a context is that something built one, and building one
    needs the command-line gate in `deploy_target`. There is no name-to-target table here for a
    request to index into, because a table is exactly the shape an injection would want.
    """
    target = (ctx or {}).get("target")
    if target is None:
        return PRODUCTION
    if not isinstance(target, Target):
        raise DeployRefused("the deployment target must be a Target value, never a name to look up")
    return target


def release_dir(sha: str, target: Target | None = None) -> str:
    return (target or PRODUCTION).release_dir(validate_sha(sha))


def _assert_allowed_path(path: str, target: Target | None = None) -> str:
    """A path must sit inside the target's allowlist, after normalization. `..` cannot walk out."""
    norm = os.path.normpath(path)
    for root in (target or PRODUCTION).allowed_paths:
        if norm == root or norm.startswith(root + "/"):
            return norm
    raise DeployRefused(f"path outside the deployment allowlist: {path}")


def _assert_allowed_service(name: str, target: Target | None = None) -> str:
    if name != (target or PRODUCTION).service:
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
         "git merge --ff-only to the exact SHA, as the account the runner already runs as "
         "(tcgrowth on the production host) — no escalation. Reversible only by deploying the "
         "previous SHA, and recorded as irreversible so it is never a surprise."),
    # "on the deployment target", not "on the VPS": read by eye in the first disposable run's
    # stored evidence, where a step that ran in a throwaway directory claimed to have run on the
    # VPS. Small, and exactly the kind of text that makes a record say more than it knows.
    Step("suite", "Run the full test suite on the deployment target", True,
         "Any failure stops the deployment here, before the store is migrated."),
    Step("migrate", "Migrate the shared store from the converged checkout", False,
         "db-init. Schema migrations are additive but NOT undoable; the verified backup from "
         "step 2 is the recovery path."),
    Step("stage", "Stage the release worktree and verify its content against the commit", True,
         "Detached worktree at releases/<sha>, then EVERY file in it is hashed and compared "
         "against a manifest read from the committed objects — not against the worktree's own "
         "git metadata, which the same account can rewrite. A file added, removed, resized or "
         "edited after checkout stops the deployment here, before anything is deployed. "
         "Reversible: the worktree is removed and nothing outside releases/<sha> has changed."),
    Step("release", "Deploy the Console through the single privileged verb", False,
         "One escalation: `sudo tc-deploy-privileged.sh apply <sha>`. Root takes a verb and a "
         "SHA — no path, user, service, unit, port or environment — verifies its own machinery "
         "against a root-owned manifest, re-authenticates the release bytes against its own copy, "
         "snapshots the current unit/inspector/sudoers, then installs and restarts. Reversible "
         "via the same program's `rollback` verb, which restores that snapshot."),
    Step("health", "Check the Console answers on loopback", True,
         "HTTP 200 from 127.0.0.1 on the service port, and the running unit pins the target SHA."),
)

IRREVERSIBLE = tuple(s.name for s in STEPS if not s.reversible)


def build_plan(sha: str, *, current_sha: str | None = None, target: Target | None = None) -> dict:
    """The plan the owner reviews BEFORE authorizing. It names the target, the fixed paths and
    service, every step in order, and — separately and prominently — which steps cannot be
    undone. `plan_digest` binds the authorization to exactly this text.

    The target's NAME is part of the plan, so a plan reviewed for a disposable target can never be
    the authorization a production run executes under: the digests differ.
    """
    sha = validate_sha(sha)
    target = target or PRODUCTION
    plan = {
        "target_sha": sha,
        "current_sha": current_sha,
        "target": target.name,
        "disposable": target.disposable,
        "evidence_namespace": target.evidence_namespace,
        "repository": target.app_dir,
        "release_dir": release_dir(sha, target),
        "service": target.service,
        "remote_ref": target.remote_ref,
        "touches_production_wordpress": False,
        "steps": [{"name": s.name, "title": s.title, "reversible": s.reversible,
                   "detail": s.detail} for s in STEPS],
        "irreversible_steps": list(IRREVERSIBLE),
        "stop_on_failure": True,
        "rollback": "The privileged program's `rollback` verb restores the previous unit, "
                    "inspector and sudoers from a root-owned snapshot, selected by a root-written "
                    "pointer rather than by anything the caller supplies. The store is recovered "
                    "from the step-2 backup, which is proven by SQLite integrity_check AND a full "
                    "row-content digest match — not by row counts. A converged checkout is "
                    "returned by deploying the previous SHA.",
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


def _run(argv: list[str], *, timeout: float = 900.0, cwd: str | None = None,
         env: dict | None = None) -> tuple[int, str]:
    """Run a FIXED argv. No shell, no string interpolation, no caller-supplied words.

    `env=None` inherits, which is what production does today. A disposable target passes a
    CONSTRUCTED environment instead, because a throwaway run that an inherited variable could
    redirect would prove nothing about the run. Constructing production's child environment too
    is acceptance criterion 5 and belongs to the privileged program, not here.
    """
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    return proc.returncode, redact((proc.stdout or "") + (proc.stderr or ""))


# WP-U4d.1, PR #79 defect 1. The unprivileged steps used to be wrapped in `sudo -u tcgrowth`.
# Every one of those was a NO-OP — `tc-console.service` sets `User=tcgrowth` and the runner is its
# detached child — but they required a sudoers rule broad enough to run `python -m <anything>`,
# which issue #77 forbids. The wrapper is gone: these commands run as whatever account the runner
# already is, which is the account they were always meant to run as. Removing it is also what
# makes the disposable harness possible, because it is what lets these steps execute somewhere
# other than the production host.

def ex_preflight(sha: str, ctx: dict) -> StepResult:
    target = target_of(ctx)
    _assert_allowed_path(target.app_dir, target)
    remote, ref = target.remote_ref.split("/", 1)
    code, out = _run(["git", "-C", target.app_dir, "fetch", remote, ref])
    if code != 0:
        return StepResult(False, f"could not fetch {target.remote_ref}", out)
    code, out = _run(
        ["git", "-C", target.app_dir, "merge-base", "--is-ancestor", sha, target.remote_ref])
    if code != 0:
        return StepResult(False, f"{sha[:12]} is not an ancestor of {target.remote_ref} — refusing "
                                 "to deploy a commit that is not on the reviewed line", out)
    return StepResult(True, f"target {sha[:12]} is on {target.remote_ref}", out)


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
    # The backup goes to the target's backup directory. Falling back to "beside the store" keeps
    # the production behaviour byte-identical (production's backup_dir IS its data directory) and
    # keeps every direct caller of this executor working.
    dst_dir = ctx.get("backup_dir") or os.path.dirname(os.path.abspath(src))
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, f"{os.path.basename(src)}.pre-{sha[:12]}.bak")
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
    target = target_of(ctx)
    code, out = _run(["git", "-C", target.app_dir, "merge", "--ff-only", sha])
    if code != 0:
        return StepResult(False, "fast-forward to the target failed", out)
    return StepResult(True, f"app checkout converged to {sha[:12]}", out)


def ex_suite(sha: str, ctx: dict) -> StepResult:
    target = target_of(ctx)
    code, out = _run([ctx["venv_python"], "-m", "pytest", "-q"],
                     cwd=target.orchestrator_dir, timeout=1800.0, env=ctx.get("child_env"))
    tail = "\n".join(out.strip().splitlines()[-5:])
    if code != 0:
        return StepResult(False, "test suite FAILED — stopping before the store is migrated", tail)
    return StepResult(True, tail.splitlines()[-1] if tail else "suite green", tail)


def ex_migrate(sha: str, ctx: dict) -> StepResult:
    target = target_of(ctx)
    code, out = _run([ctx["venv_python"], "-m", "tc_growth.cli", "db-init"],
                     cwd=target.orchestrator_dir, env=ctx.get("child_env"))
    if code != 0:
        return StepResult(False, "store migration failed", out)
    return StepResult(True, "store migrated from the converged checkout", out)


# --------------------------------------------------------- release content: what is actually there
#
# PR #79 defect 2, stated as a rule: **a check whose inputs the adversary owns is not a check.**
# `git rev-parse HEAD == <sha>` in the release worktree proves which commit was *checked out*, and
# `git status` asks the worktree's own `.git` — which the account that owns the worktree can
# rewrite. Neither notices a file edited after checkout.
#
# So the manifest is read from the COMMITTED OBJECTS (`ls-tree` + `cat-file`), and the worktree is
# hashed from its actual bytes on disk. The two are compared with nothing in between.
#
# What this establishes, precisely: the staged release tree is byte-for-byte the tree recorded in
# commit <sha>, as that commit exists in the app checkout's object store. What it does NOT yet
# establish: that the object store itself is trustworthy to a root process — it is writable by the
# same unprivileged account. Closing that gap needs a root-owned manifest, which is the privileged
# increment and is deliberately not in this one.

_GIT_MODE_FILE = "100644"
_GIT_MODE_EXEC = "100755"
_GIT_MODE_LINK = "120000"


def _cat_file_batch(git_dir: str, oids: list[str], *, timeout: float = 300.0) -> dict[str, bytes]:
    """Read many blobs in ONE `git cat-file --batch`, keeping the content as bytes.

    Bytes, not text: a manifest that round-trips content through a decoder cannot notice a change
    the decoder normalises away.
    """
    if not oids:
        return {}
    proc = subprocess.run(["git", "-C", git_dir, "cat-file", "--batch"],
                          input=("\n".join(oids) + "\n").encode("ascii"),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if proc.returncode != 0:
        raise DeployRefused("could not read the committed objects for the release manifest: "
                            + redact(proc.stderr.decode("utf-8", "replace").strip()))
    out, pos, blobs = proc.stdout, 0, {}
    for _ in oids:
        end = out.find(b"\n", pos)
        if end < 0:
            raise DeployRefused("truncated response while reading the committed objects")
        header = out[pos:end].decode("ascii", "replace").split()
        pos = end + 1
        if len(header) != 3 or header[1] != "blob":
            raise DeployRefused(f"unexpected object while reading the release manifest: {header}")
        size = int(header[2])
        blobs[header[0]] = out[pos:pos + size]
        pos += size + 1        # skip the trailing newline git writes after each object
    return blobs


def commit_manifest(git_dir: str, sha: str) -> dict[str, tuple[str, str]]:
    """`{path: (git mode, sha256 of the content)}` for every entry in commit `sha`.

    Read from the object database, so it describes what was committed rather than what is on disk.
    """
    sha = validate_sha(sha)
    proc = subprocess.run(["git", "-C", git_dir, "ls-tree", "-r", "-z", sha],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300.0)
    if proc.returncode != 0:
        raise DeployRefused(f"could not list the tree of {sha[:12]}: "
                            + redact(proc.stderr.decode("utf-8", "replace").strip()))
    entries = []
    for record in proc.stdout.split(b"\x00"):
        if not record:
            continue
        meta, _, path = record.partition(b"\t")
        mode, kind, oid = meta.decode("ascii", "replace").split()
        if kind != "blob":
            raise DeployRefused(
                f"the release tree contains a {kind} entry ({path.decode('utf-8', 'replace')}); "
                "submodules and nested trees are not supported by the release verifier, and an "
                "unsupported entry is refused rather than skipped")
        entries.append((path.decode("utf-8", "surrogateescape"), mode, oid))
    blobs = _cat_file_batch(git_dir, sorted({oid for _, _, oid in entries}))
    return {path: (mode, hashlib.sha256(blobs[oid]).hexdigest()) for path, mode, oid in entries}


def _worktree_entry(root: str, rel_path: str) -> tuple[str, str]:
    """`(git mode, sha256)` for one path as it ACTUALLY is on disk."""
    full = os.path.join(root, rel_path)
    st = os.lstat(full)
    if stat.S_ISLNK(st.st_mode):
        return _GIT_MODE_LINK, hashlib.sha256(os.readlink(full).encode("utf-8", "surrogateescape")).hexdigest()
    with open(full, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    mode = _GIT_MODE_EXEC if st.st_mode & stat.S_IXUSR else _GIT_MODE_FILE
    return mode, digest


def _worktree_paths(root: str) -> list[str]:
    """Every file under `root`, excluding git's own bookkeeping.

    `.git` is excluded because in a worktree it is a FILE pointing into the parent repository's
    administrative directory — it is not release content and is not what this check is about.
    """
    root = os.path.normpath(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in sorted(filenames):
            if name == ".git" and os.path.normpath(dirpath) == root:
                continue
            found.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(found)


def verify_release_content(release_path: str, manifest: dict[str, tuple[str, str]]
                           ) -> tuple[bool, str]:
    """Does the staged release tree match the committed tree, byte for byte?

    Reports every discrepancy in the three kinds that matter — added, removed, changed — rather
    than the first one found, because "one file differs" and "forty files differ" are different
    incidents and the owner should be able to tell them apart from the record.
    """
    on_disk = _worktree_paths(release_path)
    added = [p for p in on_disk if p not in manifest]
    removed = [p for p in manifest if p not in set(on_disk)]
    changed = []
    for path in on_disk:
        if path in manifest and _worktree_entry(release_path, path) != manifest[path]:
            changed.append(path)
    if not (added or removed or changed):
        return True, (f"{len(manifest)} files match the committed tree by sha256 "
                      "(content and executable bit)")

    def _sample(label: str, paths: list[str]) -> str:
        if not paths:
            return ""
        shown = ", ".join(sorted(paths)[:5])
        more = ", …" if len(paths) > 5 else ""
        return f"{label}: {len(paths)} ({shown}{more})"

    parts = [p for p in (_sample("added", added), _sample("removed", removed),
                         _sample("changed", changed)) if p]
    return False, "; ".join(parts)


def ex_stage(sha: str, ctx: dict) -> StepResult:
    """Create the release worktree if it is not already there, then verify what is in it.

    The verification runs whether or not this step created the directory, which is the case that
    matters: a worktree left behind by an earlier run is exactly the tree an adversary with write
    access would edit, and skipping the check for pre-existing directories would make the whole
    step decorative.
    """
    target = target_of(ctx)
    rel = _assert_allowed_path(release_dir(sha, target), target)
    if not os.path.isdir(rel):
        code, out = _run(["git", "-C", target.app_dir, "worktree", "add", "--detach", rel, sha])
        if code != 0:
            return StepResult(False, "could not create the release worktree", out)
    manifest = commit_manifest(target.app_dir, sha)
    ok, detail = verify_release_content(rel, manifest)
    if not ok:
        raise DeployRefused(
            f"the staged release at {rel} does not match commit {sha[:12]} — refusing to deploy "
            f"content nobody reviewed ({detail})")
    ctx["release_dir"] = rel
    return StepResult(True, f"release {sha[:12]} staged and verified against the commit", detail)


#: The privileged program's exit codes, mirrored here so the runner can tell "policy refused" from
#: "the file phases ran and the manager phases could not" without parsing prose.
PRIVILEGED_REFUSED = 2
PRIVILEGED_SYSTEMD_ABSENT = 3


def ex_release(sha: str, ctx: dict) -> StepResult:
    """ONE escalation, through a verb interface (WP-U4d.1 increment 2).

    This used to escalate twice: `sudo install` to stage an env file, then `sudo` on
    `deploy-console.sh` **from the release worktree** — handing root a script out of a tree the
    service user owns, which is the boundary defect review round 5 found. Both are gone.

    What is passed to root is a verb and a SHA. Not a path, not a service name, not a unit name,
    not a port, and no environment: the privileged program re-derives every one of those from
    root-owned constants installed beside it, and verifies its own machinery before acting. The
    argv below is the whole interface.
    """
    target = target_of(ctx)
    sha = validate_sha(sha)
    # `sudo -n`: never prompt. The runner is unattended, and a deployment that waits for a
    # password on a TTY nobody is watching is a deployment that hangs rather than fails.
    code, out = _run(["sudo", "-n", target.privileged_entry, "apply", sha],
                     timeout=900.0, env=ctx.get("child_env"))
    tail = "\n".join(out.strip().splitlines()[-25:])
    if code == PRIVILEGED_SYSTEMD_ABSENT:
        # Not success. The privileged program completed its file phases and stopped rather than
        # reporting a restart it never performed; saying "released" here would be the exact class
        # of claim this work package exists to end.
        return StepResult(False, "the privileged program completed its file phases and STOPPED: "
                                 "systemd is not booted on this host, so daemon-reload, restart "
                                 "and health did not run and the release is not serving", tail)
    if code != 0:
        return StepResult(False, f"the privileged apply refused or failed (exit {code}) — "
                                 "rollback is available", tail)
    return StepResult(True, f"Console released from {sha[:12]} through one privileged verb", tail)


def ex_health(sha: str, ctx: dict) -> StepResult:
    target = target_of(ctx)
    _assert_allowed_service(target.service, target)
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{ctx['port']}/", timeout=15) as r:
            code = r.status
    except Exception as exc:  # noqa: BLE001 — a failed health check is a RESULT, not a crash
        return StepResult(False, "Console did not answer on loopback", redact(f"{type(exc).__name__}: {exc}"))
    rc, out = _run(["systemctl", "show", target.service, "--no-pager", "-p", "Environment"])
    pinned = sha in out
    if code != 200 or not pinned:
        return StepResult(False, f"health check failed (HTTP {code}, target pinned: {pinned})", out)
    return StepResult(True, f"HTTP {code} and the running service pins {sha[:12]}", out)


#: Closed dispatch table. A step name that is not a key here cannot execute — there is no
#: fallback that would run "whatever was asked for".
EXECUTORS = {
    "preflight": ex_preflight, "backup": ex_backup, "converge": ex_converge,
    "suite": ex_suite, "migrate": ex_migrate, "stage": ex_stage, "release": ex_release,
    "health": ex_health,
}


def context_for(target: Target, *, env: dict | None = None) -> dict:
    """The run context for a target.

    A **disposable** target takes every value from the target itself and reads no environment at
    all: a throwaway run that could be redirected by an inherited variable would prove nothing.

    **Production** still honours `TC_DB_PATH` / `TC_VENV` / `TC_CONSOLE_PORT`, because that is how
    the host is configured today and silently ignoring them would point a real deployment at the
    wrong store. They are now bounded rather than trusted: an override must land inside the
    target's own allowlist or the run refuses. That is a tightening, not a fix — a privileged
    process must re-derive these from internal constants rather than bound them, and that belongs
    to the privileged increment.
    """
    if target.disposable:
        return {"target": target, "db_path": target.db_path, "backup_dir": target.backup_dir,
                "venv": target.venv, "venv_python": target.venv_python, "port": target.port,
                "child_env": {
                    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                    "HOME": target.app_dir,
                    "LANG": "C.UTF-8",
                    "TC_DB_PATH": target.db_path,
                    "TC_DEPLOY_TARGET": target.name,
                    "GIT_TERMINAL_PROMPT": "0",
                }}
    env = os.environ if env is None else env
    db_path = _assert_allowed_path(env.get("TC_DB_PATH") or target.db_path, target)
    venv = _assert_allowed_path(env.get("TC_VENV") or target.venv, target)
    port = str(env.get("TC_CONSOLE_PORT") or target.port)
    if not port.isdigit():
        raise DeployRefused(f"TC_CONSOLE_PORT is not a port number: {port!r}")
    return {"target": target, "db_path": db_path, "backup_dir": target.backup_dir,
            "venv": venv, "venv_python": f"{venv}/bin/python", "port": port}


def default_context() -> dict:
    return context_for(PRODUCTION)


# --------------------------------------------------------------------------- the runner

def _assert_plan_target_matches(run, ctx: dict) -> None:
    """The authorization names its target, and the run must honour it.

    Without this a plan the owner reviewed for the disposable target could be executed against
    production simply by running it in a different process — the authorization would look valid
    because the SHA and the digest still match. A plan written before the target seam existed
    carries no target and is treated as production, which is what it was.
    """
    target = target_of(ctx)
    try:
        planned = (json.loads(run["plan"]) or {}).get("target") or PRODUCTION.name
    except (TypeError, ValueError) as exc:
        raise DeployRefused(f"deploy run {run['id']} has an unreadable plan: {exc}") from exc
    if planned != target.name:
        raise DeployRefused(
            f"deploy run {run['id']} was authorized for target {planned!r} but this runner is "
            f"pointed at {target.name!r} — refusing to execute an authorization somewhere it was "
            "not given")


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
    _assert_plan_target_matches(run, ctx)
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

    # The terminal message names the steps that ACTUALLY ran. It used to say "deployed <sha> and
    # verified on loopback" unconditionally, which is a claim about the health step — untrue for
    # any run given a shorter step list, such as the disposable harness's. Evidence that describes
    # a step the run never took is the exact failure mode this work package exists to end.
    store.finish_deploy_run(
        run_id, status="succeeded",
        outcome=f"deployed {sha[:12]} on target {target_of(ctx).name}; completed: "
                + ", ".join(s.name for s in steps))
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
        env=dict(os.environ),
        cwd=PRODUCTION.orchestrator_dir if os.path.isdir(PRODUCTION.app_dir) else None)
    return proc.pid


def plan_text(plan: dict) -> str:
    """The plan as owner-readable lines — the same text whose digest binds the authorization."""
    # `.get` with a default, not `[...]`: plans stored before WP-U4d.1 carry no target key, and a
    # page that 500s on last month's evidence is a worse outcome than one that says so.
    target_name = plan.get("target") or "production (plan predates the target seam)"
    lines = [
        f"target commit .......... {plan['target_sha']}",
        f"currently deployed ..... {plan.get('current_sha') or 'unknown'}",
        f"deployment target ...... {target_name}",
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
