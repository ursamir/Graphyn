# app/api/routers/workers.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for distributed worker registration,
                  heartbeats, job claim/complete/events/cancel, and optional
                  HTTP artifact blob put/get for cross-machine transfer.
Owns:             Routes under /workers, /jobs, and /artifacts/blob.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py.
Must NOT:         Contain scheduling policy — delegate to
                  app.core.distributed.*.
Dependencies:     fastapi, pydantic, app.core.distributed.*, app.core.config,
                  stdlib (pathlib, hashlib).
Reason To Change: New worker/job endpoints, or artifact transfer protocol.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.distributed.models import (
    JobResult,
    NodeJob,
    WorkerInfo,
    WorkerResources,
)
from app.core.distributed.queue import get_job_queue
from app.core.distributed.registry import get_worker_registry

log = logging.getLogger(__name__)

router = APIRouter(tags=["distributed"])

_WORKER_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_BLOB_KEY_RE = re.compile(r"^[A-Za-z0-9_./-]+$")


def _validate_worker_id(worker_id: str) -> None:
    if not _WORKER_ID_RE.match(worker_id or ""):
        raise HTTPException(status_code=400, detail="Invalid worker_id")


# ── Request bodies ────────────────────────────────────────────────────────────


class HeartbeatBody(BaseModel):
    resources: WorkerResources | None = None
    status: str | None = None
    active_jobs: int | None = None


class ClaimBody(BaseModel):
    worker_id: str


class JobEventsBody(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)


# ── Workers ───────────────────────────────────────────────────────────────────


@router.post("/workers/register", summary="Register or refresh a worker")
def register_worker(info: WorkerInfo):
    """Register / refresh a worker in the durable registry (disk/Redis)."""
    _validate_worker_id(info.worker_id)
    stored = get_worker_registry().register(info)
    return stored.model_dump(mode="json")


@router.post("/workers/{worker_id}/heartbeat", summary="Worker heartbeat")
def worker_heartbeat(worker_id: str, body: HeartbeatBody = HeartbeatBody()):
    _validate_worker_id(worker_id)
    try:
        stored = get_worker_registry().heartbeat(
            worker_id,
            resources=body.resources,
            status=body.status,
            active_jobs=body.active_jobs,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown worker {worker_id}")
    # Heartbeat renews leases for jobs claimed by this worker (P2).
    try:
        get_job_queue().renew_leases_for_worker(worker_id)
    except Exception:
        pass
    return stored.model_dump(mode="json")


@router.get("/workers", summary="List workers")
def list_workers(include_stale: bool = Query(False)):
    workers = get_worker_registry().list(include_stale=include_stale)
    return [w.model_dump(mode="json") for w in workers]


@router.delete("/workers/{worker_id}", summary="Deregister a worker")
def delete_worker(worker_id: str):
    _validate_worker_id(worker_id)
    removed = get_worker_registry().remove(worker_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Unknown worker {worker_id}")
    return {"ok": True, "worker_id": worker_id}


# ── Jobs ──────────────────────────────────────────────────────────────────────


@router.post("/jobs/claim", summary="Claim next eligible job")
def claim_job(body: ClaimBody):
    _validate_worker_id(body.worker_id)
    worker = get_worker_registry().get(body.worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail=f"Unknown worker {body.worker_id}")
    if get_worker_registry().is_stale(worker):
        raise HTTPException(status_code=409, detail="Worker is stale; heartbeat first")
    job = get_job_queue().claim(worker)
    if job is None:
        return {"job": None}
    return {"job": job.model_dump(mode="json")}


@router.post("/jobs/{job_id}/complete", summary="Report job result")
def complete_job(job_id: str, result: JobResult):
    if result.job_id and result.job_id != job_id:
        raise HTTPException(status_code=400, detail="job_id mismatch")
    result = result.model_copy(update={"job_id": job_id})
    try:
        job = get_job_queue().complete(result)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"job": job.model_dump(mode="json"), "result": result.model_dump(mode="json")}


@router.post("/jobs/{job_id}/events", summary="Append job log events")
def job_events(job_id: str, body: JobEventsBody):
    try:
        count = get_job_queue().append_events(job_id, body.events)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    return {"job_id": job_id, "event_count": count}


@router.post("/jobs/{job_id}/cancel", summary="Cancel a job")
def cancel_job(job_id: str):
    try:
        job = get_job_queue().cancel(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    return job.model_dump(mode="json")


@router.get("/jobs/{job_id}", summary="Get job status")
def get_job(job_id: str):
    job = get_job_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    result = get_job_queue().get_result(job_id)
    return {
        "job": job.model_dump(mode="json"),
        "result": result.model_dump(mode="json") if result else None,
    }


# ── Artifact blobs (P1 HTTP transfer) ─────────────────────────────────────────


@router.post("/artifacts/blob", summary="Upload an artifact blob")
async def put_artifact_blob(
    request: Request,
    key: Optional[str] = Query(None, description="Optional explicit key"),
):
    """Store raw bytes; returns ``artifact://local/{key}``.

    If ``key`` is omitted, a sha256 content-addressed key is used.
    Delegates to :mod:`app.core.distributed.transfer` so control and
    in-process workers share one store layout.
    """
    from app.core.artifact_uri import parse_artifact_uri
    from app.core.distributed.transfer import put_blob

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty body")
    try:
        uri = put_blob(body, key=key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    parsed = parse_artifact_uri(uri)
    digest = hashlib.sha256(body).hexdigest()
    return {"uri": uri, "key": parsed.key, "sha256": digest, "bytes": len(body)}


@router.get("/artifacts/blob/{key:path}", summary="Download an artifact blob")
def get_artifact_blob(key: str):
    from app.core.artifact_uri import build_artifact_uri, LOCAL_STORE_ID
    from app.core.distributed.transfer import blob_root, get_blob

    key = (key or "").lstrip("/")
    if not key or not _BLOB_KEY_RE.match(key) or ".." in key.split("/"):
        raise HTTPException(status_code=400, detail="Invalid blob key")
    uri = build_artifact_uri(LOCAL_STORE_ID, key)
    try:
        data = get_blob(uri)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Blob not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    path = blob_root() / key
    if path.is_file():
        return FileResponse(path, filename=path.name)
    return Response(content=data, media_type="application/octet-stream")
