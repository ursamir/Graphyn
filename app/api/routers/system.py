# app/api/routers/system.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for system health, cleanup, webhook
                  configuration, and projects registry.
Owns:             Route definitions for GET /system/health,
                  POST /system/cleanup,
                  GET/PUT /system/webhooks,
                  POST /system/webhooks/test,
                  GET/POST /system/schedules,
                  GET /system/auth-status,
                  GET /system/projects-registry.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain cleanup or webhook logic — delegate to run_cleanup,
                  WebhookService, and ProjectManager.
Dependencies:     fastapi, app.core.{run_cleanup, webhook, config},
                  app.domain.project_manager, stdlib (datetime).
Reason To Change: New system endpoint added, or cleanup policy changes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.actor import resolve_actor
from app.core.config import runs_dir as _runs_dir, cache_dir as _cache_dir
from app.domain.project_manager import ProjectManager
from app.core.webhook import WebhookService
from app.api.observability import snapshot_metrics

router = APIRouter(prefix="/system", tags=["system"])

_pm = ProjectManager()
_webhook_svc = WebhookService()


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", summary="Health check")
def health_check():
    """Return service health status."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/readiness", summary="Readiness check")
def readiness_check():
    """Return readiness status with minimal dependency checks.

    Includes backend mode (local vs distributed) and registered worker count so
    the console System page can surface Mode A/B without guessing.
    """
    import os

    backend_id = (os.environ.get("GRAPHYN_BACKEND") or "local_python").strip() or "local_python"
    backend_mode = "distributed" if backend_id == "distributed" else "local"
    worker_count = 0
    try:
        from app.core.distributed.registry import get_worker_registry

        worker_count = len(get_worker_registry().list(include_stale=True))
    except Exception:
        worker_count = 0
    return {
        "status": "ready",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backend": backend_id,
        "backend_mode": backend_mode,
        "worker_count": worker_count,
        "checks": {
            "runs_dir_exists": _runs_dir().exists(),
            "cache_dir_exists": _cache_dir().exists(),
        },
    }


@router.get("/metrics", summary="In-process API metrics snapshot")
def metrics_snapshot():
    """Return lightweight in-process API metrics."""
    return snapshot_metrics()


# ── Cleanup ───────────────────────────────────────────────────────────────────

class CleanupRequest(BaseModel):
    older_than_days: int = Field(7, ge=0)
    delete_cache: bool = True
    delete_artifacts: bool = False
    keep_latest: bool = True
    reconcile_abandoned: bool = True
    stale_after_hours: float = Field(1.0, ge=0)


@router.post("/cleanup", summary="Clean up old runs and cache")
def cleanup(body: CleanupRequest = CleanupRequest()):
    """Delete finished run journals older than older_than_days.

    ``older_than_days=0`` deletes all finished runs (completed/failed/cancelled).
    Currently running/paused runs are never deleted. When ``keep_latest`` is
    true (default), the run that ``latest/`` still points at is kept, including
    its ``workspace/artifacts/<slug>/runs/<id>`` folder.

    By default (``reconcile_abandoned=true``), RUNNING/QUEUED journals with no
    active worker/lease and age > ``stale_after_hours`` are marked ``failed``
    with reason ``stale_reconciled`` before deletion policy runs. Journals are
    never deleted by reconcile alone.

    Optional cache cleanup applies the same age cutoff under ``cache/``.
    When ``delete_artifacts`` is true, matching
    ``{project_dir}/artifacts/<slug>/runs/<run_id>/`` folders are removed too.
    ``examples/`` and ``datasets/input`` are never touched. Deletion is jailed
    to ``runs/``, ``cache/``, and ``artifacts/`` under the project dir.
    """
    from app.core.run_cleanup import cleanup_workspace

    return cleanup_workspace(
        older_than_days=body.older_than_days,
        delete_cache=body.delete_cache,
        delete_artifacts=body.delete_artifacts,
        keep_latest=body.keep_latest,
        reconcile_abandoned=body.reconcile_abandoned,
        stale_after_hours=body.stale_after_hours,
    )


# ── Projects registry ─────────────────────────────────────────────────────────

@router.get("/projects-registry", summary="List dataset projects")
def get_projects_registry(
    q: Optional[str] = Query(None, description="Substring search on project name"),
    status: Optional[str] = Query(None, description="Filter by project status"),
):
    """Return a searchable list of all dataset projects."""
    projects = _pm.list_all()
    if q:
        q_lower = q.lower()
        projects = [p for p in projects if q_lower in p.get("name", "").lower()]
    if status:
        projects = [p for p in projects if p.get("status") == status]
    return projects


# ── Webhooks ──────────────────────────────────────────────────────────────────

class WebhookBody(BaseModel):
    url: str
    events: list[str] = []


@router.get("/webhooks", summary="Get webhook configuration")
def get_webhooks():
    """Return the current webhook configuration."""
    return _webhook_svc.load()


@router.put("/webhooks", summary="Set webhook configuration")
def set_webhooks(body: WebhookBody, request: Request):
    """Save webhook configuration."""
    _webhook_svc.save(body.url, body.events)
    try:
        from app.core.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="webhook.set",
            resource_type="webhook",
            resource_id=body.url[:64] or "webhook",
            meta={"events": list(body.events or [])},
        )
    except Exception:
        pass
    return {"ok": True, "url": body.url, "events": body.events}


@router.post("/webhooks/test", summary="Send a test webhook notification")
def test_webhook(request: Request):
    """Fire a test event to the configured webhook URL."""
    config = _webhook_svc.load()
    url = config.get("url")
    if not url:
        return {"ok": False, "reason": "No webhook URL configured"}
    _webhook_svc.notify("test", {"message": "Test notification from Graphyn"})
    try:
        from app.core.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="webhook.test",
            resource_type="webhook",
            resource_id=str(url)[:64],
            meta={},
        )
    except Exception:
        pass
    return {"ok": True, "url": url}


# ── Auth status (honesty banner) ──────────────────────────────────────────────

@router.get("/auth-status", summary="Auth configuration (no secrets)")
def auth_status():
    """Return whether Bearer auth is required and whether a token is configured.

    Does not reveal the token value. Safe for UI banners.
    """
    from app.core.config import api_token, auth_required, graphyn_env

    token = api_token()
    required = auth_required()
    return {
        "auth_required": required,
        "token_configured": bool(token),
        "env": graphyn_env(),
        "ok": (not required) or bool(token),
    }


# ── Schedules (always-on lite) ────────────────────────────────────────────────

class ScheduleCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    project: str = Field(..., min_length=1, max_length=64)
    pipeline: str = Field(..., min_length=1, max_length=64)
    interval_minutes: int = Field(60, ge=1, le=43200)
    enabled: bool = True


class ScheduleEnabledBody(BaseModel):
    enabled: bool = True


@router.get("/schedules", summary="List interval schedules")
def get_schedules():
    from app.core.schedules import list_schedules

    return {"schedules": list_schedules()}


@router.post("/schedules", summary="Create an interval schedule")
def post_schedule(body: ScheduleCreateBody, request: Request):
    from app.core.schedules import create_schedule

    try:
        item = create_schedule(
            name=body.name,
            project=body.project,
            pipeline=body.pipeline,
            interval_minutes=body.interval_minutes,
            enabled=body.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        from app.core.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="schedule.create",
            resource_type="schedule",
            resource_id=item["id"],
            meta={"name": body.name, "project": body.project, "pipeline": body.pipeline},
        )
    except Exception:
        pass
    return item


@router.post("/schedules/tick", summary="Tick due schedules (ops)")
def tick_schedules(request: Request):
    """Fire any enabled schedules whose next_run_at is due."""
    from app.core.schedules import tick_due_schedules

    fired = tick_due_schedules()
    try:
        from app.core.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="schedule.tick",
            resource_type="schedule",
            resource_id="tick",
            meta={"fired": len(fired)},
        )
    except Exception:
        pass
    return {"fired": fired, "count": len(fired)}


@router.delete("/schedules/{schedule_id}", summary="Delete a schedule")
def remove_schedule(schedule_id: str, request: Request):
    from app.core.schedules import delete_schedule

    try:
        delete_schedule(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    try:
        from app.core.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="schedule.delete",
            resource_type="schedule",
            resource_id=schedule_id,
            meta={},
        )
    except Exception:
        pass
    return {"ok": True, "id": schedule_id}


@router.post("/schedules/{schedule_id}/enable", summary="Enable or disable a schedule")
def enable_schedule(schedule_id: str, body: ScheduleEnabledBody, request: Request):
    from app.core.schedules import set_schedule_enabled

    try:
        item = set_schedule_enabled(schedule_id, body.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    try:
        from app.core.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="schedule.enable" if body.enabled else "schedule.disable",
            resource_type="schedule",
            resource_id=schedule_id,
            meta={"enabled": body.enabled},
        )
    except Exception:
        pass
    return item


@router.post("/schedules/{schedule_id}/run", summary="Run a schedule immediately")
def run_schedule(schedule_id: str, request: Request):
    from app.core.schedules import run_schedule_now

    try:
        item = run_schedule_now(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        from app.core.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="schedule.run",
            resource_type="schedule",
            resource_id=schedule_id,
            meta={"last_run_id": item.get("last_run_id")},
        )
    except Exception:
        pass
    return item
