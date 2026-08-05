"""WP-U4d.2 — the Console-driven acceptance run (Acceptance B).

The Operations Console launches the bounded disposable acceptance and the browser supplies
NOTHING but the click: no path, no service, no unit, no port, no user, no command fragment. The
run directory is derived here, on the server, from the one fixed parent the engine already
refuses to leave (`deploy_acceptance.SAFE_ACCEPTANCE_PARENT`). The Console is another *caller*
of the engine — the phase vocabulary, the refusals and the chain all live in
`deploy_acceptance`; this module adds only the durable run record, the launcher, and the
verdict.

The verdict is a CLOSED set and it degrades conservatively:

- ``PASS`` — every phase in `deploy_acceptance.PHASE_ORDER` recorded ``ok``. Nothing less.
- ``FAILED SAFELY`` — something failed AND the safety evidence is present and green: rollback's
  file semantics and the production-state record both landed ``ok``. A failure without that
  evidence is not "safe", it is unresolved.
- ``BLOCKED`` — everything else: a launch the privileged program refused, machinery not
  installed, a deferred phase (systemd absent), an incomplete phase record. A phase that did
  not run is never represented as success; when classification is in doubt, the verdict moves
  toward BLOCKED and never toward PASS.

Privilege: the Console process never escalates and never constructs a target — it is latched
(`deploy_target.note_http_boundary`). It spawns a detached unprivileged runner, and THAT
process makes the one escalation: ``sudo -n <privileged entry> start-acceptance <id>``. The
service user must never hold a sudoers grant that runs root Python from a tree it can write, so
the verb belongs to the same root-owned fixed-verb program as every other privileged operation.
Until that verb exists and is granted (WP-U4d.2 increment 2), the launch fails and the run is
honestly ``BLOCKED`` — which is the truthful description of a host whose machinery is not
installed.

A launch that succeeds hands the run to the root side, which streams engine phases into the
same store row and writes the terminal verdict. A launch that succeeds and then dies leaves the
row ``running``; the reaper for that case is increment 2's problem and is recorded there, not
silently absorbed here.
"""

from __future__ import annotations

import subprocess
import sys

from . import deploy, deploy_acceptance, deploy_target

VERDICT_PASS = "PASS"
VERDICT_FAILED_SAFELY = "FAILED SAFELY"
VERDICT_BLOCKED = "BLOCKED"

#: The phases whose ``ok`` records are the safety evidence FAILED SAFELY requires.
SAFETY_PHASES = ("rollback-file-semantics", "teardown-and-production-check")

#: The one phase name this module adds to the engine's vocabulary: the escalation itself.
LAUNCH_PHASE = "launch"


def derive_run_root(run_id: int) -> str:
    """The run directory, from the fixed safe parent and the run id. Never from a request."""
    return f"{deploy_acceptance.SAFE_ACCEPTANCE_PARENT}/console-run-{int(run_id)}"


def verdict(phases: list[dict]) -> str:
    """The terminal verdict, from the recorded phases alone. Pure; order of rules is the point.

    Later records for the same phase name win, so a retried phase is judged on its final state
    while the earlier attempts remain in the append-only evidence.
    """
    if not phases:
        return VERDICT_BLOCKED
    final = {p["name"]: p["status"] for p in phases}
    if any(status == "deferred" for status in final.values()):
        return VERDICT_BLOCKED
    failed = [name for name, status in final.items() if status in ("failed", "refused")]
    if failed:
        if all(final.get(name) == "ok" for name in SAFETY_PHASES):
            return VERDICT_FAILED_SAFELY
        return VERDICT_BLOCKED
    if all(final.get(name) == "ok" for name in deploy_acceptance.PHASE_ORDER):
        return VERDICT_PASS
    return VERDICT_BLOCKED


def spawn_detached(run_id: int, *, python: str | None = None) -> None:
    """Launch the acceptance runner detached, exactly as deployments are launched: the Console
    only observes after this point, so the run survives anything that happens to the Console."""
    argv = [python or sys.executable, "-m", "tc_growth.cli",
            "acceptance-run", str(int(run_id))]
    subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def execute(store, run_id: int) -> str:
    """The detached runner's whole job: claim the row, make the one escalation, record what
    happened. Returns 'launched' or 'blocked'; raises AcceptanceRefused only on a row that
    cannot be claimed (missing, already claimed, or already finished)."""
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
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=900.0)
        code, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        code, out = 127, str(exc)
    tail = deploy.redact("\n".join(out.strip().splitlines()[-10:]))

    if code == 0:
        store.record_acceptance_phase(run_id, seq=1, name=LAUNCH_PHASE, status="ok",
                                      detail=tail)
        # The root side owns the row from here: it streams the engine phases and writes the
        # terminal verdict. Claiming success for anything beyond the launch would be claiming
        # work this process did not observe.
        return "launched"

    store.record_acceptance_phase(run_id, seq=1, name=LAUNCH_PHASE, status="failed",
                                  detail=f"exit={code}\n{tail}")
    store.finish_acceptance_run(
        run_id, verdict=VERDICT_BLOCKED,
        summary="the privileged program refused the launch or is not installed on this host; "
                "no acceptance phase ran")
    return "blocked"
