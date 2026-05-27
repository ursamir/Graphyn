# app/mcp/handlers/run_control.py
"""
Bounded Context:  MCP Server
Responsibility:   pause_run, resume_run, cancel_run tool handlers. Thin
                  delegation to the active run registry.
Owns:             handle_pause_run, handle_resume_run, handle_cancel_run
                  and their SCHEMA/DESCRIPTION constants.
Public Surface:   All three handler functions above.
Must NOT:         Contain run lifecycle logic — delegates entirely to
                  get_active_run(run_id).pause/resume/cancel().
                  Must not import from app.domain.
Dependencies:     BC6 (run_control.get_active_run — module-level import),
                  app.core.config.runs_dir (for run-dir existence check).
Reason To Change: run_control tool schemas change, or new control operations
                  are added (e.g. step, restart).
"""
from app.core.run_control import get_active_run
from app.core.config import runs_dir as _runs_dir

PAUSE_RUN_DESCRIPTION = "Pause an active pipeline run after the current node completes."
PAUSE_RUN_SCHEMA = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "description": "The run ID to pause."},
    },
    "required": ["run_id"],
}

RESUME_RUN_DESCRIPTION = "Resume a paused pipeline run."
RESUME_RUN_SCHEMA = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "description": "The run ID to resume."},
    },
    "required": ["run_id"],
}

CANCEL_RUN_DESCRIPTION = "Cancel an active or paused pipeline run after the current node completes."
CANCEL_RUN_SCHEMA = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "description": "The run ID to cancel."},
    },
    "required": ["run_id"],
}


def _run_not_active_error(run_id: str) -> dict:
    """Return a structured error distinguishing 'completed' from 'never existed'.

    Mirrors the logic in app/api/routers/run_control.py::_run_not_found_error.
    """
    try:
        run_path = _runs_dir() / run_id
        if run_path.exists():
            msg = f"Run '{run_id}' has already completed or is not active in this process."
        else:
            msg = f"Run '{run_id}' is not active and no run directory was found."
    except Exception:
        msg = f"Run '{run_id}' is not active."
    return {"error": True, "error_type": "run_not_active", "message": msg, "run_id": run_id}


def handle_pause_run(arguments: dict) -> dict:
    run_id = arguments.get("run_id", "")
    if not run_id:
        return {"error": True, "error_type": "missing_argument", "message": "run_id is required"}
    run = get_active_run(run_id)
    if run is None:
        return _run_not_active_error(run_id)
    try:
        run.pause()
    except OSError as exc:
        return {"error": True, "error_type": "run_control_error",
                "message": f"Failed to persist pause state: {exc}", "run_id": run_id}
    return {"run_id": run_id, "status": "pause_requested",
            "message": "Pause signal sent. Run will pause after current node completes."}


def handle_resume_run(arguments: dict) -> dict:
    run_id = arguments.get("run_id", "")
    if not run_id:
        return {"error": True, "error_type": "missing_argument", "message": "run_id is required"}
    run = get_active_run(run_id)
    if run is None:
        return _run_not_active_error(run_id)
    try:
        run.resume()
    except OSError as exc:
        return {"error": True, "error_type": "run_control_error",
                "message": f"Failed to persist resume state: {exc}", "run_id": run_id}
    return {"run_id": run_id, "status": "running"}


def handle_cancel_run(arguments: dict) -> dict:
    run_id = arguments.get("run_id", "")
    if not run_id:
        return {"error": True, "error_type": "missing_argument", "message": "run_id is required"}
    run = get_active_run(run_id)
    if run is None:
        return _run_not_active_error(run_id)
    run.cancel()
    return {"run_id": run_id, "status": "cancel_requested",
            "message": "Cancel signal sent. Run will stop after current node completes."}
