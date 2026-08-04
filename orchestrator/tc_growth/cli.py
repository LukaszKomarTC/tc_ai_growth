"""Command-line entrypoints.

    python -m tc_growth.cli [--site <profile>] <command>   # e.g. --site production report

    python -m tc_growth.cli list-tools
    python -m tc_growth.cli list-operations         # named-operation catalogue (Action Registry)
    python -m tc_growth.cli smoke <tool_name> '<json args>'
    python -m tc_growth.cli weekly-report
    python -m tc_growth.cli investigate "<question or anomaly>"
    python -m tc_growth.cli test-email
    python -m tc_growth.cli smtp-test               # instrumented SMTP test (streams each step)
    python -m tc_growth.cli integrity-scan          # Technical Inspector: read-only WP integrity scan
    python -m tc_growth.cli db-init                 # create the SQLite store + seed Case #1
    python -m tc_growth.cli cases [open|resolved]   # list cases
    python -m tc_growth.cli case <id-or-ref>        # show one case (with narrative)
    python -m tc_growth.cli runs                    # list recent runs
    python -m tc_growth.cli report-artifacts        # list stored report artifacts (U3a)
    python -m tc_growth.cli report-artifact <id>    # artifact metadata (--body dumps exact body)
    python -m tc_growth.cli report-redeliver <id>   # re-send a stored artifact (no regeneration)
    python -m tc_growth.cli report-redeliver-latest # re-send the newest stored report (Console op)
    python -m tc_growth.cli decisions               # list the decision log
    python -m tc_growth.cli case-note <ref> "<text>"     # append a human observation to a case
    python -m tc_growth.cli case-status <ref> <status>   # human-approved lifecycle change
    python -m tc_growth.cli decision-approve <id> ["note"]   # approve a proposed decision
    python -m tc_growth.cli decision-reject <id> ["note"]    # reject a proposed decision
    python -m tc_growth.cli decision-propose <file.json>     # propose a U4 workflow decision (approve in the Console)
    python -m tc_growth.cli decision-add "<title>" ["rationale"] [case-ref]  # human policy decision (enters agent memory as approved)
    python -m tc_growth.cli decision-outcome <id> <worked|failed> ["evidence"]  # record execution result after verification
    python -m tc_growth.cli draft-test "<task>"          # supervised DRAFTS-phase run (staging)
    python -m tc_growth.cli validation                   # Release 0.3 validation report (from docs/VALIDATION.md)
    python -m tc_growth.cli dashboard [port]             # read-only web view (127.0.0.1 only)
    python -m tc_growth.cli console [port]               # Operations Console (execute ops; 127.0.0.1 + token)

`smoke` exercises a single host-side tool WITHOUT the AI runtime — the fastest way to surface
OAuth/vault/credential problems (the usual first failure point). `weekly-report` runs the full
growth coordinator. `investigate` runs a read-only FORENSIC analysis (timelines, evidence-graded
findings) for a specific question — e.g. an SEO-spam pattern or a traffic anomaly.
"""

from __future__ import annotations

import json
import sys

from .config import get_settings, load_env
from .core.approval import Phase
from .tools.load import load_all


def _build_runtime(kind: str = "messages"):
    """Instantiate the configured provider runtime. Only this function knows the provider.

    kind="messages"  -> local Messages-API tool loop (no Managed Agents needed; good for smoke).
    kind="managed"   -> hosted Managed Agents session driver (needs TC_COORDINATOR_AGENT_ID + TC_ENV_ID).
    """
    s = get_settings()
    if s.ai_provider != "anthropic":
        raise SystemExit(f"Unknown / unconfigured ai_provider: {s.ai_provider}")
    if kind == "managed":
        from .runtime.managed_agents import ManagedAgentsRuntime

        return ManagedAgentsRuntime()
    from .runtime.anthropic_runtime import AnthropicRuntime

    return AnthropicRuntime()


def cmd_list_tools() -> int:
    for tool in load_all().all():
        print(f"{tool.name:24} {tool.description.splitlines()[0]}")
    return 0


def cmd_list_operations() -> int:
    """Print the Action Registry: every named operation with its governance envelope.

    Validates first — a catalogue that contradicts the enforcement layer must not print
    as if it were true.
    """
    from .core.actions import OPERATIONS, validate_registry

    validate_registry()
    for op in OPERATIONS:
        state = "" if op.enabled else "  [DISABLED]"
        binding = op.tool and f"tool:{op.tool}" or f"cli:{op.command}"
        envs = "/".join(op.environments)
        print(f"{op.id:26} {op.category.value:12} phase>={int(op.min_phase)}  "
              f"approval:{op.approval.value:13} env:{envs:18} {binding}{state}")
    return 0


