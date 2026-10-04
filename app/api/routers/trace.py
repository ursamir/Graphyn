# app/api/routers/trace.py
"""
Bounded Context:  REST API Layer
Responsibility:   Unified Trace (backtrack) and thin audit log endpoints.
Owns:             GET /trace, GET /audit (offset / run_id / resource_id / action / q
                  filters over the whole log; total + has_more).
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain storage logic — delegate to app.core.runs.trace / audit.
Dependencies:     fastapi, app.core.runs.trace, app.core.trust.audit,
                  app.api.run_ids (run_id prefix resolution).
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
    from app.core.runs.trace import assemble_trace

    if run_id and run_id.strip():
        from app.api.run_ids import resolve_run_id_http

        # Unique prefix >= 8 → full id; ambiguous → 409 run_id_ambiguous.
        # Unknown ids still return a partial payload (``run_not_found`` warning).
        run_id = resolve_run_id_http(run_id, allow_missing=True)
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


@router.get("/audit", summary="List / search audit events")
def get_audit(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0, description="Skip this many matching events (newest first)"),
    run_id: str | None = Query(None, description="Events of this run (full id or prefix >= 8), incl. replays of it"),
    resource_id: str | None = Query(None, description="Exact resource id (or prefix >= 8)"),
    action: str | None = Query(None, description="Exact action, or 'run.*' prefix"),
    q: str | None = Query(None, description="Case-insensitive free-text search over the event"),
):
    """Newest-first append-only audit events, filtered and paged over the whole log."""
    from app.core.trust.audit import list_audit

    events, total = list_audit(
        limit=limit, offset=offset, run_id=run_id, resource_id=resource_id,
        action=action, q=q, with_total=True,
    )
    return {
        "events": events,
        "limit": limit,
        "offset": offset,
        "total": total,
        "has_more": offset + len(events) < total,
    }
