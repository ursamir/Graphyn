# app/core/distributed/__init__.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Public surface for distributed execution (workers, jobs,
                  placement, DistributedBackend).
Owns:             Re-exports of distributed models and helpers.
Public Surface:   WorkerInfo, NodeJob, JobResult, WorkerRegistry, JobQueue,
                  resolve_worker, DistributedBackend, get_worker_registry,
                  get_job_queue.
Must NOT:         Import from app.domain or app.api.
Dependencies:     app.core.distributed.*, app.core.runtime_backend.
Reason To Change: New distributed public symbols or registration policy.
"""
from __future__ import annotations

from app.core.distributed.backend import (
    DistributedBackend,
    run_loopback_worker_once,
    start_loopback_worker_thread,
)
from app.core.distributed.models import JobResult, NodeJob, WorkerInfo, WorkerResources
from app.core.distributed.placement import resolve_worker, worker_eligible_for_job
from app.core.distributed.queue import JobQueue, get_job_queue, _reset_job_queue
from app.core.distributed.registry import (
    WorkerRegistry,
    get_worker_registry,
    _reset_worker_registry,
)
# Backend registration is lazy via get_backend() / _reset_backend_registry()
# to avoid import-time lock deadlocks with runtime_backend.

__all__ = [
    "DistributedBackend",
    "JobQueue",
    "JobResult",
    "NodeJob",
    "WorkerInfo",
    "WorkerRegistry",
    "WorkerResources",
    "get_job_queue",
    "get_worker_registry",
    "resolve_worker",
    "run_loopback_worker_once",
    "start_loopback_worker_thread",
    "worker_eligible_for_job",
    "_reset_job_queue",
    "_reset_worker_registry",
]
