# app/api/routers/system.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for system health, cleanup, webhook
                  configuration, and projects registry.
Owns:             Route definitions for GET /system/health,
                  POST /system/cleanup,
                  GET/PUT /system/webhooks,
                  POST /system/webhooks/test,
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

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

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
    """Return readiness status with minimal dependency checks."""
    return {
        "status": "ready",
        "timestamp": datetime.now(timezone.utc).isoformat(),
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


@router.post("/cleanup", summary="Clean up old runs and cache")
def cleanup(body: CleanupRequest = CleanupRequest()):
    """Delete finished run journals older than older_than_days.

    ``older_than_days=0`` deletes all finished runs (completed/failed/cancelled).
    Currently running/paused runs are never deleted. When ``keep_latest`` is
    true (default), the run that ``latest/`` still points at is kept, including
    its ``workspace/artifacts/<slug>/runs/<id>`` folder.

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
def set_webhooks(body: WebhookBody):
    """Save webhook configuration."""
    _webhook_svc.save(body.url, body.events)
    return {"ok": True, "url": body.url, "events": body.events}


@router.post("/webhooks/test", summary="Send a test webhook notification")
def test_webhook():
    """Fire a test event to the configured webhook URL."""
    config = _webhook_svc.load()
    url = config.get("url")
    if not url:
        return {"ok": False, "reason": "No webhook URL configured"}
    _webhook_svc.notify("test", {"message": "Test notification from Graphyn"})
    return {"ok": True, "url": url}
