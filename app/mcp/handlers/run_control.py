# app/mcp/handlers/run_control.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   pause_run, resume_run, cancel_run tool handlers. Thin
                  delegation to the active run registry.
Owns:             handle_pause_run, handle_resume_run, handle_cancel_run
                  and their SCHEMA/DESCRIPTION constants.
Public Surface:   All three handler functions above.
Must NOT:         Contain run lifecycle logic — delegates entirely to
                  get_active_run(run_id).pause/resume/cancel().
                  Must not import from app.domain.
Dependencies:     BC6 (run_control.get_active_run — module-level import).
Reason To Change: run_control tool schemas change, or new control operations
                  are added (e.g. step, restart).
"""
from app.core.run_control import get_active_run

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


def handle_pause_run(arguments: dict) -> dict:
    run_id = arguments.get("run_id", "")
    run = get_active_run(run_id)
    if run is None:
        return {"error": True, "error_type": "run_not_active", "message": f"Run '{run_id}' is not active", "run_id": run_id}
    run.pause()
    return {"run_id": run_id, "status": "paused"}


def handle_resume_run(arguments: dict) -> dict:
    run_id = arguments.get("run_id", "")
    run = get_active_run(run_id)
    if run is None:
        return {"error": True, "error_type": "run_not_active", "message": f"Run '{run_id}' is not active", "run_id": run_id}
    run.resume()
    return {"run_id": run_id, "status": "running"}


def handle_cancel_run(arguments: dict) -> dict:
    run_id = arguments.get("run_id", "")
    run = get_active_run(run_id)
    if run is None:
        return {"error": True, "error_type": "run_not_active", "message": f"Run '{run_id}' is not active", "run_id": run_id}
    run.cancel()
    return {"run_id": run_id, "status": "cancelled"}
