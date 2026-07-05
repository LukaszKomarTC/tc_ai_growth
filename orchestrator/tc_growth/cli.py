"""Command-line entrypoints.

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


def cmd_weekly_report(kind: str = "messages") -> int:
    from .report import build_weekly_report, deliver

    runtime = _build_runtime(kind)
    report = build_weekly_report(runtime, phase=Phase.READ_ONLY)
    deliver(report)
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
    load_env()  # export .env into the process environment (Anthropic SDK, Meta/Telegram tokens)
    argv = argv if argv is not None else sys.argv[1:]
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
        return cmd_weekly_report(rest[0] if rest else "messages")
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
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
