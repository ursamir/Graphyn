# app/api/routers/run_control.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for runtime control of pipeline runs —
                  pause, resume, cancel — enforcing SRS §13.2 Current×Action.
Owns:             Route definitions for POST /runs/{run_id}/pause,
                  POST /runs/{run_id}/resume,
                  POST /runs/{run_id}/cancel.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain run control logic beyond transition gating —
                  delegate signals to get_active_run() / RunManager.
Dependencies:     fastapi, app.core.runs.run_control, app.core.runs.run_status,
                  app.core.config, app.core.runs.run_journal (durable cancel marker).
Reason To Change: Transition matrix or run_id validation changes (unique
                  prefixes >= 8 chars resolve via app.api.run_ids).

Illegal transitions → 409 error.code=invalid_transition (RT-SM-001).
Cancel on already-cancelled → 200 idempotent ack.
Resume on terminal (succeeded/failed/cancelled) → 409.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.actor import resolve_actor
from app.core.config import runs_dir as _runs_dir
from app.core.runs.run_control import get_active_run, is_active_on_another_worker
from app.core.runs.run_status import (
    InvalidTransition,
    TERMINAL_STATUSES,
    load_durable_status,
    next_status,
    normalize_status,
)

router = APIRouter(prefix="/runs", tags=["run-control"])


def _validate_run_id(run_id: str) -> str:
    """Raise HTTP 400 if run_id contains invalid characters; return the full id.

    A unique prefix >= 8 chars resolves to the full run id (ambiguous → 409
    ``run_id_ambiguous``); unknown ids pass through so the handlers keep their
    ``run_not_found`` / ``run_not_active`` semantics.
    """
    sanitized = run_id.replace("-", "")
    if not sanitized or not sanitized.isalnum():
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_run_id", "run_id": run_id, "message": "Invalid run_id"},
        )
    from app.api.run_ids import resolve_run_id_http

    try:
        root = _runs_dir()
    except Exception:
        return run_id
    return resolve_run_id_http(run_id, allow_missing=True, runs_root=root)


def _run_dir(run_id: str):
    return _runs_dir() / run_id


def _durable_status(run_id: str) -> str | None:
    try:
        return load_durable_status(_run_dir(run_id))
    except Exception:
        return None


def _invalid_transition(run_id: str, current: str, action: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "error": "invalid_transition",
            "message": f"Cannot {action} run in status={current}",
            "run_id": run_id,
            "resource_type": "run",
            "current_status": current,
            "action": action,
        },
    )


def _run_not_found_error(run_id: str) -> HTTPException:
    try:
        run_path = _run_dir(run_id)
        error_code = "run_not_active" if run_path.exists() else "run_not_found"
    except Exception:
        error_code = "run_not_active"
    return HTTPException(
        status_code=404,
        detail={"error": error_code, "run_id": run_id, "message": error_code},
    )


def _run_elsewhere_error(run_id: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "error": "run_active_on_another_worker",
            "run_id": run_id,
            "message": "Run is active on another worker",
        },
    )




@router.post("/{run_id}/pause")
def pause_run(run_id: str):
    """Pause an active pipeline run after the current node completes."""
    run_id = _validate_run_id(run_id)
    status = _durable_status(run_id)
    if status is not None:
        try:
            next_status(status, "pause")
        except InvalidTransition as exc:
            raise _invalid_transition(run_id, exc.current, "pause") from exc
    run = get_active_run(run_id)
    if run is None:
        if is_active_on_another_worker(run_id):
            raise _run_elsewhere_error(run_id)
        # Durable status said pause was legal (e.g. running) but process gone
        if status is not None and status in ("running", "pending"):
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "run_not_active",
                    "message": "Run status is non-terminal but executor is not in this process",
                    "run_id": run_id,
                },
            )
        raise _run_not_found_error(run_id)
    try:
        run.pause()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to pause run: {exc}") from exc
    return {"run_id": run_id, "status": "paused"}