def cmd_smoke(name: str, raw_args: str) -> int:
    args = json.loads(raw_args) if raw_args else {}
    payload = load_all().dispatch(name, args)
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("ok") else 1


def cmd_weekly_report(kind: str = "messages", *, validation: bool = False) -> int:
    from .report import build_weekly_report, deliver, validate_report_artifact

    runtime = _build_runtime(kind)
    report = build_weekly_report(runtime, phase=Phase.READ_ONLY, validation=validation)
    # Fail-closed: if the agent produced no valid report artifact, deliver it as a clearly-marked
    # FAILURE (not a success) and exit non-zero so the scheduler records the run as failed.
    ok, reason = validate_report_artifact(report)
    deliver(report, validation=validation, ok=ok)
    if not ok:
        print(f"weekly report artifact INVALID ({reason}) — delivered as failure, run marked failed")
    return 0 if ok else 1


def cmd_test_email() -> int:
    """Send a tiny test email to verify SMTP (e.g. Brevo) works — no AI tokens spent."""
    from .report import send_email

    body = (
        "This is a delivery test from the TC Growth agent.\n\n"
        "If you can read this, SMTP is configured correctly and the weekly digest will arrive.\n"
    )
    try:
        ok = send_email("Tossa Cycling — Email delivery test", body, raise_on_error=True)
    except Exception as exc:
        print(f"Email test FAILED: {exc}")
        return 1
    print("Email test sent — check the inbox." if ok else "Email not configured.")
    return 0 if ok else 1


def cmd_smtp_test() -> int:
    """Instrumented SMTP test — prints each protocol step (connect/starttls/auth/send).

    This is the CLI binding the Action Registry points `smtp_test` at. The Operations Console
    calls the same underlying `smtp_test_steps` directly to stream the step events; here we
    print them so the operator gets the same evidence from the terminal.
    """
    from .report import smtp_test_steps

    def _print(step: str, status: str, detail: str = "") -> None:
        line = f"  [{status:5}] {step}"
        print(f"{line}: {detail}" if detail else line)

    ok, summary = smtp_test_steps(emit=_print)
    print(summary)
    return 0 if ok else 1


def cmd_integrity_scan() -> int:
    """Run the Technical Inspector (read-only WP integrity scan), streaming its output.

    This is the CLI binding the Action Registry points `run_integrity_scan` at. It runs the
    standalone inspector script and passes its output and exit code straight through, so the
    Operations Console surfaces it through the GENERIC command path — no executor code is
    specific to this operation. Exit codes: 0 = clean, 2 = anomalies found (and logged), other
    = the scan could not run.
    """
    import os
    import subprocess
    from pathlib import Path

    from .config import BASE_DIR

    script = os.environ.get("TC_INSPECTOR_SCRIPT") or str(BASE_DIR / "scripts" / "wp-integrity-scan.sh")
    if not Path(script).is_file():
        print(f"integrity scanner not found at {script} — set TC_INSPECTOR_SCRIPT or deploy the script.")
        return 1
    # Op-specific provenance: record WHICH scanner actually ran (path + content hash + deploy
    # commit) as the first evidence line — so "the scan passed" is always traceable to an exact
    # script revision, per docs/TECHNICAL_INSPECTOR.md.
    import hashlib

    sha = hashlib.sha256(Path(script).read_bytes()).hexdigest()
    commit = os.environ.get("TC_BUILD_COMMIT", "unknown")
    # Provenance in the evidence stream identifies the scanner by CONTENT HASH + commit, not its
    # absolute path — the sha256 is the definitive identity, and the full deploy path stays in the
    # server-side deploy log (journald), not in a browser-facing evidence line. (Review: don't leak
    # filesystem layout to the UI.)
    print(f"scanner: {Path(script).name} sha256={sha[:16]} commit={commit}", flush=True)
    # TC_INSPECTOR_SUDO=true: run the deployed, root-owned scanner via sudo, because the service
    # user cannot read the WP docroot (VPS recon, defect D2). The sudoers drop-in installed by the
    # deploy package allowlists EXACTLY this path with ZERO arguments — and sudo's env_reset strips
    # the caller's TC_* environment, so the scan target is pinned to the script's baked defaults
    # even if the Console's environment were compromised. Script must be executable (deployed 0755).
    use_sudo = os.environ.get("TC_INSPECTOR_SUDO", "").strip().lower() in ("1", "true", "yes")
    argv = ["sudo", "-n", "--", script] if use_sudo else ["bash", script]
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
    except OSError as exc:
        print(f"could not launch integrity scanner: {exc}")
        return 1
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line.rstrip("\n"), flush=True)
    return proc.wait()


