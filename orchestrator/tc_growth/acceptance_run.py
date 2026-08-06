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

#: A fixed, root-owned location OUTSIDE any disposable tree (the disposable root is torn down at
#: the end of a run, so the attestation cannot live inside it). Root creates it; `tcgrowth` may
#: read it but cannot write it, and that is the whole anchor.
RECEIPTS_DIR = "/var/lib/tc-console-acceptance/receipts"

_RECEIPT_MAGIC = "TC_ACCEPTANCE_RECEIPT_V1"


def derive_run_root(run_id: int) -> str:
    """The run directory, from the fixed safe parent and the run id. Never from a request."""
    return f"{deploy_acceptance.SAFE_ACCEPTANCE_PARENT}/console-run-{int(run_id)}"


# --------------------------------------------------------------------------- the phase digest

def phase_digest(phases: list[dict]) -> str:
    """A stable digest over the ENGINE phases only, keyed by the fixed PHASE_ORDER.

    Excludes the launch phase and ignores seq, so root (which seals the receipt before the
    launcher writes the launch row) and the Console (which digests every durable row afterward)
    compute the identical value. Later records for a name win, so a retried phase is judged on
    its final state — matching `verdict`.
    """
    final: dict[str, str] = {}
    for p in phases:
        if p["name"] in deploy_acceptance.PHASE_ORDER:
            final[p["name"]] = p["status"]
    canonical = "\n".join(f"{name}={final[name]}"
                          for name in deploy_acceptance.PHASE_ORDER if name in final)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verdict(phases: list[dict]) -> str:
    """The verdict the durable ROWS imply, on their own. Pure; the order of rules is the point.

    This is NOT the trusted verdict — it says what the rows claim, not who wrote them.
    `trusted_verdict` gates a positive result of this on a matching root receipt.
    """
    engine = {p["name"]: p["status"] for p in phases if p["name"] in deploy_acceptance.PHASE_ORDER}
    if not engine:
        return VERDICT_BLOCKED
    if any(status == "deferred" for status in engine.values()):
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
    store.finish_acceptance_run(
        run_id, verdict=VERDICT_BLOCKED,
        summary="the privileged program refused the launch or is not installed on this host; "
                "no acceptance phase ran")
    return "blocked"


def execute_as_root(store, run_id: int, *, receipts_dir: str = RECEIPTS_DIR,
                    now_iso: str | None = None) -> str:
    """The ROOT side of a launch — what the `start-acceptance` privileged verb runs.

    Runs the bounded engine acceptance, streams each phase into the durable record as it lands
    (so progress survives a Console restart), then computes the verdict FROM the durable rows
    and seals a root-owned receipt binding it. Only after the receipt exists does it finish the
    run. `tcgrowth` never reaches this function — it is gated on euid 0 and invoked through the
    privileged verb.
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
                                      detail=detail or None)

    report = deploy_acceptance.run(Path(run["root"]), progress=record)
    phases = store.list_acceptance_phases(run_id)
    rows_verdict = verdict(phases)
    completed = now_iso or deploy.now_iso()
    write_receipt_as_root(
        run_id, target=report.get("target_name", ""),
        engine_head=report.get("target_sha", ""), phases=phases,
        verdict_value=rows_verdict, completed_at=completed, receipts_dir=receipts_dir)
    store.finish_acceptance_run(
        run_id, verdict=rows_verdict,
        summary=f"acceptance {rows_verdict}; receipt sealed by root at {completed}")
    return rows_verdict
