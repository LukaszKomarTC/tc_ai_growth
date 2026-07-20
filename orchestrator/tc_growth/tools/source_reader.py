"""Source Reader tools (WP-07): read-only, path-disciplined access to plugin/theme source.

Why: the 2026-07-19/20 diagnosis inferred qTranslate's and Yoast's behaviour from symptoms
across ~10 human relay rounds because only OUR plugin (in the repo) was readable. These tools
answer such questions in one call — on either profile, since the orchestrator shares the VPS
with both sites.

Every read is audit-logged (path, bytes, outcome) to data/source_audit.jsonl — metadata only,
NEVER file content (the audit trail must not become the leak it exists to prevent, same rule
as WP-08). A per-process read budget bounds runaway loops.
"""

from __future__ import annotations

import json
from typing import Any

from ..config import BASE_DIR, get_settings
from ..core.source_reader import (
    SourceAccessDenied,
    list_dir,
    parse_roots,
    read_file,
    resolve_checked,
)
from .base import Tool, ToolError, registry

_READ_BUDGET = 60
_BYTE_BUDGET = 5 * 1024 * 1024

# Budget state is keyed by (run identity, profile) — a STRUCTURAL boundary, not an
# operational assumption (reviewer 2026-07-20). Today a tool process serves exactly one
# report run and one profile (env-bound) and dies with it, so the default run identity is
# the pid; if the orchestrator ever moves to persistent workers or queues, runtimes must
# call bind_run(run_id) and the isolation survives that architecture change unchanged.
# LIFECYCLE ASSUMPTION (documented + tested): one process = one run = one profile.
_budgets: dict = {}
_budget_lock = __import__("threading").Lock()
_bound_run: list = [None]


def bind_run(run_id: str) -> None:
    """Bind subsequent budget accounting to an explicit run identity (future runtimes)."""
    _bound_run[0] = str(run_id)


def _budget_key() -> tuple:
    import os as _os
    return (_bound_run[0] or f"pid:{_os.getpid()}", get_settings().site_name or "default")


def _audit(action: str, path: str, *, bytes_returned: int = 0, outcome: str = "ok") -> None:
    """Best-effort JSONL audit — metadata only, never content; never raises."""
    try:
        import datetime as dt

        line = json.dumps({
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "site": get_settings().site_name or "default",
            "action": action, "path": path, "bytes": bytes_returned, "outcome": outcome,
        })
        log = BASE_DIR / "data" / "source_audit.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _charge(bytes_consumed: int, *, path: str = "") -> None:
    """Atomic per-(run, profile) accounting. Denied reads charge a CALL (bounds deny-probe
    loops) but no bytes; full-file hashing charges its actual read bandwidth."""
    key = _budget_key()
    with _budget_lock:
        spent = _budgets.setdefault(key, {"calls": 0, "bytes": 0})
        spent["calls"] += 1
        spent["bytes"] += bytes_consumed
        calls, size = spent["calls"], spent["bytes"]
    if calls > _READ_BUDGET or size > _BYTE_BUDGET:
        _audit("budget", path, outcome="budget_exhausted")
        raise ToolError(
            f"source-read budget exhausted for this run ({_READ_BUDGET} calls / "
            f"{_BYTE_BUDGET // 1024**2} MB) — narrow the investigation or continue next run"
        )


def _roots():
    return parse_roots(get_settings().source_roots)


def _read(args: dict[str, Any]) -> Any:
    path = str(args["path"])
    roots = _roots()
    try:
        resolved = resolve_checked(path, roots)
        result = read_file(resolved, roots)
    except SourceAccessDenied as exc:
        _audit("read", path, outcome=f"denied:{exc.code}")
        _charge(0, path=path)  # denials consume a call, never bytes
        raise ToolError(f"[{exc.code}] {exc}")
    except OSError as exc:  # distinct audit class: infrastructure, not policy or probing
        _audit("read", path, outcome=f"fs_error:{exc.__class__.__name__}")
        _charge(0, path=path)
        raise ToolError(f"[fs_error] {exc}")
    _charge(result["bytes_consumed"], path=path)
    _audit("read", result["path"], bytes_returned=result["returned_bytes"])
    return result


def _list(args: dict[str, Any]) -> Any:
    path = str(args.get("path", "")).strip()
    roots = _roots()
    if not path:
        return {"roots": [str(r) for r in roots]}
    try:
        resolved = resolve_checked(path, roots)
        result = list_dir(resolved, roots)
    except SourceAccessDenied as exc:
        _audit("list", path, outcome=f"denied:{exc.code}")
        _charge(0, path=path)
        raise ToolError(f"[{exc.code}] {exc}")
    _charge(0, path=path)
    _audit("list", result["path"])
    return result


registry.register(Tool(
    name="source_list",
    description="List a directory under the profile's allowlisted source roots (plugins/themes/"
                "mu-plugins). Call with no path to see the configured roots. Read-only; "
                "credential files and uploads are structurally unreadable.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Directory to list; omit for the roots"}},
    },
    handler=_list,
))

registry.register(Tool(
    name="source_read",
    description="Read one source file (plugin/theme/mu-plugin code, selected logs) from the "
                "allowlisted roots — up to 256 KB, truncation flagged. Use to answer 'why does "
                "this plugin behave that way' from its actual code instead of inference. "
                "wp-config, .env, dumps, archives, keys and uploads are denied by construction.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Absolute file path within the roots"}},
        "required": ["path"],
    },
    handler=_read,
))
