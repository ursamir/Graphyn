# app/api/routers/run_control.py
"""Runtime control endpoints — pause, resume, cancel active pipeline runs.

Req 7.5, 7.6
"""
from fastapi import APIRouter, HTTPException
from app.core.run_control import get_active_run

router = APIRouter(prefix="/runs", tags=["run-control"])


@router.post("/{run_id}/pause")
async def pause_run(run_id: str):
    """Pause an active pipeline run after the current node completes."""
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
    run = get_active_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "run_not_active", "run_id": run_id},
        )
    run.cancel()
    return {"run_id": run_id, "status": "cancelled"}
