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
Dependencies:     fastapi, app.core.run_control, app.core.config.
Reason To Change: New run control action added, or run_id validation changes.

Req 7.5, 7.6
"""
from fastapi import APIRouter, HTTPException
from app.core.run_control import get_active_run
from app.core.config import runs_dir as _runs_dir

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


def _run_not_found_error(run_id: str) -> HTTPException:
    """Return 404 with a detail that distinguishes 'never existed' from 'not active'.

    Checks the run journal directory: if a run directory exists for run_id it
    was once active but has since completed or been deregistered →
    "run_not_active".  If no directory exists → "run_not_found".
    """
    try:
        run_path = _runs_dir() / run_id
        error_code = "run_not_active" if run_path.exists() else "run_not_found"
    except Exception:
        # Config unavailable — fall back to generic code.
        error_code = "run_not_active"
    return HTTPException(
        status_code=404,
        detail={"error": error_code, "run_id": run_id},
    )


@router.post("/{run_id}/pause")
def pause_run(run_id: str):
    """Pause an active pipeline run after the current node completes.

    Declared as a sync handler so FastAPI runs it in a thread pool — avoids
    blocking the event loop on the threading.Lock inside get_active_run().
    """
    _validate_run_id(run_id)
    run = get_active_run(run_id)
    if run is None:
        raise _run_not_found_error(run_id)
    try:
        run.pause()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to pause run: {exc}") from exc
    return {"run_id": run_id, "status": "paused"}


@router.post("/{run_id}/resume")
def resume_run(run_id: str):
    """Resume a paused pipeline run.

    Declared as a sync handler so FastAPI runs it in a thread pool — avoids
    blocking the event loop on the threading.Lock inside get_active_run().
    """
    _validate_run_id(run_id)
    run = get_active_run(run_id)
    if run is None:
        raise _run_not_found_error(run_id)
    try:
        run.resume()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to resume run: {exc}") from exc
    return {"run_id": run_id, "status": "running"}


@router.post("/{run_id}/cancel")
def cancel_run(run_id: str):
    """Cancel an active (or paused) pipeline run after the current node completes.

    Declared as a sync handler so FastAPI runs it in a thread pool — avoids
    blocking the event loop on the threading.Lock inside get_active_run().
    """
    _validate_run_id(run_id)
    run = get_active_run(run_id)
    if run is None:
        raise _run_not_found_error(run_id)
    try:
        run.cancel()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to cancel run: {exc}") from exc
    return {"run_id": run_id, "status": "cancelled"}
