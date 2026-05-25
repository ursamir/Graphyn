# app/api/routers/run_control.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for runtime control of active pipeline runs —
                  pause, resume, cancel.
Owns:             Route definitions for POST /runs/{run_id}/pause,
                  POST /runs/{run_id}/resume,
                  POST /runs/{run_id}/cancel.
                  run_id validation helper (_validate_run_id).
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain run control logic — delegate to get_active_run()
                  from app.core.run_control.
Dependencies:     fastapi, app.core.run_control.
Reason To Change: New run control action added, or run_id validation changes.

Req 7.5, 7.6
"""
from fastapi import APIRouter, HTTPException
from app.core.run_control import get_active_run

router = APIRouter(prefix="/runs", tags=["run-control"])


def _validate_run_id(run_id: str) -> None:
    """Raise HTTP 400 if run_id contains invalid characters.

    NEW-9 fix: mirrors the alphanumeric + hyphen validation used in runs.py.
    Prevents path traversal and injection via run_id path parameter.
    """
    sanitized = run_id.replace("-", "")
    if not sanitized or not sanitized.isalnum():
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_run_id", "run_id": run_id},
        )


@router.post("/{run_id}/pause")
async def pause_run(run_id: str):
    """Pause an active pipeline run after the current node completes."""
    _validate_run_id(run_id)
    run = get_active_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "run_not_active", "run_id": run_id},
        )
    run.pause()
    return {"run_id": run_id, "status": "paused"}


@router.post("/{run_id}/resume")
async def resume_run(run_id: str):
    """Resume a paused pipeline run."""
    _validate_run_id(run_id)
    run = get_active_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "run_not_active", "run_id": run_id},
        )
    run.resume()
    return {"run_id": run_id, "status": "running"}


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Cancel an active (or paused) pipeline run after the current node completes."""
    _validate_run_id(run_id)
    run = get_active_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "run_not_active", "run_id": run_id},
        )
    run.cancel()
    return {"run_id": run_id, "status": "cancelled"}
