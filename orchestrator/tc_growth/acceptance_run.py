"""WP-U4d.2 — the Console-driven acceptance run (Acceptance B).

The Operations Console launches the bounded disposable acceptance and the browser supplies
NOTHING but the click: no path, no service, no unit, no port, no user, no command fragment. The
run directory is derived here, on the server, from the one fixed parent the engine already
refuses to leave (`deploy_acceptance.SAFE_ACCEPTANCE_PARENT`). The Console is another *caller*
of the engine — the phase vocabulary, the refusals and the chain all live in
`deploy_acceptance`; this module adds the durable run record, the launcher, and the trust
boundary on the verdict.

The trust boundary (increment 2, review of head `f40a20a`)
----------------------------------------------------------
The durable phase rows live in the ordinary store, which the service account can write. So the
rows alone cannot establish WHO produced the evidence: `tcgrowth` could append `ok` phases and
never run the privileged acceptance. A positive verdict must therefore be attested by ROOT and
be unforgeable by the application layer.

The attestation is a **root-owned receipt file**. Its authenticity rests on filesystem
ownership — the same anchor the whole privileged chain uses — not on a shared secret (a secret
`tcgrowth` could read to verify, it could also use to forge). Root writes
`<RECEIPTS_DIR>/<run_id>.receipt`, root-owned and not group/other-writable, in a directory
`tcgrowth` cannot write. The Console shows a positive verdict ONLY when:

  * a receipt exists for this run id, owned by root and not writable by anyone else;
  * its phase digest equals a digest recomputed over the durable rows; and
  * root's recorded verdict agrees with the verdict those rows imply.

Anything else — missing, non-root-owned, mismatched, or a receipt whose verdict the rows do not
support — is ``BLOCKED``. `tcgrowth` cannot create a root-owned file, so it cannot manufacture a
trusted PASS however freely it writes the store. The unprivileged launcher can only ever record
a launch refusal and a ``BLOCKED`` verdict; it never finalises a positive one.

The verdict is a CLOSED set: ``PASS`` (every engine phase ``ok``, attested), ``FAILED SAFELY``
(a phase failed but the rollback and production-state phases recorded ``ok``, attested), or
``BLOCKED`` (everything else). Deferred work is never success; when classification is in doubt
the verdict moves toward BLOCKED and never toward PASS.
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

from . import deploy, deploy_acceptance, deploy_target

VERDICT_PASS = "PASS"
VERDICT_FAILED_SAFELY = "FAILED SAFELY"
VERDICT_BLOCKED = "BLOCKED"
_POSITIVE = (VERDICT_PASS, VERDICT_FAILED_SAFELY)

#: The phases whose ``ok`` records are the safety evidence FAILED SAFELY requires.
SAFETY_PHASES = ("rollback-file-semantics", "teardown-and-production-check")

#: The one phase name this module adds to the engine's vocabulary: the escalation itself. It is
#: deliberately OUTSIDE the digested set — it is launcher bookkeeping, not engine evidence, and
#: it is written by the unprivileged side after root has already sealed the receipt.
LAUNCH_PHASE = "launch"

#: The self-checks the ROOT runner performs automatically and records as durable evidence, so
#: the owner approves once in the browser and never inspects a file, restarts a service, or
#: edits the store by hand (review of head `90ae12f`). Each is a phase like any engine phase and
#: must be `ok` for a positive verdict; a failed check is a trust/integration failure and is
#: `BLOCKED`, never `FAILED SAFELY`.
CHECK_ATTESTATION = "check-attestation-resistance"          # forged rows/receipts -> BLOCKED, on a scratch store
CHECK_RECEIPT_BINDING = "check-receipt-binds-runtime-and-target"
CHECK_STORE_OWNERSHIP = "check-store-ownership-preserved"
CHECK_RESTART_RECONNECT = "check-console-restart-reconnect"  # systemd-bound
CHECK_ORDER = (CHECK_ATTESTATION, CHECK_RECEIPT_BINDING, CHECK_STORE_OWNERSHIP,
               CHECK_RESTART_RECONNECT)

#: The full digested vocabulary: engine phases then self-checks. The launch phase is the only
#: recorded phase outside it (written by the unprivileged side after the receipt is sealed).
ALL_PHASES = tuple(deploy_acceptance.PHASE_ORDER) + CHECK_ORDER

#: A fixed, root-owned location OUTSIDE any disposable tree (the disposable root is torn down at
#: the end of a run, so the attestation cannot live inside it). Root creates it; `tcgrowth` may
#: read it but cannot write it, and that is the whole anchor.
RECEIPTS_DIR = "/var/lib/tc-console-acceptance/receipts"

_RECEIPT_MAGIC = "TC_ACCEPTANCE_RECEIPT_V1"

#: The fixed evidence namespace the disposable acceptance target carries (deploy_harness builds
#: it with name="vpsprobe"). Used as the independent reference the receipt-binding check confirms
#: the sealed target against.
DISPOSABLE_ACCEPTANCE_NAMESPACE = "disposable/vpsprobe"


def derive_run_root(run_id: int) -> str:
    """The run directory, from the fixed safe parent and the run id. Never from a request."""
    return f"{deploy_acceptance.SAFE_ACCEPTANCE_PARENT}/console-run-{int(run_id)}"


# --------------------------------------------------------------------------- the phase digest

def phase_digest(phases: list[dict]) -> str:
    """A stable digest over every digested phase (engine phases and self-checks), keyed by the
    fixed ALL_PHASES order.

    Excludes the launch phase and ignores seq, so root (which seals the receipt before the
    launcher writes the launch row) and the Console (which digests every durable row afterward)
    compute the identical value. Later records for a name win, so a retried phase is judged on
    its final state — matching `verdict`.
    """
    final: dict[str, str] = {}
    for p in phases:
        if p["name"] in ALL_PHASES:
            final[p["name"]] = p["status"]
    canonical = "\n".join(f"{name}={final[name]}" for name in ALL_PHASES if name in final)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verdict(phases: list[dict]) -> str:
    """The verdict the durable ROWS imply, on their own. Pure; the order of rules is the point.

    This is NOT the trusted verdict — it says what the rows claim, not who wrote them.
    `trusted_verdict` gates a positive result of this on a matching root receipt.

    A positive verdict requires BOTH the engine phases and every self-check to be `ok`: the
    self-checks are the runner proving, on the host, that forged evidence would not be believed
    and that the run left the store usable. A failed self-check is a trust/integration failure,
    which is `BLOCKED` — never `FAILED SAFELY` (that is only for a genuine deployment failure the
    rollback handled).
    """
    engine = {p["name"]: p["status"] for p in phases if p["name"] in deploy_acceptance.PHASE_ORDER}
    checks = {p["name"]: p["status"] for p in phases if p["name"] in CHECK_ORDER}
    if not engine:
        return VERDICT_BLOCKED
    if any(s == "deferred" for s in list(engine.values()) + list(checks.values())):
        return VERDICT_BLOCKED
    if not all(checks.get(name) == "ok" for name in CHECK_ORDER):
        return VERDICT_BLOCKED
    failed = [name for name, status in engine.items() if status in ("failed", "refused")]
    if failed:
        if all(engine.get(name) == "ok" for name in SAFETY_PHASES):
            return VERDICT_FAILED_SAFELY
        return VERDICT_BLOCKED
    if all(engine.get(name) == "ok" for name in deploy_acceptance.PHASE_ORDER):
        return VERDICT_PASS
    return VERDICT_BLOCKED


# --------------------------------------------------------------------------- the root receipt

def receipt_path(run_id: int, *, receipts_dir: str = RECEIPTS_DIR) -> Path:
    return Path(receipts_dir) / f"{int(run_id)}.receipt"


def render_receipt(*, run_id: int, target: str, engine_head: str, phases: list[dict],
                   verdict_value: str, completed_at: str) -> str:
    """The receipt bytes root writes. Binds the run id, the target identity, the exact engine
    head, the phase digest, the verdict and the completion time (review increment-2 criterion 1)."""
    return "\n".join([
        _RECEIPT_MAGIC,
        f"run_id={int(run_id)}",
        f"target={target}",
        f"engine_head={engine_head}",
        f"phase_digest={phase_digest(phases)}",
        f"verdict={verdict_value}",
        f"completed_at={completed_at}",
        "",
    ])


def parse_receipt(text: str) -> dict | None:
    lines = text.splitlines()
    if not lines or lines[0] != _RECEIPT_MAGIC:
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        if "=" not in line:
            return None
        key, value = line.split("=", 1)
        fields[key] = value
    required = {"run_id", "target", "engine_head", "phase_digest", "verdict", "completed_at"}
    if not required.issubset(fields):
        return None
    return fields


def _receipt_is_root_owned(path: Path) -> bool:
    """The anchor: the file must be owned by root and writable by nobody else. `tcgrowth` can
    neither create a file in the root-owned receipts directory nor own one, so a receipt that
    passes this check was written by root — which is the only thing that makes the verdict on
    it trustworthy."""
    try:
        st = path.lstat()
    except OSError:
        return False
    if not os.path.isfile(path) or os.path.islink(path):
        return False
    return st.st_uid == 0 and (st.st_mode & 0o022) == 0


def read_trusted_receipt(run_id: int, phases: list[dict], *, receipts_dir: str = RECEIPTS_DIR,
                         require_root_owned: bool = True) -> dict | None:
    """Return the receipt IF it exists, is root-owned, and matches these rows; else None.

    `require_root_owned` exists only so the matching logic can be tested off-root, where no
    process can create a root-owned file. Production always leaves it True — a receipt the
    service account could have written is no attestation at all.
    """
    path = receipt_path(run_id, receipts_dir=receipts_dir)
    if require_root_owned and not _receipt_is_root_owned(path):
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    fields = parse_receipt(text)
    if fields is None:
        return None
    if fields["run_id"] != str(int(run_id)):
        return None
    if fields["phase_digest"] != phase_digest(phases):
        return None
    return fields


def trusted_verdict(run: dict, phases: list[dict], *, receipts_dir: str = RECEIPTS_DIR,
                    require_root_owned: bool = True) -> str | None:
    """The verdict the Console may DISPLAY. None while the run is not yet done (UI shows RUNNING).

    A positive verdict is shown only when a root-owned receipt for this run matches the durable
    rows AND records the same verdict those rows imply. Everything else — no receipt, a receipt
    the service account could have written, a digest mismatch, or root and the rows disagreeing
    — is BLOCKED. The stored `verdict` column is deliberately NOT consulted: it is application
    data and the whole point is that application data cannot finalise a positive verdict.
    """
    if run.get("status") != "done":
        return None
    receipt = read_trusted_receipt(int(run["id"]), phases, receipts_dir=receipts_dir,
                                   require_root_owned=require_root_owned)
    if receipt is None:
        return VERDICT_BLOCKED
    attested = receipt["verdict"]
    if attested not in _POSITIVE:
        return VERDICT_BLOCKED
    if verdict(phases) != attested:      # root's claim must match what the rows imply
        return VERDICT_BLOCKED
    return attested


def _assert_safe_root_dir_chain(directory: Path) -> None:
    """Every EXISTING component from the root of the filesystem down to `directory` must be
    root-owned, not writable by group/other, and not a symlink.

    Without this, an unprivileged actor who controlled an ancestor of the receipts directory
    could redirect where root writes the attestation — a root process following an unprivileged
    symlink is the classic privileged-write defect. Verified before creation, so a poisoned
    ancestor is refused rather than followed.
    """
    components, p = [], directory
    while True:
        components.append(p)
        if p == p.parent:
            break
        p = p.parent
    for comp in reversed(components):           # filesystem root downward
        try:
            st = comp.lstat()
        except OSError:
            continue                            # does not exist yet — root will create it safely
        if stat.S_ISLNK(st.st_mode):
            raise deploy_acceptance.AcceptanceRefused(
                f"{comp} is a symlink; refusing to write a root receipt through it")
        if st.st_uid != 0:
            raise deploy_acceptance.AcceptanceRefused(
                f"{comp} is not root-owned; refusing to write a root receipt beneath it")
        if st.st_mode & 0o022:
            raise deploy_acceptance.AcceptanceRefused(
                f"{comp} is writable by group/other; refusing to write a root receipt beneath it")


def write_receipt_as_root(run_id: int, *, target: str, engine_head: str, phases: list[dict],
                          verdict_value: str, completed_at: str,
                          receipts_dir: str = RECEIPTS_DIR) -> Path:
    """Seal the attestation. MUST run as root: the file's root ownership is the anchor, so a
    non-root writer would produce a receipt the verification correctly rejects.

    The write itself is symlink-safe: the ancestor chain is verified root-owned first, and the
    file is opened O_NOFOLLOW so root cannot be tricked into writing through a planted symlink
    (increment-3 criterion 5)."""
    if os.geteuid() != 0:
        raise deploy_acceptance.AcceptanceRefused(
            "an acceptance receipt may only be sealed by root — its root ownership is the anchor")
    directory = Path(receipts_dir)
    _assert_safe_root_dir_chain(directory)
    directory.mkdir(parents=True, exist_ok=True)
    os.chown(directory, 0, 0)
    os.chmod(directory, 0o755)
    _assert_safe_root_dir_chain(directory)      # re-check: nothing swapped in during creation
    path = receipt_path(run_id, receipts_dir=receipts_dir)
    text = render_receipt(run_id=run_id, target=target, engine_head=engine_head, phases=phases,
                          verdict_value=verdict_value, completed_at=completed_at)
    # O_NOFOLLOW: if `path` is a symlink, this raises rather than writing through it.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    os.chown(path, 0, 0)
    os.chmod(path, 0o644)
    return path


# --------------------------------------------------------------------------- the two runners

def spawn_detached(run_id: int, *, python: str | None = None) -> None:
    """Launch the acceptance runner detached, exactly as deployments are launched: the Console
    only observes after this point, so the run survives anything that happens to the Console."""
    argv = [python or sys.executable, "-m", "tc_growth.cli",
            "acceptance-run", str(int(run_id))]
    subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def execute(store, run_id: int) -> str:
    """The UNPRIVILEGED detached runner. Claims the row, makes the ONE escalation, records what
    happened. Returns 'launched' or 'blocked'; raises AcceptanceRefused only on a row that
    cannot be claimed (missing, already claimed, or already finished).

    It never records a positive verdict: on a successful escalation the ROOT side (inside the
    privileged verb) has already streamed the engine phases, sealed the receipt and finished the
    run. On any failure this side finishes the run BLOCKED — the honest verdict for a host whose
    privileged machinery is absent or refusing.
    """
    run = store.get_acceptance_run(run_id)
    if run is None:
        raise deploy_acceptance.AcceptanceRefused(f"no such acceptance run: {run_id}")
    if not store.claim_acceptance_run(run_id):
        raise deploy_acceptance.AcceptanceRefused(
            f"acceptance run {run_id} is {run['status']}, not requested — refusing to run it "
            "twice; an acceptance is authorized once")

    argv = ["sudo", "-n", deploy_target.PRODUCTION.privileged_entry,
            "start-acceptance", str(int(run_id))]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=3600.0)
        code, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        code, out = 127, str(exc)
    tail = deploy.redact("\n".join(out.strip().splitlines()[-10:]))

    if code == 0:
        store.record_acceptance_phase(run_id, seq=1, name=LAUNCH_PHASE, status="ok", detail=tail)
        # The root side already sealed the receipt and finished the run; claiming anything
        # beyond the launch here would be claiming work this process did not do — and could not
        # attest to if it had.
        return "launched"

    store.record_acceptance_phase(run_id, seq=1, name=LAUNCH_PHASE, status="failed",
                                  detail=f"exit={code}\n{tail}")
    # A non-zero exit does NOT always mean nothing ran: the harness itself exits non-zero for a
    # BLOCKED verdict after recording every phase and finishing the run. In that case root's
    # verdict and summary are the honest record and this side has nothing to add — the first
    # on-host run showed the generic summary below overwriting root's, captioning a run full of
    # durable phases with "no acceptance phase ran". Only an UNFINISHED run may be finished
    # here, as the launch-refusal it then genuinely is.
    finished = store.get_acceptance_run(run_id)
    if finished is not None and finished.get("status") == "done":
        return "blocked"
    store.finish_acceptance_run(
        run_id, verdict=VERDICT_BLOCKED,
        summary="the privileged program refused the launch or is not installed on this host; "
                "no acceptance phase ran")
    return "blocked"


# --------------------------------------------------------------------------- the self-checks
#
# The runner performs these itself and records each as durable evidence, so the owner approves
# once in the browser and never inspects a file, restarts a service, or edits the store by hand
# (review of head `90ae12f`). Each returns (status, detail) where status is "ok" | "failed" |
# "deferred". A failed check is a trust/integration failure and makes the whole verdict BLOCKED.

def verify_attestation_resistance(*, scratch_dir: Path) -> tuple[str, str]:
    """Prove, on THIS host at run time, that forged evidence is not believed — against a
    DISPOSABLE record and receipts directory, never the live store (criterion 5). Root-only,
    because the positive control needs a genuinely root-owned receipt.

    Each case constructs phases (and maybe a receipt) and asserts the trusted verdict. The owner
    never edits a store to check this; the runner does, here, and records the tally.
    """
    if os.geteuid() != 0:
        return "deferred", "attestation self-check needs root to build the root-owned control"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    os.chown(scratch_dir, 0, 0)
    os.chmod(scratch_dir, 0o755)

    import pwd
    green = [{"seq": i, "name": n, "status": "ok"} for i, n in enumerate(ALL_PHASES)]
    done = {"id": 4242, "status": "done"}
    base = dict(target="disposable/vpsprobe", engine_head="a" * 40, verdict_value="PASS",
                completed_at="t")
    cases: list[tuple[str, str, bool]] = []   # (label, actual, passed)

    def fresh_dir(label: str) -> Path:
        rdir = scratch_dir / label
        rdir.mkdir(parents=True, exist_ok=True)
        os.chown(rdir, 0, 0)
        os.chmod(rdir, 0o755)
        return rdir

    def record_case(label: str, phases, rdir: Path, expect: str) -> None:
        actual = trusted_verdict(done, phases, receipts_dir=str(rdir)) or "None"
        cases.append((label, actual, actual == expect))

    # Positive control: a matching root-owned receipt yields PASS.
    rdir = fresh_dir("matching")
    write_receipt_as_root(4242, phases=green, receipts_dir=str(rdir), **base)
    record_case("matching-receipt-passes", green, rdir, VERDICT_PASS)

    # Forged rows, no receipt at all.
    record_case("forged-rows-no-receipt", green, fresh_dir("no-receipt"), VERDICT_BLOCKED)

    # Receipt claims PASS but the rows show a failed phase.
    bad_rows = [dict(p) for p in green]
    bad_rows[3]["status"] = "failed"
    rdir = fresh_dir("verdict-disagree")
    write_receipt_as_root(4242, phases=bad_rows, receipts_dir=str(rdir), **base)
    record_case("receipt-verdict-rows-disagree", bad_rows, rdir, VERDICT_BLOCKED)

    # Receipt sealed over `green`, but substituted rows are presented (digest mismatch).
    other = [dict(p) for p in green]
    other[2]["status"] = "deferred"
    rdir = fresh_dir("digest-mismatch")
    write_receipt_as_root(4242, phases=green, receipts_dir=str(rdir), **base)
    record_case("receipt-digest-mismatch", other, rdir, VERDICT_BLOCKED)

    # Receipt whose content names another run id.
    rdir = fresh_dir("wrong-run")
    (rdir / "4242.receipt").write_text(render_receipt(
        run_id=7, phases=green, **base))
    os.chown(rdir / "4242.receipt", 0, 0)
    os.chmod(rdir / "4242.receipt", 0o644)
    record_case("receipt-wrong-run-id", green, rdir, VERDICT_BLOCKED)

    # A receipt the service account could have written (chowned away from root).
    non_root = next((pwd.getpwnam(n).pw_uid for n in ("nobody", "daemon", "bin")
                     if _uid_present(n)), None)
    if non_root is not None:
        rdir = fresh_dir("non-root")
        write_receipt_as_root(4242, phases=green, receipts_dir=str(rdir), **base)
        os.chown(rdir / "4242.receipt", non_root, non_root)
        record_case("non-root-receipt-rejected", green, rdir, VERDICT_BLOCKED)

    failures = [label for label, _, ok in cases if not ok]
    summary = "; ".join(f"{label}->{actual}" for label, actual, _ in cases)
    if failures:
        return "failed", f"attestation resistance FAILED for {failures}: {summary}"
    return "ok", f"{len(cases)} cases, all as expected: {summary}"


def _uid_present(name: str) -> bool:
    import pwd
    try:
        pwd.getpwnam(name)
        return True
    except KeyError:
        return False


def verify_receipt_binding(report: dict, *, resolved_head: str | None,
                           resolved_target: str | None) -> tuple[str, str]:
    """Root records that the receipt will bind an independently-resolved runtime head and a
    disposable (never production) target, so the owner does not compare files by hand
    (criterion 4). `resolved_head` is the SHA of the root-owned runtime root actually executed
    from — resolved by the privileged verb, not taken from the run. Deferred when no independent
    reference is available (off-host), so it can never masquerade as proven.
    """
    if resolved_head is None or resolved_target is None:
        return "deferred", ("no independent runtime/config reference on this host; the run "
                            f"records target_sha={report.get('target_sha', '')} for the on-host "
                            "cross-check")
    problems = []
    if not deploy.SHA_RE.match(resolved_head):
        problems.append(f"the resolved runtime head is not a 40-hex SHA: {resolved_head!r}")
    if not resolved_target.startswith("disposable/"):
        problems.append(f"the resolved target is not disposable: {resolved_target!r}")
    for marker in deploy_acceptance.PRODUCTION_MARKERS:
        if marker in resolved_target:
            problems.append(f"the resolved target names production: {resolved_target!r}")
    if problems:
        return "failed", "; ".join(problems)
    return "ok", (f"the receipt binds runtime head {resolved_head} and disposable target "
                  f"{resolved_target}, both resolved independently by root")


def verify_store_ownership(store_path: str, *, account: str | None = None) -> tuple[str, str]:
    """After the run, no db/WAL/journal artifact may be left root-owned (that would lock the
    service account out), and — when a service account exists — it must be able to reopen and
    write the store (criterion 6)."""
    p = Path(store_path)
    artifacts = [p] + [p.with_name(p.name + suffix) for suffix in ("-wal", "-journal", "-shm")]
    root_owned = []
    for a in artifacts:
        try:
            if a.exists() and a.stat().st_uid == 0:
                root_owned.append(a.name)
        except OSError:
            continue
    if root_owned:
        return "failed", f"root-owned store artifacts would lock out the service account: {root_owned}"
    if account is None or os.geteuid() != 0:
        return "ok", "no root-owned db/WAL/journal artifacts (service-account write not exercised here)"
    import pwd
    try:
        pw = pwd.getpwnam(account)
    except KeyError:
        return "ok", f"no root-owned artifacts; account {account} not present to exercise a write"
    probe = subprocess.run(
        ["setpriv", "--reuid", str(pw.pw_uid), "--regid", str(pw.pw_gid), "--clear-groups",
         sys.executable, "-c",
         "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
         "c.execute('CREATE TABLE IF NOT EXISTS _u4d2_probe(x)'); "
         "c.execute('DROP TABLE _u4d2_probe'); c.commit(); print('ok')", store_path],
        capture_output=True, text=True, timeout=60)
    if probe.returncode != 0:
        return "failed", f"the service account could not write the store: {probe.stderr.strip()}"
    return "ok", f"no root-owned artifacts and {account} reopened and wrote the store"


def verify_restart_reconnect(store, run_id: int) -> tuple[str, str]:
    """The runner restarts the Console and confirms the run record survives (criterion 3).
    systemd-bound: deferred where it is not booted, so it never claims an unproven reconnection."""
    if not deploy_acceptance.systemd_is_booted():
        return "deferred", "systemd is not booted; the live Console-restart reconnection is on-host"
    before = store.list_acceptance_phases(run_id)
    proc = subprocess.run(["systemctl", "restart", deploy_target.PRODUCTION.service],
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        return "failed", f"could not restart {deploy_target.PRODUCTION.service}: {proc.stderr.strip()}"
    after = store.list_acceptance_phases(run_id)
    if len(after) < len(before):
        return "failed", "the durable run record did not survive the Console restart"
    return "ok", (f"{deploy_target.PRODUCTION.service} restarted; the run record survived with "
                  f"{len(after)} phases intact")


def execute_as_root(store, run_id: int, *, receipts_dir: str = RECEIPTS_DIR,
                    now_iso: str | None = None, resolved_head: str | None = None,
                    resolved_target: str | None = None, account: str | None = None,
                    scratch_dir: Path | None = None) -> str:
    """The ROOT side of a launch — what the `start-acceptance` privileged verb runs.

    Runs the bounded engine acceptance, then performs the acceptance's OWN adversarial and
    integration self-checks (so the owner never does terminal work), streams every phase and
    check into the durable record as it lands, computes the verdict FROM the durable rows, seals
    a root-owned receipt binding it, and only then finishes the run. `tcgrowth` never reaches
    this function — it is gated on euid 0 and invoked through the privileged verb.
    """
    if os.geteuid() != 0:
        raise deploy_acceptance.AcceptanceRefused(
            "the root side of an acceptance run must execute as root")
    run = store.get_acceptance_run(run_id)
    if run is None:
        raise deploy_acceptance.AcceptanceRefused(f"no such acceptance run: {run_id}")

    # Engine phases occupy seq 2+; seq 1 is reserved for the unprivileged launcher's launch row.
    counter = {"seq": 1}

    def record(name: str, status: str, detail: str = "") -> None:
        counter["seq"] += 1
        store.record_acceptance_phase(run_id, seq=counter["seq"], name=name, status=status,
                                      detail=deploy.redact(detail) if detail else None)

    report = deploy_acceptance.run(Path(run["root"]), progress=record)

    # The runner's own checks — recorded as durable evidence, not delegated to the owner.
    scratch = scratch_dir or (Path(receipts_dir).parent / "self-check-scratch")
    for name, (status, detail) in (
        (CHECK_ATTESTATION, verify_attestation_resistance(scratch_dir=scratch)),
        (CHECK_RECEIPT_BINDING, verify_receipt_binding(
            report, resolved_head=resolved_head, resolved_target=resolved_target)),
        (CHECK_STORE_OWNERSHIP, verify_store_ownership(
            deploy_target.PRODUCTION.db_path, account=account)),
        (CHECK_RESTART_RECONNECT, verify_restart_reconnect(store, run_id)),
    ):
        record(name, status, detail)

    phases = store.list_acceptance_phases(run_id)
    rows_verdict = verdict(phases)
    completed = now_iso or deploy.now_iso()
    write_receipt_as_root(
        run_id, target=resolved_target or report.get("target_name", ""),
        engine_head=resolved_head or report.get("target_sha", ""), phases=phases,
        verdict_value=rows_verdict, completed_at=completed, receipts_dir=receipts_dir)
    store.finish_acceptance_run(
        run_id, verdict=rows_verdict,
        summary=f"acceptance {rows_verdict}; receipt sealed by root at {completed}")
    return rows_verdict
