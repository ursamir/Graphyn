# app/core/distributed/placement.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Resolve which worker (or local) should run a node given
                  IRPlacement + capability hints and the live worker set.
Owns:             resolve_worker(), worker_eligible_for_job(),
                  placement_needs_remote(), effective_job_constraints().
Public Surface:   resolve_worker, worker_eligible_for_job,
                  placement_needs_remote, effective_job_constraints.
Must NOT:         Import from app.domain, app.api, or orchestrator.
Dependencies:     app.core.ir.models (IRPlacement, IRCapabilityMetadata),
                  app.core.distributed.models (WorkerInfo, NodeJob).
Reason To Change: Scheduling policy (load balancing, affinity) evolves.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from app.core.distributed.models import NodeJob, WorkerInfo
from app.core.ir.models import IRCapabilityMetadata, IRPlacement

LOCAL = "local"


def placement_needs_remote(
    placement: IRPlacement | None,
    *,
    capability: IRCapabilityMetadata | None = None,
) -> bool:
    """Return True if placement/capability implies a remote (non-local) worker."""
    if placement is not None:
        if placement.mode == "local":
            return False
        if placement.mode in ("worker", "pool"):
            return True
        if placement.require_gpu or placement.min_vram_mib:
            return True
        if placement.tags and any(t.lower() == "gpu" for t in placement.tags):
            return True
        if placement.worker or placement.pool:
            return True
    if capability is not None and capability.requires_gpu:
        return True
    return False



def effective_job_constraints(
    placement: IRPlacement | None,
    capability: IRCapabilityMetadata | None = None,
) -> dict:
    """Derive job constraint fields mirroring :func:`resolve_worker`.

    Returns a dict with keys ``require_gpu``, ``tags``, ``min_vram_mib``, ``pool``.
    Capability ``requires_gpu`` promotes ``require_gpu`` and ensures a ``gpu`` tag
    even when placement omitted those fields — so enqueued jobs stay GPU-bound.
    """
    tags: list[str] = list(placement.tags) if placement and placement.tags else []
    require_gpu = bool(placement.require_gpu) if placement else False
    min_vram = placement.min_vram_mib if placement else None
    pool = placement.pool if placement else None

    if capability is not None and capability.requires_gpu:
        require_gpu = True
        if "gpu" not in {t.lower() for t in tags}:
            tags = [*tags, "gpu"]

    if placement is not None and placement.mode == "pool":
        pool = placement.pool or pool

    return {
        "require_gpu": require_gpu,
        "tags": tags,
        "min_vram_mib": min_vram,
        "pool": pool,
    }


def worker_eligible_for_job(worker: WorkerInfo, job: NodeJob) -> bool:
    """Whether ``worker`` satisfies the job's placement constraints."""
    # Explicit worker pin
    if job.placement is not None and job.placement.mode == "worker":
        return worker.worker_id == (job.placement.worker or "")

    pool = job.pool
    tags = list(job.tags)
    require_gpu = job.require_gpu
    min_vram = job.min_vram_mib

    if job.placement is not None:
        p = job.placement
        if p.mode == "pool":
            pool = p.pool or pool
        if p.tags:
            tags = list(p.tags)
        require_gpu = require_gpu or p.require_gpu
        if p.min_vram_mib is not None:
            min_vram = p.min_vram_mib

    if pool and pool not in (worker.pools or []):
        return False

    if tags:
        worker_labels = {lbl.lower() for lbl in (worker.labels or [])}
        needed = {t.lower() for t in tags}
        if not needed.issubset(worker_labels):
            return False

    resources = worker.resources
    if require_gpu and not (resources and resources.gpu):
        return False

    if min_vram is not None:
        free = resources.vram_mib_free if resources else None
        if free is None or free < min_vram:
            return False

    # Hard refuse (P2): advertised non-empty plugins must include node_type.
    plugins = list(worker.plugins or [])
    if plugins:
        if not job.node_type or job.node_type not in plugins:
            return False

    return True


def _load_score(worker: WorkerInfo) -> tuple[int, str]:
    """Least-loaded sort key: fewer active jobs, then worker_id."""
    return (worker.active_jobs, worker.worker_id)


def resolve_worker(
    *,
    placement: IRPlacement | None = None,
    capability: IRCapabilityMetadata | None = None,
    workers: Sequence[WorkerInfo] = (),
    node_type: str | None = None,
) -> str | None:
    """Resolve a worker id, ``\"local\"``, or ``None`` (no eligible worker).

    Resolution order (design §3.1):
    explicit ``worker`` → ``pool`` → tags + capability → least-loaded eligible
    → ``\"local\"`` when remote is not required → ``None`` if required but missing.
    """
    alive = list(workers)

    # Explicit local
    if placement is not None and placement.mode == "local":
        return LOCAL

    # Explicit worker pin (fail closed if advertised plugins omit node_type)
    if placement is not None and placement.mode == "worker":
        wid = placement.worker
        if not wid:
            return None
        for w in alive:
            if w.worker_id == wid:
                plugins = list(w.plugins or [])
                if plugins and node_type and node_type not in plugins:
                    return None
                return wid
        return None

    # Build a synthetic job for eligibility checks (shared with enqueue path)
    constraints = effective_job_constraints(placement, capability=capability)
    tags = list(constraints["tags"])
    require_gpu = bool(constraints["require_gpu"])
    min_vram = constraints["min_vram_mib"]
    pool = constraints["pool"]

    needs_remote = placement_needs_remote(placement, capability=capability)

    if placement is not None and placement.mode == "pool":
        pool = placement.pool or pool
        needs_remote = True

    # Unconstrained nodes stay on the control plane / local worker.
    if not needs_remote and not tags and not pool and not require_gpu:
        return LOCAL

    synthetic = NodeJob(
        job_id="_resolve",
        run_id="_",
        node_id="_",
        node_type=node_type or "",
        placement=placement,
        require_gpu=require_gpu,
        min_vram_mib=min_vram,
        tags=tags,
        pool=pool,
    )

    eligible = [w for w in alive if worker_eligible_for_job(w, synthetic)]
    if eligible:
        eligible.sort(key=_load_score)
        return eligible[0].worker_id

    if needs_remote:
        return None
    return LOCAL