@router.post("/{run_id}/resume")
def resume_run(run_id: str):
    """Resume a paused pipeline run. Terminal statuses → 409 invalid_transition."""
    run_id = _validate_run_id(run_id)
    status = _durable_status(run_id)
    if status is not None:
        try:
            next_status(status, "resume")
        except InvalidTransition as exc:
            raise _invalid_transition(run_id, exc.current, "resume") from exc

    run = get_active_run(run_id)
    if run is None:
        if is_active_on_another_worker(run_id):
            raise _run_elsewhere_error(run_id)
        if status is not None and status in TERMINAL_STATUSES:
            raise _invalid_transition(run_id, status, "resume")
        raise _run_not_found_error(run_id)
    try:
        run.resume()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to resume run: {exc}") from exc
    return {"run_id": run_id, "status": "running"}


@router.post("/{run_id}/cancel")
def cancel_run(run_id: str, request: Request):
    """Cancel an active/paused/pending run; already-cancelled → 200 idempotent."""
    run_id = _validate_run_id(run_id)
    status = _durable_status(run_id)

    if status is not None:
        try:
            next_status(status, "cancel")
        except InvalidTransition as exc:
            raise _invalid_transition(run_id, exc.current, "cancel") from exc
        # Idempotent cancel on already-cancelled
        if normalize_status(status) == "cancelled":
            return {"run_id": run_id, "status": "cancelled", "idempotent": True}

    run = get_active_run(run_id)
    if run is None:
        if is_active_on_another_worker(run_id):
            raise _run_elsewhere_error(run_id)
        # Durable cancelled already handled above; terminal other → 409 already
        if status is not None and normalize_status(status) == "cancelled":
            return {"run_id": run_id, "status": "cancelled", "idempotent": True}
        # pending/running on disk but no active process: still mark cancelled
        if status in ("pending", "running", "paused"):
            # Durable cancel marker first: an executor that has not started
            # yet (queued) or runs in another process polls it and refuses to
            # start / stops between nodes. It is never rewritten, so a racing
            # meta.json read-modify-write cannot lose the cancel.
            try:
                from app.core.runs.run_journal import write_cancel_marker

                write_cancel_marker(str(_run_dir(run_id)))
            except Exception:
                pass
            try:
                # Best-effort: write cancelled into existing meta (only while
                # still non-terminal — never clobber succeeded/failed).
                meta_path = _run_dir(run_id) / "meta.json"
                if meta_path.exists():
                    import json
                    import os
                    import tempfile
                    from datetime import datetime, timezone

                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    current = normalize_status(meta.get("status"))
                    if current not in TERMINAL_STATUSES:
                        meta["status"] = "cancelled"
                        meta["duration_s"] = meta.get("duration_s") or 0
                        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
                        fd, tmp = tempfile.mkstemp(
                            prefix=".meta.", suffix=".tmp", dir=str(meta_path.parent)
                        )
                        with os.fdopen(fd, "w", encoding="utf-8") as f:
                            json.dump(meta, f, indent=2)
                        os.replace(tmp, meta_path)
                        from app.core.runs.run_notify import notify_run_terminal

                        notify_run_terminal(
                            "cancelled",
                            run_id,
                            graph_name=meta.get("graph_name") if isinstance(meta.get("graph_name"), str) else None,
                            project=meta.get("project") if isinstance(meta.get("project"), str) else None,
                        )
            except Exception:
                pass
            try:
                from app.core.trust.audit import record_audit

                record_audit(
                    actor=resolve_actor(request),
                    action="run.cancel",
                    resource_type="run",
                    resource_id=run_id,
                    meta={"offline": True},
                )
            except Exception:
                pass
            return {"run_id": run_id, "status": "cancelled"}
        raise _run_not_found_error(run_id)
    try:
        run.cancel()
        # Durable cancel stamp (RunManager.cancel sets event; orchestrator marks)
        try:
            run.mark_cancelled()
        except Exception:
            pass
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to cancel run: {exc}") from exc
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="run.cancel",
            resource_type="run",
            resource_id=run_id,
            meta={},
        )
    except Exception:
        pass
    return {"run_id": run_id, "status": "cancelled"}
