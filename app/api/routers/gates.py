# app/api/routers/gates.py
"""
Bounded Context:  REST API Layer
Responsibility:   Human approval gates of a run (``hitl_approve`` nodes):
                  list gates and record a token-bound human decision.
Owns:             GET /runs/{run_id}/gates, POST /runs/{run_id}/gates/{node_id}/decision.
Public Surface:   router — mounted at /api/v1 in app/api/main.py (bearer auth).
Must NOT:         Contain the decision-file contract (app.core.runs.gates).
Dependencies:     fastapi, app.core.runs.gates, app.api.actor, app.api.routers.runs (_run_dir).
Reason To Change: Gate API contract changes.
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/runs", tags=["runs"])


class GateDecisionBody(BaseModel):
    decision: Literal["approve", "reject"]
    comment: Optional[str] = Field(None, max_length=4000)
    role: Optional[str] = Field(None, max_length=128, description="Approver role (checked against approver_roles when the gate sets them)")


def _run_dir(run_id: str):
    from app.api.routers.runs import _run_dir as runs_dir

    return runs_dir(run_id)


@router.get("/{run_id}/gates", summary="List approval gates of a run")
def list_run_gates(run_id: str, pending_only: bool = Query(False, description="Only gates waiting for a decision")):
    """``{run_id, run_status, awaiting_approval, gates: [...]}``."""
    from app.core.runs.gates import list_gates
    from app.core.runs.run_status import load_durable_status

    run_path = _run_dir(run_id)
    gates = list_gates(run_path)
    if pending_only:
        gates = [g for g in gates if g["status"] == "pending"]
    return {
        "run_id": run_path.name,
        "run_status": load_durable_status(run_path) or "unknown",
        "awaiting_approval": any(g["status"] == "pending" for g in gates),
        "gates": gates,
    }


@router.post("/{run_id}/gates/{node_id}/decision", summary="Approve or reject a pending gate")
def decide_run_gate(run_id: str, node_id: str, request: Request, body: GateDecisionBody = Body(...)):
    """Writes the decision the ``hitl_approve`` node polls for. Actor is bound to the bearer token."""
    from app.api.actor import resolve_identity
    from app.core.runs.gates import GateError, decide_gate

    run_path = _run_dir(run_id)
    ident = resolve_identity(request)
    try:
        gate = decide_gate(
            run_path,
            node_id,
            decision=body.decision,
            comment=body.comment,
            role=body.role,
            actor=str(ident.get("actor") or "unidentified"),
            actor_verified=bool(ident.get("actor_verified")),
            claimed_actor=ident.get("claimed_actor"),
            source="api",
        )
    except GateError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})
    return {"run_id": run_path.name, "gate": gate}
