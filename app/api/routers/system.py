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

import threading
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.actor import resolve_actor
from app.core.config import runs_dir as _runs_dir, cache_dir as _cache_dir
from app.domain.project_manager import ProjectManager
from app.core.notify.webhook import WebhookService
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
    """Return readiness status with dependency checks (Wave B ready/signals)."""
    from app.core.host.readiness import readiness_snapshot

    # Probe endpoint: always fresh (guarded GETs use the short-TTL cache).
    return readiness_snapshot(max_age_s=0)


@router.get("/metrics", summary="In-process API metrics snapshot")
def metrics_snapshot():
    """Return lightweight in-process API metrics."""
    return snapshot_metrics()


# ── Cleanup ───────────────────────────────────────────────────────────────────

class CleanupRequest(BaseModel):
    older_than_days: int = Field(7, ge=0)
    delete_cache: bool = False
    delete_artifacts: bool = False
    keep_latest: bool = True
    reconcile_abandoned: bool = True
    stale_after_hours: float = Field(1.0, ge=0)


_CLEANUP_LOCK = threading.Lock()


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
    from app.core.runs.run_cleanup import cleanup_workspace

    if not _CLEANUP_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Cleanup is already running. Wait for it to finish.",
        )
    try:
        result = cleanup_workspace(
            older_than_days=body.older_than_days,
            delete_cache=body.delete_cache,
            delete_artifacts=body.delete_artifacts,
            keep_latest=body.keep_latest,
            reconcile_abandoned=body.reconcile_abandoned,
            stale_after_hours=body.stale_after_hours,
        )
    finally:
        _CLEANUP_LOCK.release()
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor="api",
            action="system.cleanup",
            resource_type="workspace",
            resource_id="cleanup",
            meta={
                "older_than_days": body.older_than_days,
                "delete_cache": body.delete_cache,
                "delete_artifacts": body.delete_artifacts,
                **{
                    k: result.get(k)
                    for k in (
                        "runs_deleted",
                        "cache_entries_deleted",
                        "artifacts_deleted",
                        "blobs_deleted",
                    )
                    if isinstance(result, dict)
                },
            },
        )
    except Exception:
        pass
    return result


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
    url: str = ""
    events: list[str] = []
    resource_version: Optional[str] = None
    keep_url: bool = False


@router.get("/webhooks", summary="Get webhook configuration")
def get_webhooks():
    """Return webhook configuration with URL redacted (host/path only)."""
    from fastapi.responses import JSONResponse
    from app.api.concurrency import etag_value

    cfg = _webhook_svc.public_config()
    resp = JSONResponse(content=cfg)
    if cfg.get("resource_version") is not None:
        resp.headers["ETag"] = etag_value(cfg["resource_version"])
    return resp


@router.put("/webhooks", summary="Set webhook configuration")
def set_webhooks(body: WebhookBody, request: Request):
    """Save webhook configuration.

    Supports ``If-Match`` / ``resource_version`` (API-CONV-005).
    """
    from fastapi.responses import JSONResponse
    from app.api.concurrency import (
        etag_value,
        resolve_expected_version,
        version_conflict_http,
    )
    from app.core.errors import VersionConflict

    expected, via_if_match = resolve_expected_version(request, body.resource_version)
    if expected is not None:
        current = str(_webhook_svc.load().get("resource_version") or "0")
        if str(expected) != current:
            raise version_conflict_http(
                VersionConflict(via_if_match=via_if_match, current=current)
            )
    try:
        url_to_save = _webhook_svc.url_for_save(body.url, keep_url=body.keep_url)
        cfg = _webhook_svc.save(url_to_save, body.events)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    from app.core.trust.egress import redact_webhook_url_for_api

    redacted_url = redact_webhook_url_for_api(str(cfg.get("url") or ""))
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="webhook.set",
            resource_type="webhook",
            resource_id=(redacted_url[:64] if redacted_url else "webhook"),
            meta={"events": list(body.events or []), "url_configured": bool(str(cfg.get("url") or "").strip())},
            request_id=getattr(request.state, "request_id", None),
        )
    except Exception:
        pass
    out = {
        "ok": True,
        "url": redacted_url,
        "url_configured": bool(str(cfg.get("url") or "").strip()),
        "events": cfg.get("events") if isinstance(cfg, dict) else body.events,
        **{
            k: cfg.get(k)
            for k in ("resource_version", "secret_name")
            if isinstance(cfg, dict)
        },
    }
    resp = JSONResponse(content=out)
    if out.get("resource_version") is not None:
        resp.headers["ETag"] = etag_value(out["resource_version"])
    return resp


@router.post("/webhooks/test", summary="Send a test webhook notification")
def test_webhook(request: Request):
    """Fire a test event to the configured webhook URL."""
    from app.core.trust.egress import redact_webhook_url_for_api

    config = _webhook_svc.load()
    url = config.get("url")
    if not url:
        return {"ok": False, "reason": "No webhook URL configured"}
    reason = _webhook_svc.deliver_now("test", {"message": "Test notification from Graphyn"})
    redacted_url = redact_webhook_url_for_api(str(url))
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="webhook.test",
            resource_type="webhook",
            resource_id=redacted_url[:64] or "webhook",
            meta={},
        )
    except Exception:
        pass
    return {"ok": reason is None, "url": redacted_url, "url_configured": True, **({"reason": reason} if reason else {})}


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
    env: str = Field("prod", description="draft | staging | prod")


