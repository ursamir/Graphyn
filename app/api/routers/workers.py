# app/api/routers/workers.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for distributed worker registration,
                  heartbeats, job claim/complete/events/cancel, and optional
                  HTTP artifact blob put/get for cross-machine transfer.
                  Mode B WAVE-1/2: worker-scoped token ACL, blob GET authz +
                  signed URLs, admin PATCH for plugin ACL / trust / max_claimed,
                  usage counters, encrypt-at-rest blob GET, audit hooks.
Owns:             Routes under /workers, /jobs, and /artifacts/blob.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py.
Must NOT:         Contain scheduling policy — delegate to
                  app.core.distributed.*.
Dependencies:     fastapi, starlette.concurrency, pydantic,
                  app.core.distributed.*, app.core.config, app.core.trust.*,
                  stdlib (pathlib, hashlib).
Reason To Change: New worker/job endpoints, heartbeat protocol (active_job_ids),
                  or artifact transfer protocol (blob key authz / integrity).
"""
from __future__ import annotations

import hashlib
import logging
import re
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


def _audit(action: str, *, resource_type: str, resource_id: str, meta: dict | None = None) -> None:
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor="api",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            meta=meta or {},
        )
    except Exception as exc:
        log.warning("workers.audit %s failed for %s: %s", action, resource_id, exc)


def _enforce_worker_acl(request: Request, worker_id: str | None) -> None:
    """Fail closed: worker-scoped tokens / mTLS certs may only act as their id.

    When neither token auth nor an mTLS worker identity is present (plain lab
    HTTP), ACL is a no-op. When mTLS cert identity is bound, enforce even
    without bearer tokens.
    """
    from app.core.trust.identity import (
        current_identity,
        token_auth_configured,
        worker_route_allowed,
    )

    ident = current_identity()
    mtls_bound = bool(ident and ident.get("mtls_worker_id"))
    if not token_auth_configured() and not mtls_bound:
        return
    if not worker_route_allowed(worker_id):
        raise HTTPException(
            status_code=403,
            detail="Worker-scoped token/cert cannot act as this worker_id",
        )


def _require_operator(request: Request) -> None:
    """Admin mutations require a non-worker token when auth is configured."""
    from app.core.trust.identity import is_operator_identity, token_auth_configured

    if not token_auth_configured():
        return
    if not is_operator_identity():
        raise HTTPException(status_code=403, detail="Operator token required")


def _worker_id_from_request(
    request: Request,
    *,
    body_worker_id: str | None = None,
    query_worker_id: str | None = None,
    path_worker_id: str | None = None,
) -> str | None:
    return (
        path_worker_id
        or body_worker_id
        or query_worker_id
        or request.headers.get("x-graphyn-worker-id")
        or None
    )


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
    content_hashes: dict[str, str] | None = Field(
        None,
        description="Optional node_type → sha256 advertisement refresh.",
    )


class ClaimBody(BaseModel):
    worker_id: str


class JobEventsBody(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)


class WorkerPatchBody(BaseModel):
    allowed_plugins: list[str] | None = None
    plugin_hashes: dict[str, str] | None = None
    trusted: bool | None = None
    labels: list[str] | None = None
    pools: list[str] | None = None
    node_types: list[str] | None = None
    max_claimed: int | None = None


# ── Workers ───────────────────────────────────────────────────────────────────


def _split_ids(raw: Optional[str]) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


@router.post("/workers/register", summary="Register or refresh a worker")
def register_worker(
    request: Request,
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
    _enforce_worker_acl(request, info.worker_id)
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
    _audit(
        "worker.register",
        resource_type="worker",
        resource_id=info.worker_id,
        meta={
            "labels": list(getattr(info, "labels", None) or []),
            "pools": list(getattr(info, "pools", None) or []),
            "trusted": bool(getattr(stored, "trusted", True)),
        },
    )
    out = stored.model_dump(mode="json")
    if released:
        out["released_job_ids"] = released
    return out


@router.post("/workers/{worker_id}/heartbeat", summary="Worker heartbeat")
def worker_heartbeat(
    request: Request, worker_id: str, body: HeartbeatBody = HeartbeatBody()
):
    _validate_worker_id(worker_id)
    _enforce_worker_acl(request, worker_id)
    try:
        stored = get_worker_registry().heartbeat(
            worker_id,
            resources=body.resources,
            status=body.status,
            active_jobs=body.active_jobs,
        )
        if body.content_hashes is not None:
            stored = get_worker_registry().patch(
                worker_id, content_hashes=dict(body.content_hashes)
            )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown worker {worker_id}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
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
    from app.core.distributed.quotas import parse_pool_max_claimed, usage_snapshot

    workers = get_worker_registry().list(include_stale=include_stale)
    pool_limits = parse_pool_max_claimed()
    out = []
    for w in workers:
        row = w.model_dump(mode="json")
        row["usage"] = usage_snapshot(w)
        if pool_limits:
            row["pool_max_claimed"] = {
                p: pool_limits[p] for p in (w.pools or []) if p in pool_limits
            }
        out.append(row)
    return out


@router.get("/workers/remote-node-types", summary="List remote-advertised node types")
def list_remote_node_types(include_stale: bool = Query(False)):
    """Type names advertised by registered workers (plugins ∪ node_types)."""
    from app.core.distributed.registry import known_remote_node_types

    return {"node_types": sorted(known_remote_node_types(include_stale=include_stale))}


@router.patch("/workers/{worker_id}", summary="Update worker ACL / trust fields")
def patch_worker(request: Request, worker_id: str, body: WorkerPatchBody):
    _validate_worker_id(worker_id)
    _require_operator(request)
    # exclude_unset so omitted fields stay untouched; explicit null clears ACL lists.
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to patch")
    try:
        prev = get_worker_registry().get(worker_id)
        stored = get_worker_registry().patch(worker_id, **fields)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown worker {worker_id}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if "trusted" in fields and prev is not None and bool(prev.trusted) != bool(stored.trusted):
        _audit(
            "worker.trust",
            resource_type="worker",
            resource_id=worker_id,
            meta={"trusted": bool(stored.trusted), "previous": bool(prev.trusted)},
        )
    else:
        _audit(
            "worker.patch",
            resource_type="worker",
            resource_id=worker_id,
            meta={"fields": sorted(fields.keys())},
        )
    return stored.model_dump(mode="json")


@router.delete("/workers/{worker_id}", summary="Deregister a worker")
def delete_worker(request: Request, worker_id: str):
    _validate_worker_id(worker_id)
    _require_operator(request)
    removed = get_worker_registry().remove(worker_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Unknown worker {worker_id}")
    _audit("worker.deregister", resource_type="worker", resource_id=worker_id)
    return {"ok": True, "worker_id": worker_id}


# ── Jobs ──────────────────────────────────────────────────────────────────────


@router.post("/jobs/claim", summary="Claim next eligible job")
def claim_job(request: Request, body: ClaimBody):
    _validate_worker_id(body.worker_id)
    _enforce_worker_acl(request, body.worker_id)
    worker = get_worker_registry().get(body.worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail=f"Unknown worker {body.worker_id}")
    if get_worker_registry().is_stale(worker):
        raise HTTPException(status_code=409, detail="Worker is stale; heartbeat first")
    # Fail fast on quota before scanning (claim also skips under CAS).
    from app.core.distributed.quotas import QuotaExceeded, assert_claim_quota, record_usage

    try:
        assert_claim_quota(worker)
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    job = get_job_queue().claim(worker)
    if job is None:
        return {"job": None}
    record_usage(body.worker_id, claims=1)
    _audit(
        "job.claim",
        resource_type="job",
        resource_id=job.job_id,
        meta={
            "worker_id": body.worker_id,
            "node_type": job.node_type,
            "run_id": job.run_id,
        },
    )
    return {"job": job.model_dump(mode="json")}


@router.post("/jobs/{job_id}/complete", summary="Report job result")
def complete_job(request: Request, job_id: str, result: JobResult):
    if result.job_id and result.job_id != job_id:
        raise HTTPException(status_code=400, detail="job_id mismatch")
    wid = _worker_id_from_request(request, body_worker_id=result.worker_id)
    _enforce_worker_acl(request, wid)
    from app.core.distributed.security import redact_job_result_payload

    result = redact_job_result_payload(result.model_copy(update={"job_id": job_id}))
    try:
        job = get_job_queue().complete(result)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if result.worker_id:
        from app.core.distributed.quotas import record_usage

        record_usage(result.worker_id, completes=1)
    _audit(
        "job.complete",
        resource_type="job",
        resource_id=job_id,
        meta={
            "worker_id": result.worker_id,
            "status": result.status,
            "run_id": getattr(job, "run_id", None),
        },
    )
    return {"job": job.model_dump(mode="json"), "result": result.model_dump(mode="json")}


@router.post("/jobs/{job_id}/events", summary="Append job log events")
def job_events(request: Request, job_id: str, body: JobEventsBody):
    job = get_job_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    wid = _worker_id_from_request(
        request, body_worker_id=getattr(job, "claimed_by", None)
    )
    _enforce_worker_acl(request, wid)
    from app.core.distributed.security import redact_job_events

    events = redact_job_events(body.events)
    try:
        count = get_job_queue().append_events(job_id, events)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    return {"job_id": job_id, "event_count": count}


@router.post("/jobs/{job_id}/cancel", summary="Cancel a job")
def cancel_job(request: Request, job_id: str):
    _require_operator(request)
    try:
        job = get_job_queue().cancel(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    _audit(
        "job.cancel",
        resource_type="job",
        resource_id=job_id,
        meta={"run_id": getattr(job, "run_id", None)},
    )
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


def _authorize_blob_get(
    request: Request,
    key: str,
    *,
    exp: Optional[str],
    sig: Optional[str],
    worker_id: Optional[str],
) -> None:
    """GET authz: operator OR claim holder (job keys) OR valid signed URL."""
    from app.core.distributed.transfer import (
        parse_job_output_key,
        verify_signed_blob_url,
    )
    from app.core.trust.identity import (
        is_operator_identity,
        token_auth_configured,
    )

    if verify_signed_blob_url(key, exp=exp, sig=sig, method="GET"):
        return

    if not token_auth_configured():
        # Unauthenticated-dev: keep lab Mode B working without signed URLs.
        return

    if is_operator_identity():
        return

    # Worker-scoped: only job-scoped keys while holding the claim.
    parsed = parse_job_output_key(key)
    if parsed is None:
        raise HTTPException(
            status_code=403,
            detail="Blob GET requires operator token or a valid signed URL",
        )
    job_seg, gen = parsed
    wid = worker_id or request.headers.get("x-graphyn-worker-id")
    _enforce_worker_acl(request, wid)
    job = get_job_queue().get(job_seg)
    if (
        job is None
        or job.status not in ("claimed", "running")
        or job.claimed_by != wid
        or int(job.lease_generation or 0) != gen
    ):
        raise HTTPException(
            status_code=403,
            detail="Worker does not hold claim for this blob key",
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
    _enforce_worker_acl(request, worker_id)
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
    if worker_id:
        from app.core.distributed.quotas import record_usage

        record_usage(worker_id, bytes_out=size)
    _audit(
        "blob.put",
        resource_type="blob",
        resource_id=parsed.key[:128],
        meta={
            "sha256": digest,
            "bytes": size,
            "worker_id": worker_id,
            "job_id": (parse_job_id_from_key(parsed.key) if key else None),
        },
    )
    return {"uri": uri, "key": parsed.key, "sha256": digest, "bytes": size}


def parse_job_id_from_key(key: str) -> str | None:
    from app.core.distributed.transfer import parse_job_output_key

    parsed = parse_job_output_key(key)
    return parsed[0] if parsed else None


@router.get("/artifacts/blob/{key:path}", summary="Download an artifact blob")
def get_artifact_blob(
    request: Request,
    key: str,
    exp: Optional[str] = Query(None),
    sig: Optional[str] = Query(None),
    worker_id: Optional[str] = Query(None),
):
    """Serve plaintext blob bytes; ``sha256/`` keys verified after decrypt.

    On-disk files may be GBE1 envelopes when ``GRAPHYN_BLOB_ENCRYPTION_KEY``
    is set; callers always receive plaintext. Authz (when auth configured):
    operator bearer, OR worker holding the job-scoped claim, OR a valid HMAC
    signed URL (``exp`` + ``sig``).
    """
    from fastapi.responses import Response

    from app.core.artifacts.artifact_uri import LOCAL_STORE_ID, build_artifact_uri
    from app.core.distributed.blob_crypto import BlobCryptoError
    from app.core.distributed.transfer import (
        BlobIntegrityError,
        get_blob,
        sha256_from_key,
    )

    key = (key or "").lstrip("/")
    if not key or not _BLOB_KEY_RE.match(key) or ".." in key.split("/"):
        raise HTTPException(status_code=400, detail="Invalid blob key")
    _authorize_blob_get(request, key, exp=exp, sig=sig, worker_id=worker_id)
    uri = build_artifact_uri(LOCAL_STORE_ID, key)
    try:
        data = get_blob(uri)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Blob not found")
    except BlobIntegrityError as exc:
        log.error("get_artifact_blob: corrupt blob %s: %s", key, exc)
        raise HTTPException(status_code=409, detail="Blob content hash mismatch") from exc
    except BlobCryptoError as exc:
        raise HTTPException(status_code=500, detail=f"Blob decrypt failed: {exc}") from exc
    wid = worker_id or request.headers.get("x-graphyn-worker-id")
    if wid:
        from app.core.distributed.quotas import record_usage

        record_usage(str(wid), bytes_in=len(data))
    expected = sha256_from_key(key)
    _audit(
        "blob.get",
        resource_type="blob",
        resource_id=key[:128],
        meta={
            "sha256": expected,
            "bytes": len(data),
            "worker_id": wid,
            "job_id": parse_job_id_from_key(key),
            "signed": bool(sig),
        },
    )
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Length": str(len(data))},
    )


@router.post("/artifacts/blob/sign", summary="Mint a short-lived signed blob URL")
def sign_artifact_blob(
    request: Request,
    key: str = Query(..., description="Blob key to sign"),
    ttl_s: Optional[int] = Query(None),
):
    """Operator helper: mint ``exp``+``sig`` for GET (or return relative URL)."""
    _require_operator(request)
    from app.core.distributed.transfer import mint_signed_blob_url

    k = (key or "").lstrip("/")
    if not k or not _BLOB_KEY_RE.match(k) or ".." in k.split("/"):
        raise HTTPException(status_code=400, detail="Invalid blob key")
    try:
        url = mint_signed_blob_url(k, method="GET", ttl_s=ttl_s)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"key": k, "signed_path": url}
