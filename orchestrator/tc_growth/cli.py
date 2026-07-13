"""Command-line entrypoints.

    python -m tc_growth.cli [--site <profile>] <command>   # e.g. --site production report

    python -m tc_growth.cli list-tools
    python -m tc_growth.cli smoke <tool_name> '<json args>'
    python -m tc_growth.cli weekly-report
    python -m tc_growth.cli investigate "<question or anomaly>"
    python -m tc_growth.cli test-email
    python -m tc_growth.cli db-init                 # create the SQLite store + seed Case #1
    python -m tc_growth.cli cases [open|resolved]   # list cases
    python -m tc_growth.cli case <id-or-ref>        # show one case (with narrative)
    python -m tc_growth.cli runs                    # list recent runs
    python -m tc_growth.cli decisions               # list the decision log
    python -m tc_growth.cli case-note <ref> "<text>"     # append a human observation to a case
    python -m tc_growth.cli case-status <ref> <status>   # human-approved lifecycle change
    python -m tc_growth.cli decision-approve <id> ["note"]   # approve a proposed decision
    python -m tc_growth.cli decision-reject <id> ["note"]    # reject a proposed decision
    python -m tc_growth.cli decision-add "<title>" ["rationale"] [case-ref]  # human policy decision (enters agent memory as approved)
    python -m tc_growth.cli decision-outcome <id> <worked|failed> ["evidence"]  # record execution result after verification
    python -m tc_growth.cli draft-test "<task>"          # supervised DRAFTS-phase run (staging)
    python -m tc_growth.cli validation                   # Release 0.3 validation report (from docs/VALIDATION.md)
    python -m tc_growth.cli dashboard [port]             # read-only web view (127.0.0.1 only)

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


def cmd_smoke(name: str, raw_args: str) -> int:
    args = json.loads(raw_args) if raw_args else {}
    payload = load_all().dispatch(name, args)
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("ok") else 1


def cmd_weekly_report(kind: str = "messages", *, validation: bool = False) -> int:
    from .report import build_weekly_report, deliver

    runtime = _build_runtime(kind)
    report = build_weekly_report(runtime, phase=Phase.READ_ONLY, validation=validation)
    deliver(report, validation=validation)
    return 0


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
    s.update_decision(d.id, status=status)
    if d.case_id:
        entry = f"Decision D#{d.id} ('{d.title}') {status} by human."
        if note:
            entry += f" Note: {note}"
        s.append_observation(d.case_id, entry, author="human")
    print(f"Decision D#{d.id} ('{d.title}'): {d.status} -> {status}")
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
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