class ScheduleEnabledBody(BaseModel):
    enabled: bool = True


@router.get("/schedules", summary="List interval schedules")
def get_schedules(
    project: str | None = Query(None, description="Only schedules for this project"),
):
    from app.core.pipelines.schedules import (
        SchedulesDataError,
        list_schedules,
        normalize_schedule,
    )

    try:
        return {
            "schedules": [
                normalize_schedule(i) for i in list_schedules(project=project or None)
            ]
        }
    except SchedulesDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/schedules", summary="Create an interval schedule")
def post_schedule(body: ScheduleCreateBody, request: Request):
    """Create schedule. Honors Idempotency-Key (API-CONV-004)."""
    from app.api.idempotency import begin_idempotent, complete_idempotent, idempotency_guard
    from app.core.pipelines.schedules import (
        SchedulesDataError,
        create_schedule,
        normalize_schedule,
    )

    cached = begin_idempotent(
        request, body=body.model_dump(), route="POST /api/v1/system/schedules"
    )
    if cached is not None:
        return cached

    with idempotency_guard(request):
        try:
            item = create_schedule(
                name=body.name,
                project=body.project,
                pipeline=body.pipeline,
                interval_minutes=body.interval_minutes,
                enabled=body.enabled,
                env=body.env,
            )
            item = normalize_schedule(item)
        except SchedulesDataError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            from app.core.trust.audit import record_audit

            record_audit(
                actor=resolve_actor(request),
                action="schedule.create",
                resource_type="schedule",
                resource_id=item["id"],
                meta={"name": body.name, "project": body.project, "pipeline": body.pipeline},
            )
        except Exception:
            pass
        complete_idempotent(request, status_code=200, body=item)
    return item


@router.post("/schedules/tick", summary="Tick due schedules (ops)")
def tick_schedules(request: Request):
    """Fire any enabled schedules whose next_run_at is due."""
    from app.core.pipelines.schedules import SchedulesDataError, tick_due_schedules

    try:
        fired = tick_due_schedules()
    except SchedulesDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        from app.core.trust.audit import record_audit

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
    from app.core.pipelines.schedules import SchedulesDataError, delete_schedule

    try:
        delete_schedule(schedule_id)
    except SchedulesDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    try:
        from app.core.trust.audit import record_audit

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
    from app.core.pipelines.schedules import (
        SchedulesDataError,
        normalize_schedule,
        set_schedule_enabled,
    )

    try:
        item = set_schedule_enabled(schedule_id, body.enabled)
    except SchedulesDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="schedule.enable" if body.enabled else "schedule.disable",
            resource_type="schedule",
            resource_id=schedule_id,
            meta={"enabled": body.enabled},
        )
    except Exception:
        pass
    return normalize_schedule(item)


class ScheduleEnvBody(BaseModel):
    env: str = Field("draft", description="draft | staging | prod")


@router.post("/schedules/{schedule_id}/env", summary="Set the environment a schedule runs")
def schedule_env(schedule_id: str, body: ScheduleEnvBody, request: Request):
    from app.core.pipelines.schedules import SchedulesDataError, set_schedule_env

    try:
        item = set_schedule_env(schedule_id, body.env)
    except SchedulesDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="schedule.env",
            resource_type="schedule",
            resource_id=schedule_id,
            meta={"env": item.get("env")},
        )
    except Exception:
        pass
    return item


@router.post("/schedules/{schedule_id}/run", summary="Run a schedule immediately")
def run_schedule(schedule_id: str, request: Request):
    from app.core.pipelines.schedules import SchedulesDataError, run_schedule_now

    try:
        item = run_schedule_now(schedule_id)
    except SchedulesDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        from app.core.trust.audit import record_audit

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

class NotificationsMarkBody(BaseModel):
    ids: list[str] = Field(default_factory=list)
    all: bool = False


@router.get("/notifications", summary="List in-app notifications")
def get_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Return newest-first in-app notifications (run/ops events)."""
    from app.core.notify.in_app_notify import list_notifications

    return list_notifications(unread_only=unread_only, limit=limit, offset=offset)


@router.post("/notifications/mark-read", summary="Mark in-app notifications read")
def post_notifications_mark_read(body: NotificationsMarkBody, request: Request):
    """Mark selected notification ids as read, or all when ``all`` is true."""
    from app.core.trust.audit import record_audit
    from app.core.notify.in_app_notify import mark_read

    result = mark_read(body.ids, all_read=bool(body.all))
    try:
        record_audit(
            actor=resolve_actor(request),
            action="notifications.mark_read",
            resource_type="notification",
            resource_id="all" if body.all else ",".join((body.ids or [])[:8]) or "none",
            meta={"marked": result.get("marked"), "all": bool(body.all)},
        )
    except Exception:
        pass
    return result