def cmd_investigate(question: str) -> int:
    from .investigate import build_investigation

    if not question:
        print('Usage: investigate "<question or anomaly to investigate>"')
        return 1
    runtime = _build_runtime()
    print(build_investigation(runtime, question, phase=Phase.READ_ONLY))
    return 0


def cmd_db_init() -> int:
    from . import store

    s = store.open_store()
    case_id = s.seed_incident_case()
    print(f"Store ready at {store.resolved_db_path()}")
    print(f"Seeded {store.INCIDENT_REF} as case #{case_id}")
    return 0


def cmd_cases(status: str | None = None) -> int:
    from . import store

    rows = store.open_store().list_cases(status=status)
    if not rows:
        print("(no cases)")
        return 0
    for c in rows:
        ref = c.ref or f"#{c.id}"
        print(f"{ref:16} [{c.status:10}] {c.priority:8} {c.title}")
    return 0


def cmd_case_show(key: str) -> int:
    from . import store

    s = store.open_store()
    case = s.get_case_by_ref(key)
    if case is None and key.isdigit():
        case = s.get_case(int(key))
    if case is None:
        print(f"No case matching {key!r}")
        return 1
    print(f"# {case.ref or ('#' + str(case.id))} — {case.title}")
    print(f"status={case.status}  priority={case.priority}  confidence={case.confidence}")
    print(f"category={case.category}  created={case.created_at}  updated={case.updated_at}\n")
    print(case.body or "(no narrative)")
    return 0


def cmd_runs() -> int:
    from . import store

    rows = store.open_store().list_runs()
    if not rows:
        print("(no runs logged yet)")
        return 0
    for r in rows:
        cost = f"${r.cost_usd:.4f}" if r.cost_usd is not None else "—"
        print(f"#{r.id:<4} {r.started_at}  {r.kind:16} {r.status:6} {r.model or '—':20} {cost}")
    return 0


def cmd_report_artifacts() -> int:
    """List stored weekly-report artifacts (U3a) — metadata only, newest first."""
    from . import store

    rows = store.open_store().list_report_artifacts()
    if not rows:
        print("(no report artifacts stored yet)")
        return 0
    for a in rows:
        verdict = "ok    " if a.validator_ok else "FAILED"
        print(f"#{a.id:<4} {a.generated_at}  {a.kind:26} {verdict} v{a.validator_version} "
              f"{a.delivery_status:11} sha={a.content_sha256[:16]} {len(a.body)}B "
              f"run#{a.run_id if a.run_id is not None else '—'}")
    return 0


def cmd_report_artifact(artifact_id: str, show_body: bool = False) -> int:
    """Show one artifact's metadata; --body dumps the exact immutable body (for hash-diffing
    against the delivered email — the U3a acceptance check)."""
    from . import store

    a = store.open_store().get_report_artifact(int(artifact_id))
    if a is None:
        print(f"No report artifact #{artifact_id}")
        return 1
    if show_body:
        print(a.body, end="")
        return 0
    print(f"artifact #{a.id}  kind={a.kind}  run#{a.run_id}  profile={a.profile or '—'}")
    print(f"window={a.window or '—'}  generated={a.generated_at}  format={a.format_version}")
    print(f"validator v{a.validator_version}: {'ok' if a.validator_ok else f'FAILED ({a.validator_reason})'}")
    print(f"model={a.model or '—'}  cost={f'${a.cost_usd:.4f}' if a.cost_usd is not None else '—'}")
    print(f"sha256={a.content_sha256}")
    print(f"delivery={a.delivery_status}  delivered_at={a.delivered_at or '—'}  size={len(a.body)}B")
    return 0


