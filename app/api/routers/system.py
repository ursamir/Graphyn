# app/api/routers/system.py
"""System API — health, cleanup, webhooks, and projects-registry endpoints."""
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


@router.post("/cleanup", summary="Clean up old runs and cache")
def cleanup(body: CleanupRequest = CleanupRequest()):
    """Delete run directories older than older_than_days and optionally cache entries."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=body.older_than_days)
    runs_deleted = 0
    cache_deleted = 0
    bytes_freed = 0

    runs_root = _runs_dir()
    cache_root = _cache_dir()

    if runs_root.exists():
        for entry in runs_root.iterdir():
            if not entry.is_dir():
                continue
            # Check mtime of the run directory
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

    return {
        "deleted": runs_deleted + cache_deleted,
        "runs_deleted": runs_deleted,
        "cache_entries_deleted": cache_deleted,
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
