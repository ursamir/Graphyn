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
Must NOT:         Contain cleanup or webhook logic — delegate to ArtifactStore,
                  WebhookService, and ProjectManager.
Dependencies:     fastapi, app.core.{artifact_store, webhook, config},
                  app.domain.project_manager, stdlib (shutil, datetime).
Reason To Change: New system endpoint added, or cleanup policy changes.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.config import runs_dir as _runs_dir, cache_dir as _cache_dir
from app.domain.project_manager import ProjectManager
from app.core.webhook import WebhookService

router = APIRouter(prefix="/system", tags=["system"])

_pm = ProjectManager()
_webhook_svc = WebhookService()


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", summary="Health check")
def health_check():
    """Return service health status."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ── Cleanup ───────────────────────────────────────────────────────────────────

class CleanupRequest(BaseModel):
    older_than_days: int = 7
    delete_cache: bool = True
    delete_artifacts: bool = False


@router.post("/cleanup", summary="Clean up old runs and cache")
def cleanup(body: CleanupRequest = CleanupRequest()):
    """Delete run directories older than older_than_days, optionally cache and artifact entries."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=body.older_than_days)
    runs_deleted = 0
    cache_deleted = 0
    artifacts_deleted = 0
    bytes_freed = 0

    runs_root = _runs_dir()
    cache_root = _cache_dir()

    if runs_root.exists():
        for entry in runs_root.iterdir():
            if not entry.is_dir():
                continue
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                for f in entry.rglob("*"):
                    if f.is_file():
                        bytes_freed += f.stat().st_size
                shutil.rmtree(entry)
                runs_deleted += 1

    if body.delete_cache and cache_root.exists():
        for entry in cache_root.iterdir():
            if not entry.is_dir():
                continue
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                for f in entry.rglob("*"):
                    if f.is_file():
                        bytes_freed += f.stat().st_size
                shutil.rmtree(entry)
                cache_deleted += 1

    if body.delete_artifacts:
        from app.core.artifact_store import ArtifactStore
        result = ArtifactStore().cleanup(older_than_days=body.older_than_days)
        artifacts_deleted = result["entries_deleted"]
        bytes_freed += result["bytes_freed"]

    return {
        "deleted": runs_deleted + cache_deleted + artifacts_deleted,
        "runs_deleted": runs_deleted,
        "cache_entries_deleted": cache_deleted,
        "artifacts_deleted": artifacts_deleted,
        "bytes_freed": bytes_freed,
        "older_than_days": body.older_than_days,
    }


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
