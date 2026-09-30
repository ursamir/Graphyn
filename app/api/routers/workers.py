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
Dependencies:     fastapi, starlette.concurrency, pydantic,
                  app.core.distributed.*, app.core.config, stdlib (pathlib, hashlib).
Reason To Change: New worker/job endpoints, heartbeat protocol (active_job_ids),
                  or artifact transfer protocol (blob key authz / integrity).
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
from starlette.concurrency import run_in_threadpool

from app.core.distributed.models import (
    JobResult,
    NodeJob,
    WorkerInfo,
    WorkerResources,
    WorkerStatus,
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
    status: WorkerStatus | None = None
    active_jobs: int | None = None
    active_job_ids: list[str] | None = Field(
        None,
        description=(
            "Jobs this worker instance is actively running. When present only "
            "these leases are renewed; omitted = legacy renew-all (deprecated)."
        ),
    )


class ClaimBody(BaseModel):
    worker_id: str


class JobEventsBody(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)


# ── Workers ───────────────────────────────────────────────────────────────────


def _split_ids(raw: Optional[str]) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


@router.post("/workers/register", summary="Register or refresh a worker")
def register_worker(
    info: WorkerInfo,
    active_job_ids: Optional[str] = Query(
        None,
        description=(
            "Comma-separated jobs this instance is still running (re-register "
            "after a 404). Every other job claimed under this worker_id is "
            "requeued with a bumped lease_generation."
        ),
    ),
):
    """Register a worker instance in the durable registry (disk/Redis).

    Registration always means *a new worker instance*: jobs previously
    claimed under the same ``worker_id`` (e.g. before a crash/restart) are
    released back to the queue unless listed in ``active_job_ids``.
    """
    _validate_worker_id(info.worker_id)
    stored = get_worker_registry().register(info)
    released: list[str] = []
    try:
        released = get_job_queue().release_jobs_for_worker(
            info.worker_id, keep_job_ids=_split_ids(active_job_ids)
        )
    except Exception as exc:
        log.warning(
            "workers.register: releasing stale claims for %s failed: %s",
            info.worker_id,
            exc,
        )
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor="worker",
            action="worker.register",
            resource_type="worker",
            resource_id=info.worker_id,
            meta={
                "labels": list(getattr(info, "labels", None) or []),
                "pools": list(getattr(info, "pools", None) or []),
            },
        )
    except Exception as exc:
        log.warning(
            "workers.register: audit record failed for %s: %s",
            info.worker_id,
            exc,
        )
    out = stored.model_dump(mode="json")
    if released:
        out["released_job_ids"] = released
    return out


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
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # Heartbeat renews leases: only ``active_job_ids`` when sent (v2), else
    # every job claimed by this worker id (legacy, logs a deprecation).
    try:
        queue = get_job_queue()
        if body.active_job_ids is None:
            queue.renew_leases_for_worker(worker_id)
        else:
            queue.renew_leases_for_worker(worker_id, active_job_ids=body.active_job_ids)
    except Exception as exc:
        log.warning(
            "workers.heartbeat: lease renew failed for worker %s: %s",
            worker_id,
            exc,
        )
        raise HTTPException(
            status_code=503,
            detail=f"Lease renew failed for worker {worker_id}: {exc}",
        )
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
def get_job(
    job_id: str,
    worker_id: Optional[str] = Query(
        None,
        description=(
            "Accepted for compatibility; ignored. GET is read-only and never "
            "renews leases — workers renew via heartbeat active_job_ids."
        ),
    ),
):
    queue = get_job_queue()
    job = queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    result = queue.get_result(job_id)
    return {
        "job": job.model_dump(mode="json"),
        "result": result.model_dump(mode="json") if result else None,
        "run_paused": queue.is_run_paused(str(job.run_id or "")),
    }


# ── Artifact blobs (P1 HTTP transfer) ─────────────────────────────────────────


_MAX_BLOB_UPLOAD_BYTES = 100 * 1024 * 1024
_BLOB_CHUNK_BYTES = 1024 * 1024