def cmd_report_redeliver(artifact_id: str) -> int:
    """Re-deliver a STORED artifact byte-identically (U3a review: the report exists once;
    delivery attempts are tracked separately). No agent run, no tokens, no new artifact —
    deliver() marks this attempt by hash against the same immutable row."""
    from . import store
    from .report import deliver

    a = store.open_store().get_report_artifact(int(artifact_id))
    if a is None:
        print(f"No report artifact #{artifact_id}")
        return 1
    deliver(a.body, validation=a.kind.endswith("-validation"), ok=bool(a.validator_ok),
            artifact_id=a.id)  # bind to THE row — byte-identical twins must never receive this
    b = store.open_store().get_report_artifact(int(artifact_id))
    print(f"artifact #{a.id} re-delivery attempt #{b.delivery_attempts}: {b.delivery_status}")
    return 0 if b.delivery_status == "delivered" else 1


def cmd_report_redeliver_latest() -> int:
    """Re-send the LATEST stored weekly-report artifact — the Console binding (U3b): registry
    command ops take no arguments by design, so 'latest' IS the operation; per-id redelivery
    stays a CLI action until U4 brings argumented approvals."""
    from . import store

    a = store.open_store().latest_report_artifact(kind="weekly-report")
    if a is None:
        print("No weekly-report artifact stored yet (first one lands on the next scheduled run).")
        return 1
    print(f"latest artifact: #{a.id} generated {a.generated_at} sha={a.content_sha256[:16]}")
    return cmd_report_redeliver(str(a.id))


def _resolve_case(s, key: str):
    case = s.get_case_by_ref(key)
    if case is None and key.lstrip("#").isdigit():
        case = s.get_case(int(key.lstrip("#")))
    return case


def cmd_case_note(key: str, text: str) -> int:
    from . import store

    s = store.open_store()
    case = _resolve_case(s, key)
    if case is None:
        print(f"No case matching {key!r}")
        return 1
    s.append_observation(case.id, text, author="human")
    print(f"Noted on {case.ref or case.id}")
    return 0


def cmd_case_status(key: str, status: str) -> int:
    from . import store

    s = store.open_store()
    case = _resolve_case(s, key)
    if case is None:
        print(f"No case matching {key!r}")
        return 1
    fields: dict = {"status": status}
    if status in ("resolved", "closed"):
        fields["closed_by"] = "human"
    s.update_case(case.id, **fields)
    s.append_observation(case.id, f"Status {case.status} -> {status} (human, via CLI).", author="human")
    print(f"{case.ref or case.id}: {case.status} -> {status}")
    return 0


def cmd_decision_set(decision_id: str, status: str, note: str = "") -> int:
    """Human approves/rejects a proposed decision — the whole approval trail lands in the store:
    the decision's status flips, and the linked case (if any) gets a human journal entry."""
    from . import store

    s = store.open_store()
    d = s.get_decision(int(decision_id))
    if d is None:
        print(f"No decision with id {decision_id}")
        return 1
    try:
        s.update_decision(d.id, status=status)
    except ValueError as exc:
        # U4a: workflow decisions (bound envelope) left the CLI on purpose — the eliminated-
        # actions table's first row. Point at the browser path instead of half-working here.
        print(exc)
        return 1
    if d.case_id:
        entry = f"Decision D#{d.id} ('{d.title}') {status} by human."
        if note:
            entry += f" Note: {note}"
        s.append_observation(d.case_id, entry, author="human")
    print(f"Decision D#{d.id} ('{d.title}'): {d.status} -> {status}")
    return 0


