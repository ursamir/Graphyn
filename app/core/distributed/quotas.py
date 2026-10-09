# app/core/distributed/quotas.py
"""
Bounded Context:  BC5 — Execution Runtime (Mode B WAVE-2)
Responsibility:   Pool / per-worker concurrent claim quotas, durable usage
                  counters, and F18 org fair-share / queue-reason helpers.
Owns:             parse_pool_max_claimed(), worker_at_quota(), pool_at_quota(),
                  count_active_claims(), record_usage(), usage_snapshot(),
                  org concurrent helpers, fair_share_key(), infer_queue_reason().
Public Surface:   Functions above + QuotaExceeded.
Must NOT:         Import app.api / invent a parallel broker.
Dependencies:     stdlib, models / registry / queue / trust.metering (lazy).
Reason To Change: Quota env syntax, org fair-share, or slot metrics evolve.
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


def job_effective_pools(job: Any) -> set[str]:
    """Pools a claimed job counts against: ``job.pool`` ∪ ``claim_pools`` (set at claim)."""
    get = (lambda k: job.get(k)) if isinstance(job, dict) else (lambda k: getattr(job, k, None))
    pools = {str(p) for p in (get("claim_pools") or []) if p}
    if get("pool"):
        pools.add(str(get("pool")))
    return pools


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
        if pool is not None and str(pool) not in job_effective_pools(job):
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

            jobs = get_job_queue().active_jobs()
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

        return get_worker_registry().increment_usage(
            worker_id,
            usage_claims=claims,
            usage_completes=completes,
            usage_bytes_in=bytes_in,
            usage_bytes_out=bytes_out,
        )
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


# ── F18: org fair-share + queue reasons ───────────────────────────────────────


def _job_field(job: Any, key: str, default: Any = None) -> Any:
    if isinstance(job, dict):
        return job.get(key, default)
    return getattr(job, key, default)


def count_org_jobs(
    org_id: str | None,
    *,
    statuses: tuple[str, ...] = ("claimed", "running"),
    jobs: list[Any] | None = None,
) -> int:
    """Count jobs for ``org_id`` in the given statuses."""
    if jobs is None:
        try:
            from app.core.distributed.queue import get_job_queue

            q = get_job_queue()
            jobs = q.list() if hasattr(q, "list") else list(getattr(q, "_jobs", {}).values())
        except Exception as exc:
            log.warning("count_org_jobs: queue unavailable: %s", exc)
            return 0
    n = 0
    for job in jobs or []:
        status = _job_field(job, "status")
        if status not in statuses:
            continue
        joid = _job_field(job, "org_id")
        if org_id is None:
            n += 1
            continue
        if str(joid or "") == str(org_id):
            n += 1
    return n


def org_concurrent_limit(org_id: str | None) -> int | None:
    """Per-org max concurrent claimed/running jobs (None = unlimited)."""
    if not org_id:
        return None
    try:
        from app.core.trust.metering import get_meter_store

        q = get_meter_store().get_quota(str(org_id))
        return q.max_concurrent_jobs
    except Exception as exc:
        log.warning("org_concurrent_limit(%s) failed: %s", org_id, exc)
        return None


def org_queued_limit(org_id: str | None) -> int | None:
    """Per-org max pending (queued) jobs (None = unlimited)."""
    if not org_id:
        return None
    try:
        from app.core.trust.metering import get_meter_store

        q = get_meter_store().get_quota(str(org_id))
        return q.max_queued_jobs
    except Exception as exc:
        log.warning("org_queued_limit(%s) failed: %s", org_id, exc)
        return None


def org_at_concurrent_quota(
    org_id: str | None,
    *,
    jobs: list[Any] | None = None,
    upcoming: int = 0,
) -> bool:
    """True when org already holds max_concurrent_jobs active claims."""
    limit = org_concurrent_limit(org_id)
    if limit is None:
        return False
    used = count_org_jobs(org_id, statuses=("claimed", "running"), jobs=jobs)
    return used + upcoming >= int(limit)


def org_at_queue_depth(
    org_id: str | None,
    *,
    jobs: list[Any] | None = None,
    upcoming: int = 0,
) -> bool:
    """True when org pending count would exceed max_queued_jobs."""
    limit = org_queued_limit(org_id)
    if limit is None:
        return False
    used = count_org_jobs(org_id, statuses=("pending",), jobs=jobs)
    return used + upcoming > int(limit)


def fair_share_key(
    org_id: str | None,
    *,
    jobs: list[Any] | None = None,
    fifo_index: int = 0,
) -> tuple[float, int]:
    """Sort key for fair-share dispatch: lower utilization first, then FIFO.

    utilization = running / max_concurrent (absolute running when unlimited).
    Prefer the org with fewer running jobs relative to its quota so one tenant
    cannot starve others under a shared worker pool.
    """
    limit = org_concurrent_limit(org_id)
    running = count_org_jobs(org_id, statuses=("claimed", "running"), jobs=jobs)
    if limit is None or int(limit) <= 0:
        util = float(running)
    else:
        util = float(running) / float(limit)
    return (util, int(fifo_index))


def infer_queue_reason(
    job: Any,
    *,
    workers: list[Any] | None = None,
    jobs: list[Any] | None = None,
) -> str:
    """Derive why a pending job is waiting (F18 visibility).

    Priority: org_quota → no_capacity (pinned/all full) → waiting_worker.
    """
    org_id = _job_field(job, "org_id")
    if org_at_concurrent_quota(org_id, jobs=jobs) or org_at_queue_depth(org_id, jobs=jobs):
        return "org_quota"

    placement = _job_field(job, "placement")
    pin = None
    if placement is not None:
        mode = getattr(placement, "mode", None) or (
            placement.get("mode") if isinstance(placement, dict) else None
        )
        if mode == "worker":
            pin = getattr(placement, "worker", None) or (
                placement.get("worker") if isinstance(placement, dict) else None
            )
    if workers is None:
        try:
            from app.core.distributed.registry import get_worker_registry

            workers = get_worker_registry().list(include_stale=False)
        except Exception:
            workers = []
    if pin:
        target = None
        for w in workers or []:
            if getattr(w, "worker_id", None) == pin:
                target = w
                break
        if target is not None and worker_at_quota(target, jobs=jobs):
            return "no_capacity"
        if target is None:
            return "waiting_worker"

    from app.core.distributed.models import NodeJob
    from app.core.distributed.placement import worker_eligible_for_job

    try:
        nj = job if isinstance(job, NodeJob) else NodeJob.model_validate(job)
    except Exception:
        return "waiting_worker"
    eligible_free = False
    for w in workers or []:
        try:
            if not worker_eligible_for_job(w, nj):
                continue
        except Exception:
            continue
        if not worker_at_quota(w, jobs=jobs):
            eligible_free = True
            break
    if not eligible_free and workers:
        return "no_capacity"
    return "waiting_worker"
