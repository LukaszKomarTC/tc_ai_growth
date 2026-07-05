"""Case-memory tools (Phase 2, slice 5) — the agent maintains its own institutional memory.

These write to the agent's OWN store, never to any external system, which is why most are allowed
in READ_ONLY phase: the phase gate governs external side effects, and a notebook entry is not one.
The single exception is `case_set_status` — lifecycle transitions (open -> resolved/closed) are
consequential judgments, so that tool is in ALWAYS_ASK and can only execute with a human in the
loop; in a scheduled run the agent must *propose* the change in its report instead.

Search-before-create is enforced at the tool layer: `case_open` refuses to create a case that
matches an existing open one unless the model explicitly confirms it is genuinely new.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from ..store import open_store
from .base import Tool, ToolError, registry

_STATUSES = ["open", "monitoring", "resolved", "closed"]
_PRIORITIES = ["low", "medium", "high", "critical"]

_CATEGORY_PREFIX = {"incident": "INC", "seo": "SEO", "tracking": "TRK", "ads": "ADS"}


def _case_dict(c) -> dict[str, Any]:
    return {
        "ref": c.ref or f"#{c.id}",
        "title": c.title,
        "status": c.status,
        "priority": c.priority,
        "confidence": c.confidence,
        "category": c.category,
        "updated_at": c.updated_at,
    }


def _resolve(s, ref: str):
    case = s.get_case_by_ref(ref)
    if case is None and ref.lstrip("#").isdigit():
        case = s.get_case(int(ref.lstrip("#")))
    if case is None:
        raise ToolError(f"No case matching '{ref}'. Use case_search to find the right ref.")
    return case


def _search(args: dict[str, Any]) -> Any:
    s = open_store()
    try:
        # ALL statuses on purpose: matching a RESOLVED case is the "possible recurrence" signal.
        hits = s.find_cases(str(args["query"]), limit=int(args.get("limit", 10)))
        return [_case_dict(c) for c in hits]
    finally:
        s.close()


def _read(args: dict[str, Any]) -> Any:
    s = open_store()
    try:
        case = _resolve(s, str(args["ref"]))
        decisions = s.list_decisions(case_id=case.id)
        return {
            **_case_dict(case),
            "opened_by": case.opened_by,
            "closed_by": case.closed_by,
            "created_at": case.created_at,
            "narrative": case.body or "",
            "decisions": [
                {"title": d.title, "status": d.status, "made_by": d.made_by, "made_at": d.made_at}
                for d in decisions
            ],
        }
    finally:
        s.close()


def _open(args: dict[str, Any]) -> Any:
    s = open_store()
    try:
        title = str(args["title"]).strip()
        # Search-before-create ACROSS ALL STATUSES: a match against a resolved case means
        # "possible recurrence of a known incident", which must be surfaced, not duplicated.
        matches = s.find_cases(f"{title} {args.get('summary', '')}", limit=5)
        if matches and not args.get("confirmed_new"):
            return {
                "created": False,
                "possible_duplicates": [_case_dict(c) for c in matches],
                "instruction": "These cases (any status) may already cover this. FIRST call "
                               "case_read on the closest match and compare its narrative/timeline "
                               "with your data. If it is the same phenomenon: case_note the new "
                               "evidence there (and propose reopening if it was resolved). Only if "
                               "genuinely distinct, call case_open again with confirmed_new=true.",
            }
        category = args.get("category") or "case"
        prefix = _CATEGORY_PREFIX.get(category, "CASE")
        now = dt.datetime.now(dt.timezone.utc)
        ref = f"{prefix}-{now:%Y%m%d-%H%M%S}"
        case_id = s.create_case(
            title=title,
            ref=ref,
            category=category,
            priority=args.get("priority", "medium"),
            confidence=str(args["confidence"]) if args.get("confidence") is not None else None,
            opened_by="agent",
            body=str(args.get("summary", "")).strip() or None,
        )
        return {"created": True, "ref": ref, "id": case_id}
    finally:
        s.close()


def _note(args: dict[str, Any]) -> Any:
    s = open_store()
    try:
        case = _resolve(s, str(args["ref"]))
        s.append_observation(case.id, str(args["observation"]), author="agent")
        return {"ref": case.ref or f"#{case.id}", "noted": True}
    finally:
        s.close()


def _set_confidence(args: dict[str, Any]) -> Any:
    s = open_store()
    try:
        case = _resolve(s, str(args["ref"]))
        new = str(args["confidence"])
        s.update_case(case.id, confidence=new)
        s.append_observation(case.id, f"Confidence {case.confidence or 'unset'} -> {new}. "
                                      f"Basis: {args.get('basis', 'not stated')}", author="agent")
        return {"ref": case.ref or f"#{case.id}", "confidence": {"from": case.confidence, "to": new}}
    finally:
        s.close()


def _set_status(args: dict[str, Any]) -> Any:
    s = open_store()
    try:
        case = _resolve(s, str(args["ref"]))
        new = str(args["status"])
        if new not in _STATUSES:
            raise ToolError(f"Invalid status '{new}'. One of: {', '.join(_STATUSES)}")
        fields: dict[str, Any] = {"status": new}
        if new in ("resolved", "closed"):
            fields["closed_by"] = "agent"  # executed only under per-call human approval (ALWAYS_ASK)
        s.update_case(case.id, **fields)
        s.append_observation(case.id, f"Status {case.status} -> {new}. "
                                      f"Reason: {args.get('reason', 'not stated')}", author="agent")
        return {"ref": case.ref or f"#{case.id}", "status": {"from": case.status, "to": new}}
    finally:
        s.close()


def _decision(args: dict[str, Any]) -> Any:
    s = open_store()
    try:
        case_id = None
        if args.get("case_ref"):
            case_id = _resolve(s, str(args["case_ref"])).id
        did = s.record_decision(
            title=str(args["title"]),
            rationale=args.get("rationale"),
            status="proposed",   # agent decisions start as proposals; a human activates them
            made_by="agent",
            case_id=case_id,
        )
        return {"decision_id": did, "status": "proposed"}
    finally:
        s.close()


registry.register(Tool(
    name="case_search",
    description="Search ALL cases (institutional memory) by keywords — including resolved/closed "
                "ones, because matching a resolved case means possible recurrence, not novelty. "
                "Call before treating any observation as new, and before case_open.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keywords, e.g. 'tobacco spam URLs'"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    },
    handler=_search,
))

registry.register(Tool(
    name="case_read",
    description="Read a case's FULL narrative (timeline, evidence, retracted hypotheses, prior "
                "verification) plus its linked decisions. The one-line case summaries omit this "
                "depth — ALWAYS read the closest matching case before judging whether an "
                "observation is new or already covered.",
    input_schema={
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "Case ref, e.g. INC-2026-02-01"},
        },
        "required": ["ref"],
    },
    handler=_read,
))

registry.register(Tool(
    name="case_open",
    description="Open a NEW case in memory for a genuinely new, consequential finding. "
                "Automatically checks for existing open cases first and refuses likely duplicates "
                "unless confirmed_new=true.",
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "category": {"type": "string", "enum": list(_CATEGORY_PREFIX) + ["case"]},
            "priority": {"type": "string", "enum": _PRIORITIES, "default": "medium"},
            "summary": {"type": "string", "description": "Initial narrative: observations so far, evidence"},
            "confidence": {"type": "number", "description": "0-1 initial confidence in the finding"},
            "confirmed_new": {"type": "boolean", "description": "Set true ONLY after reviewing possible_duplicates"},
        },
        "required": ["title", "summary"],
    },
    handler=_open,
))

registry.register(Tool(
    name="case_note",
    description="Append a timestamped observation to an existing case (evidence, weekly check "
                "result, 'no recurrence this week', etc.). The narrative is append-only.",
    input_schema={
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "Case ref, e.g. INC-2026-02-01"},
            "observation": {"type": "string"},
        },
        "required": ["ref", "observation"],
    },
    handler=_note,
))

registry.register(Tool(
    name="case_set_confidence",
    description="Update a case's calibrated confidence (0-1 number) with the evidence basis. "
                "Use when new data strengthens or weakens the case's conclusion.",
    input_schema={
        "type": "object",
        "properties": {
            "ref": {"type": "string"},
            "confidence": {"type": "number", "description": "New confidence 0-1"},
            "basis": {"type": "string", "description": "What evidence moved it"},
        },
        "required": ["ref", "confidence"],
    },
    handler=_set_confidence,
))

registry.register(Tool(
    name="case_set_status",
    description="Change a case's lifecycle status (open/monitoring/resolved/closed). Consequential: "
                "requires explicit human approval per call. In an autonomous run, PROPOSE the change "
                "in your report instead.",
    input_schema={
        "type": "object",
        "properties": {
            "ref": {"type": "string"},
            "status": {"type": "string", "enum": _STATUSES},
            "reason": {"type": "string"},
        },
        "required": ["ref", "status"],
    },
    handler=_set_status,
))

registry.register(Tool(
    name="decision_log",
    description="Record a PROPOSED decision in the decision log (optionally linked to a case). "
                "Proposals await human activation; use for 'we should keep spam URLs at 410', etc.",
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "rationale": {"type": "string"},
            "case_ref": {"type": "string", "description": "Optional case to link, e.g. INC-2026-02-01"},
        },
        "required": ["title"],
    },
    handler=_decision,
))