def cmd_decision_propose(path: str) -> int:
    """Seed a WORKFLOW decision (U4a) from a JSON file:

        {"title": "...", "rationale": "...", "evidence": "...",
         "impact": {"value": "...", "label": "estimate", "method": "...", "source": "...",
                    "as_of": "..."},
         "confidence": {...same shape...},
         "envelope": {"schema_version": "u4/1", "profile": ..., "environment": ...,
                      "kind": ..., "target": {...}, "payload": {...}}}

    The envelope is validated and canonically hashed at birth; approval then happens in the
    Console browser UI (/decision/<id>) — this command only PROPOSES."""
    import json as _json
    from pathlib import Path

    from . import store

    try:
        doc = _json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Cannot read decision file: {exc}")
        return 1
    if not isinstance(doc, dict) or "envelope" not in doc or "title" not in doc:
        print('The file must be a JSON object with at least "title" and "envelope".')
        return 1
    # Proposal context comes from the RUNTIME, never from the file (review #71 finding 1): the
    # active profile id, the environments this deployment may target, and the profile's
    # legitimate URL hosts. Missing host config fails closed — an unconstrained target host is
    # not a default, it's a decision the owner hasn't made yet.
    from .config import active_site, get_settings

    settings = get_settings()
    expected_profile = active_site() or "default"
    allowed_environments = (("production",) if settings.env_kind.strip().lower() == "production"
                            else ("staging",))
    hosts = tuple(h.strip().lower() for h in settings.decision_url_hosts.split(",") if h.strip())
    if not hosts:
        print("REFUSED: TC_DECISION_URL_HOSTS is not set for this profile — the proposal "
              "boundary cannot verify target URL hosts. Set it (e.g. "
              "TC_DECISION_URL_HOSTS=www.tossacycling.com,tossacycling.com) and retry.")
        return 1

    s = store.open_store()
    case_id = None
    if doc.get("case"):
        case = s.get_case_by_ref(str(doc["case"]))
        if case is None:
            print(f"No case matching {doc['case']!r}")
            return 1
        case_id = case.id
    try:
        did = s.propose_decision(
            title=str(doc["title"]), envelope=doc["envelope"],
            expected_profile=expected_profile, allowed_environments=allowed_environments,
            allowed_hosts=hosts,
            rationale=doc.get("rationale"), evidence=doc.get("evidence"),
            impact=doc.get("impact"), confidence=doc.get("confidence"),
            case_id=case_id, made_by="human")
    except ValueError as exc:
        print(f"REFUSED: {exc}")
        return 1
    d = s.get_decision(did)
    print(f"Decision D#{did} proposed: {d.title}")
    print(f"  envelope sha256: {d.envelope_sha256}")
    print(f"  review + approve in the Console: /decision/{did}")
    return 0


def cmd_decision_add(title: str, rationale: str = "", case_ref: str = "") -> int:
    """Record a HUMAN decision (business policy) directly as approved. It enters the decision
    queue injected into every run, so the agent treats it as in-force — the decision log doubles
    as early policy memory without any new schema."""
    from . import store

    s = store.open_store()
    case_id = None
    if case_ref:
        case = _resolve_case(s, case_ref)
        if case is None:
            print(f"No case matching {case_ref!r}")
            return 1
        case_id = case.id
    did = s.record_decision(title=title, rationale=rationale or None, status="approved",
                            made_by="human", case_id=case_id)
    if case_id:
        s.append_observation(case_id, f"Decision D#{did} recorded by human: {title}", author="human")
    print(f"Decision D#{did} recorded (approved, human): {title}")
    return 0


def cmd_decision_outcome(decision_id: str, outcome: str, evidence: str = "") -> int:
    """Record the RESULT of executing an approved decision — after human verification, never
    before. Closes the loop: proposed -> approved -> executed -> verified (outcome)."""
    from . import store

    if outcome not in ("worked", "failed"):
        print("Outcome must be 'worked' or 'failed'")
        return 1
    s = store.open_store()
    d = s.get_decision(int(decision_id))
    if d is None:
        print(f"No decision with id {decision_id}")
        return 1
    s.update_decision(d.id, outcome=outcome)
    if d.case_id:
        entry = f"Decision D#{d.id} ('{d.title}') executed and verified: {outcome}."
        if evidence:
            entry += f" Evidence: {evidence}"
        s.append_observation(d.case_id, entry, author="human")
    print(f"Decision D#{d.id}: outcome = {outcome}")
    return 0


def cmd_draft_test(instruction: str) -> int:
    """Supervised validation run at DRAFTS phase (staging connector). Human launches, human
    reviews the result in staging wp-admin — see docs/VALIDATION.md Content section."""
    from .core.approval import Phase
    from .validate import run_draft_test

    if not instruction:
        print('Usage: draft-test "<drafting task, e.g. SEO title/meta draft for post 13699>"')
        return 1
    runtime = _build_runtime()
    print(run_draft_test(runtime, instruction, phase=Phase.DRAFTS))
    return 0


def cmd_validation() -> int:
    """Print the Release 0.3 validation report parsed from docs/VALIDATION.md."""
    from .validate import validation_status

    st = validation_status()
    if not st["total"]:
        print("No checklist items found (docs/VALIDATION.md missing?)")
        return 1
    for s in st["sections"]:
        mark = "PASS" if s["pass"] else f"{s['done']}/{s['total']}"
        print(f"{s['name']:<40} {mark}")
    print(f"\nOverall: {st['done']}/{st['total']} ({st['percent']}%)")
    return 0


