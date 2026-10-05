# app/mcp/handlers/gates.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Human approval gate MCP tools (hitl_approve nodes).
Owns:             list_pending_gates_handler, decide_gate_handler + schemas.
Public Surface:   *_handler, *_DESCRIPTION, *_SCHEMA in this module.
Must NOT:         Import app.domain; contain the decision-file contract
                  (app.core.runs.gates owns it).
Dependencies:     app.core.runs.gates, app.core.runs.run_resolve,
                  app.core.trust.identity, app.core.config.
Reason To Change: Gate tool arguments or result shape change.

Trust: ``approve`` through MCP requires GRAPHYN_MCP_HUMAN_APPROVAL=1 (same
switch as accept_proposal) so an agent cannot approve its own gate by
default; ``reject`` is always allowed. The actor is the name mapped to
``_meta.auth_token`` (GRAPHYN_API_TOKENS → actor_verified=true); otherwise
``mcp:<actor arg>`` with actor_verified=false.
"""
from __future__ import annotations

from typing import Any

from app.mcp.handlers.journey.common import handler_error, meta_props

LIST_PENDING_GATES_DESCRIPTION = (
    "List human approval gates (hitl_approve nodes) of a run, or all runs that are "
    "currently waiting on one. Returns node_id, prompt, status, waiting_since, timeout."
)
LIST_PENDING_GATES_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "description": "Run id (or unique prefix ≥ 8). Omit to scan running runs."},
        "include_decided": {"type": "boolean", "description": "Also return non-pending gates (with run_id only)."},
        "limit": {"type": "integer", "description": "Max running runs to scan when run_id is omitted (default 50)."},
        **meta_props(),
    },
    "additionalProperties": False,
}

DECIDE_GATE_DESCRIPTION = (
    "Approve or reject a pending human approval gate of a run. 'approve' requires "
    "GRAPHYN_MCP_HUMAN_APPROVAL=1; 'reject' is always allowed. Audited as gate.decision."
)
DECIDE_GATE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "run_id": {"type": "string"},
        "node_id": {"type": "string"},
        "decision": {"type": "string", "enum": ["approve", "reject"]},
        "comment": {"type": "string", "description": "Reason (required when the gate sets reason_required)."},
        "role": {"type": "string", "description": "Approver role when the gate restricts approver_roles."},
        "actor": {"type": "string", "description": "Claimed actor when the token is not mapped to a name."},
        **meta_props(),
    },
    "required": ["run_id", "node_id", "decision"],
    "additionalProperties": False,
}


def _resolve_run_dir(raw: str):
    from app.core.config import runs_dir
    from app.core.runs.run_resolve import resolve_run_id

    root = runs_dir()
    return root / resolve_run_id(root, raw)


def list_pending_gates_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.runs.gates import list_gates, pending_gates
    from app.core.runs.run_status import load_durable_status

    args = arguments or {}
    run_id = str(args.get("run_id") or "").strip()
    if run_id:
        try:
            run_dir = _resolve_run_dir(run_id)
        except Exception as exc:
            return handler_error("not_found", str(exc) or f"Run '{run_id}' not found")
        gates = list_gates(run_dir) if args.get("include_decided") else pending_gates(run_dir)
        return {"run_id": run_dir.name, "gates": gates, "count": len(gates)}

    from app.core.config import runs_dir

    limit = max(1, min(int(args.get("limit") or 50), 500))
    out: list[dict[str, Any]] = []
    scanned = 0
    try:
        entries = sorted(runs_dir().iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        entries = []
    for entry in entries:
        if scanned >= limit:
            break
        if not entry.is_dir() or load_durable_status(entry) != "running":
            continue
        scanned += 1
        for gate in pending_gates(entry):
            out.append({"run_id": entry.name, **gate})
    return {"gates": out, "count": len(out), "runs_scanned": scanned}


def decide_gate_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.config import mcp_human_approval_enabled
    from app.core.runs.gates import GateError, decide_gate
    from app.core.trust.identity import identity_from_credentials

    args = arguments or {}
    decision = str(args.get("decision") or "").strip().lower()
    if decision == "approve" and not mcp_human_approval_enabled():
        return handler_error(
            "capability_denied",
            "Approving a gate via MCP is disabled. Set GRAPHYN_MCP_HUMAN_APPROVAL=1, "
            "or approve in the console / REST API.",
        )
    run_id = str(args.get("run_id") or "").strip()
    node_id = str(args.get("node_id") or "").strip()
    if not run_id or not node_id:
        return handler_error("missing_argument", "decide_gate requires run_id and node_id")
    try:
        run_dir = _resolve_run_dir(run_id)
    except Exception as exc:
        return handler_error("not_found", str(exc) or f"Run '{run_id}' not found")
    token = ((args.get("_meta") or {}).get("auth_token") or "") if isinstance(args.get("_meta"), dict) else ""
    claimed = args.get("actor") if isinstance(args.get("actor"), str) else None
    ident = identity_from_credentials(str(token) or None, claimed)
    if ident.get("token_mapped"):
        actor, verified = str(ident["actor"]), True
    else:
        actor, verified = f"mcp:{(claimed or 'agent').strip()[:100] or 'agent'}", False
    try:
        gate = decide_gate(
            run_dir,
            node_id,
            decision=decision,
            comment=args.get("comment") if isinstance(args.get("comment"), str) else None,
            role=args.get("role") if isinstance(args.get("role"), str) else None,
            actor=actor,
            actor_verified=verified,
            claimed_actor=ident.get("claimed_actor"),
            source="mcp",
        )
    except GateError as exc:
        return handler_error(exc.code, exc.message)
    return {"ok": True, "run_id": run_dir.name, "gate": gate}
