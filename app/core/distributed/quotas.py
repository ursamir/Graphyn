# app/core/distributed/quotas.py
"""
Bounded Context:  BC5 — Execution Runtime (Mode B WAVE-2)
Responsibility:   Pool / per-worker concurrent claim quotas and durable usage
                  counters (claims, completes, bytes in/out). Not multi-tenant
                  SaaS — single-operator pool limits only.
Owns:             parse_pool_max_claimed(), worker_at_quota(), pool_at_quota(),
                  count_active_claims(), record_usage(), usage_snapshot().
Public Surface:   Functions above + QuotaExceeded.
Must NOT:         Import app.api / app.domain / invent org tables.
Dependencies:     stdlib, app.core.distributed.models / registry / queue (lazy).
Reason To Change: Quota env syntax or usage metric set evolves.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

log = logging.getLogger(__name__)

_ENV_POOL = "GRAPHYN_POOL_MAX_CLAIMED"


class QuotaExceeded(RuntimeError):
    """Claim refused because a pool or worker concurrent quota was hit."""

    def __init__(self, message: str, *, kind: str = "worker") -> None:
        super().__init__(message)
        self.kind = kind


def parse_pool_max_claimed(raw: str | None = None) -> dict[str, int]:
    """Parse ``GRAPHYN_POOL_MAX_CLAIMED``.

    Accepts JSON ``{"gpu-lab": 2}`` or comma list ``gpu-lab=2,cpu=4``.
    """
    text = (raw if raw is not None else os.environ.get(_ENV_POOL) or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError as exc:
            log.warning("GRAPHYN_POOL_MAX_CLAIMED invalid JSON: %s", exc)
            return {}
        out: dict[str, int] = {}
        if isinstance(data, dict):
            for k, v in data.items():
                try:
                    n = int(v)
                except (TypeError, ValueError):
                    continue
                name = str(k or "").strip()
                if name and n >= 0:
                    out[name] = n
        return out
    out = {}
    for part in re.split(r"[,\s]+", text):
        if not part or "=" not in part:
            continue
        name, _, val = part.partition("=")
        name = name.strip()
        try:
            n = int(val.strip())
        except ValueError:
            continue
        if name and n >= 0:
            out[name] = n
    return out


def count_active_claims(
    *,
    worker_id: str | None = None,
    pool: str | None = None,
    jobs: list[Any] | None = None,
) -> int:
    """Count claimed/running jobs, optionally filtered by worker or pool."""
    if jobs is None:
        try:
            from app.core.distributed.queue import get_job_queue

            q = get_job_queue()
            jobs = q.list() if hasattr(q, "list") else list(getattr(q, "_jobs", {}).values())
        except Exception as exc:
            log.warning("count_active_claims: queue unavailable: %s", exc)
            return 0
    n = 0
    for job in jobs or []:
        status = getattr(job, "status", None) or (job.get("status") if isinstance(job, dict) else None)
        if status not in ("claimed", "running"):
            continue
        if worker_id is not None:
            claimed_by = getattr(job, "claimed_by", None) or (
                job.get("claimed_by") if isinstance(job, dict) else None
            )
            if claimed_by != worker_id:
                continue
        if pool is not None:
            job_pool = getattr(job, "pool", None) or (
                job.get("pool") if isinstance(job, dict) else None
            )
            if str(job_pool or "") != str(pool):
                continue
        n += 1
    return n


def worker_max_claimed(worker: Any) -> int | None:
    """Per-worker max concurrent claimed/running (None = unlimited)."""
    raw = getattr(worker, "max_claimed", None)
    if raw is None:
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def worker_at_quota(worker: Any, *, jobs: list[Any] | None = None) -> bool:
    """True when this worker already holds ``max_claimed`` active jobs."""
    limit = worker_max_claimed(worker)
    if limit is None:
        return False
    wid = getattr(worker, "worker_id", None) or ""
    return count_active_claims(worker_id=wid, jobs=jobs) >= limit


def pool_at_quota(
    worker: Any,
    job_pool: str | None,
    *,
    jobs: list[Any] | None = None,
    pool_limits: dict[str, int] | None = None,
) -> bool:
    """True when the job's pool (or any of the worker's pools) is at max."""
    limits = pool_limits if pool_limits is not None else parse_pool_max_claimed()
    if not limits:
        return False
    pools: list[str] = []
    if job_pool:
        pools.append(str(job_pool))
    for p in list(getattr(worker, "pools", None) or []):
        s = str(p or "").strip()
        if s and s not in pools:
            pools.append(s)
    for p in pools:
        if p in limits and count_active_claims(pool=p, jobs=jobs) >= limits[p]:
            return True
    return False


def assert_claim_quota(worker: Any, job: Any | None = None, *, jobs: list[Any] | None = None) -> None:
    """Raise :class:`QuotaExceeded` when claiming would exceed a limit."""
    if jobs is None:
        try:
            from app.core.distributed.queue import get_job_queue

            q = get_job_queue()
            if hasattr(q, "all_jobs"):
                jobs = q.all_jobs()
            elif hasattr(q, "list_jobs"):
                jobs = q.list_jobs()
            else:
                # Peek private cache (tests / memory store).
                jobs = list(getattr(q, "_jobs", {}).values())
        except Exception:
            jobs = []
    if worker_at_quota(worker, jobs=jobs):
        raise QuotaExceeded(
            f"Worker {getattr(worker, 'worker_id', '?')} at max_claimed="
            f"{worker_max_claimed(worker)}",
            kind="worker",
        )
    job_pool = None
    if job is not None:
        job_pool = getattr(job, "pool", None) or (
            job.get("pool") if isinstance(job, dict) else None
        )
    if pool_at_quota(worker, job_pool, jobs=jobs):
        raise QuotaExceeded(
            f"Pool concurrent claim quota exceeded for pool={job_pool!r} "
            f"worker={getattr(worker, 'worker_id', '?')}",
            kind="pool",
        )


def record_usage(
    worker_id: str,
    *,
    claims: int = 0,
    completes: int = 0,
    bytes_in: int = 0,
    bytes_out: int = 0,
) -> Any | None:
    """Atomically bump durable usage counters on the worker registry."""
    if not worker_id:
        return None
    try:
        from app.core.distributed.registry import get_worker_registry

        reg = get_worker_registry()
        info = reg.get(worker_id)
        if info is None:
            return None
        updates: dict[str, Any] = {}
        if claims:
            updates["usage_claims"] = int(getattr(info, "usage_claims", 0) or 0) + int(claims)
        if completes:
            updates["usage_completes"] = int(getattr(info, "usage_completes", 0) or 0) + int(
                completes
            )
        if bytes_in:
            updates["usage_bytes_in"] = int(getattr(info, "usage_bytes_in", 0) or 0) + int(
                bytes_in
            )
        if bytes_out:
            updates["usage_bytes_out"] = int(getattr(info, "usage_bytes_out", 0) or 0) + int(
                bytes_out
            )
        if not updates:
            return info
        return reg.patch(worker_id, **updates)
    except Exception as exc:
        log.warning("record_usage(%s) failed: %s", worker_id, exc)
        return None


def usage_snapshot(worker: Any) -> dict[str, int]:
    return {
        "claims": int(getattr(worker, "usage_claims", 0) or 0),
        "completes": int(getattr(worker, "usage_completes", 0) or 0),
        "bytes_in": int(getattr(worker, "usage_bytes_in", 0) or 0),
        "bytes_out": int(getattr(worker, "usage_bytes_out", 0) or 0),
    }