def cmd_decisions() -> int:
    from . import store

    rows = store.open_store().list_decisions()
    if not rows:
        print("(no decisions logged yet)")
        return 0
    for d in rows:
        link = f" (case #{d.case_id})" if d.case_id else ""
        print(f"#{d.id:<4} {d.made_at}  [{d.status:10}] {d.title}{link}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    # Site profile selection: `--site <name>` / `--site=<name>` (or the TC_SITE env var).
    # Must be resolved BEFORE load_env so the right profile file is exported.
    if argv and argv[0].startswith("--site"):
        import os

        if "=" in argv[0]:
            os.environ["TC_SITE"] = argv[0].split("=", 1)[1].strip()
            argv = argv[1:]
        elif len(argv) > 1:
            os.environ["TC_SITE"] = argv[1].strip()
            argv = argv[2:]
        else:
            print("Usage: --site <name> <command> ...")
            return 1
    load_env()  # export the resolved env file (profile or .env) into the process environment
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "list-tools":
        return cmd_list_tools()
    if cmd == "list-operations":
        return cmd_list_operations()
    if cmd == "smoke":
        return cmd_smoke(rest[0], rest[1] if len(rest) > 1 else "")
    if cmd == "weekly-report":
        # Optional: `weekly-report managed` to use the hosted Managed Agents runtime.
        # `--validation`: manual validation run — distinct ledger kind, labelled header,
        # [MANUAL VALIDATION] email subject; never counts toward the acceptance gate.
        validation = "--validation" in rest
        positional = [a for a in rest if not a.startswith("--")]
        return cmd_weekly_report(positional[0] if positional else "messages", validation=validation)
    if cmd == "investigate":
        return cmd_investigate(rest[0] if rest else "")
    if cmd == "test-email":
        return cmd_test_email()
    if cmd == "smtp-test":
        return cmd_smtp_test()
    if cmd == "integrity-scan":
        return cmd_integrity_scan()
    if cmd == "db-init":
        return cmd_db_init()
    if cmd == "cases":
        return cmd_cases(rest[0] if rest else None)
    if cmd == "case":
        if not rest:
            print("Usage: case <id-or-ref>")
            return 1
        return cmd_case_show(rest[0])
    if cmd == "runs":
        return cmd_runs()
    if cmd == "report-artifacts":
        return cmd_report_artifacts()
    if cmd == "report-artifact":
        if not rest:
            print("Usage: report-artifact <id> [--body]")
            return 1
        return cmd_report_artifact(rest[0], show_body="--body" in rest)
    if cmd == "report-redeliver":
        if not rest:
            print("Usage: report-redeliver <id>")
            return 1
        return cmd_report_redeliver(rest[0])
    if cmd == "report-redeliver-latest":
        return cmd_report_redeliver_latest()
    if cmd == "decisions":
        return cmd_decisions()
    if cmd == "case-note":
        if len(rest) < 2:
            print('Usage: case-note <ref> "<text>"')
            return 1
        return cmd_case_note(rest[0], rest[1])
    if cmd == "case-status":
        if len(rest) < 2:
            print("Usage: case-status <ref> <open|monitoring|resolved|closed>")
            return 1
        return cmd_case_status(rest[0], rest[1])
    if cmd == "draft-test":
        return cmd_draft_test(rest[0] if rest else "")
    if cmd == "validation":
        return cmd_validation()
    if cmd == "decision-outcome":
        if len(rest) < 2:
            print("Usage: decision-outcome <id> <worked|failed> [\"evidence\"]")
            return 1
        return cmd_decision_outcome(rest[0], rest[1], rest[2] if len(rest) > 2 else "")
    if cmd == "decision-propose":
        if not rest:
            print("Usage: decision-propose <decision.json>")
            return 1
        return cmd_decision_propose(rest[0])
    if cmd == "decision-add":
        if not rest:
            print('Usage: decision-add "<title>" ["rationale"] [case-ref]')
            return 1
        return cmd_decision_add(rest[0], rest[1] if len(rest) > 1 else "",
                                rest[2] if len(rest) > 2 else "")
    if cmd in ("decision-approve", "decision-reject"):
        if not rest:
            print(f"Usage: {cmd} <decision-id> [\"note\"]")
            return 1
        status = "approved" if cmd == "decision-approve" else "rejected"
        return cmd_decision_set(rest[0], status, rest[1] if len(rest) > 1 else "")
    if cmd == "dashboard":
        from .dashboard import serve

        serve(port=int(rest[0]) if rest else 8383)
        return 0
    if cmd == "console":
        from .console import serve as serve_console

        return serve_console(port=int(rest[0]) if rest else 8385)
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