def _authorize_blob_key(key: Optional[str], worker_id: Optional[str]) -> None:
    """Enforce explicit-key rules for blob uploads (raises HTTPException).

    * omitted key → content-addressed ``sha256/…`` (always allowed);
    * ``sha256/…`` explicit keys are rejected (server derives them);
    * ``jobs/<job_id>/g<gen>/<port>`` requires ``worker_id`` to hold the
      job's *current* claim at exactly that generation;
    * any other explicit key is rejected.
    """
    from app.core.distributed.transfer import parse_job_output_key

    if not key:
        return
    k = key.lstrip("/")
    if not _BLOB_KEY_RE.match(k) or ".." in k.split("/"):
        raise HTTPException(status_code=400, detail="Invalid blob key")
    if k.startswith("sha256/"):
        raise HTTPException(
            status_code=400,
            detail="Explicit sha256/ keys are not allowed; omit key for content addressing",
        )
    parsed = parse_job_output_key(k)
    if parsed is None:
        raise HTTPException(
            status_code=400,
            detail="Explicit blob keys must be jobs/<job_id>/g<generation>/<port>",
        )
    job_seg, gen = parsed
    if not worker_id:
        raise HTTPException(
            status_code=403, detail="worker_id is required for jobs/ blob keys"
        )
    job = get_job_queue().get(job_seg)
    if (
        job is None
        or job.status not in ("claimed", "running")
        or job.claimed_by != worker_id
        or int(job.lease_generation or 0) != gen
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Worker {worker_id!r} does not hold job {job_seg!r} at "
                f"generation g{gen}"
            ),
        )


@router.post("/artifacts/blob", summary="Upload an artifact blob")
async def put_artifact_blob(
    request: Request,
    key: Optional[str] = Query(None, description="Optional explicit key (jobs/… only)"),
    worker_id: Optional[str] = Query(
        None, description="Uploading worker (required for jobs/<job>/g<gen>/ keys)"
    ),
):
    """Store raw bytes (write-once); returns ``artifact://local/{key}`` + sha256.

    If ``key`` is omitted, a sha256 content-addressed key is used. Explicit
    keys follow :func:`_authorize_blob_key`. Existing blobs are never
    overwritten (identical bytes → idempotent 200, different → 409).
    Hashing and disk writes run in a threadpool, off the event loop.
    """
    from app.core.artifacts.artifact_uri import parse_artifact_uri
    from app.core.distributed.transfer import put_blob_with_digest

    worker_id = worker_id or request.headers.get("x-graphyn-worker-id") or None
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_BLOB_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Upload too large")
        except ValueError:
            pass
    await run_in_threadpool(_authorize_blob_key, key, worker_id)

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > _MAX_BLOB_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Upload too large")
        chunks.append(chunk)
    if not total:
        raise HTTPException(status_code=400, detail="Empty body")

    def _store() -> tuple[str, str, int]:
        body = b"".join(chunks)
        # Re-check the claim right before writing (lease may have moved).
        _authorize_blob_key(key, worker_id)
        uri, digest = put_blob_with_digest(body, key=key)
        return uri, digest, len(body)

    try:
        uri, digest, size = await run_in_threadpool(_store)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    parsed = parse_artifact_uri(uri)
    return {"uri": uri, "key": parsed.key, "sha256": digest, "bytes": size}


@router.get("/artifacts/blob/{key:path}", summary="Download an artifact blob")
def get_artifact_blob(key: str):
    """Serve a blob; ``sha256/`` keys are verified before serving (409 on mismatch)."""
    from app.core.distributed.transfer import sha256_from_key, blob_root

    key = (key or "").lstrip("/")
    if not key or not _BLOB_KEY_RE.match(key) or ".." in key.split("/"):
        raise HTTPException(status_code=400, detail="Invalid blob key")
    path = blob_root() / key
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Blob not found")
    expected = sha256_from_key(key)
    if expected:
        hasher = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(_BLOB_CHUNK_BYTES), b""):
                hasher.update(chunk)
        actual = hasher.hexdigest()
        if not actual.startswith(expected):
            log.error("get_artifact_blob: corrupt blob %s (sha256 %s)", key, actual)
            raise HTTPException(status_code=409, detail="Blob content hash mismatch")
    return FileResponse(path, filename=path.name)
