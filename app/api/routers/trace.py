# app/api/routers/trace.py
"""
Bounded Context:  REST API Layer
Responsibility:   Unified Trace (backtrack) and thin audit log endpoints.
Owns:             GET /trace, GET /audit.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain storage logic — delegate to app.core.trace / audit.
Dependencies:     fastapi, app.core.trace, app.core.audit.
Reason To Change: Trace/audit response schema changes or new query modes.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["trace"])


@router.get("/trace", summary="Unified backtrack Trace payload")
def get_trace(
    artifact_id: Optional[str] = Query(None, description="Artifact to backtrack from"),
    run_id: Optional[str] = Query(None, description="Run to backtrack from"),
    node_id: Optional[str] = Query(None, description="Optional node focus within the run"),
):
    """Return artifact → node → run → graph → worker chain.

    Partial payloads are returned when pieces are missing (see ``warnings``).
    """
    if not artifact_id and not run_id:
        raise HTTPException(
            status_code=400,
            detail="Provide artifact_id and/or run_id query parameters",
        )
    from app.core.trace import assemble_trace

    try:
        return assemble_trace(artifact_id=artifact_id, run_id=run_id, node_id=node_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/trace/{kind}/{id}", summary="Trace by kind/id path")
def get_trace_by_path(kind: str, id: str, node_id: Optional[str] = Query(None)):
    """Convenience path form: ``/trace/artifact/{id}`` or ``/trace/run/{id}``."""
    kind_norm = kind.strip().lower()
    if kind_norm in ("artifact", "artifacts"):
        return get_trace(artifact_id=id, run_id=None, node_id=node_id)
    if kind_norm in ("run", "runs"):
        return get_trace(artifact_id=None, run_id=id, node_id=node_id)
    raise HTTPException(status_code=400, detail="kind must be 'artifact' or 'run'")


@router.get("/audit", summary="List recent audit events")
def get_audit(limit: int = Query(100, ge=1, le=1000)):
    """Return newest-first append-only audit events (thin seed)."""
    from app.core.audit import list_audit

    return {"events": list_audit(limit=limit), "limit": limit}
