"""Worker registry + job queue tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.distributed.models import JobResult, NodeJob, WorkerInfo, WorkerResources
from app.core.distributed.queue import JobQueue
from app.core.distributed.registry import WorkerRegistry
from app.core.ir.models import IRPlacement


def test_registry_heartbeat_and_stale():
    reg = WorkerRegistry(stale_after_s=1.0)
    info = WorkerInfo(worker_id="w1", labels=["gpu"], resources=WorkerResources(gpu=True))
    reg.register(info)
    assert not reg.is_stale("w1")
    # Force old heartbeat
    old = info.model_copy(
        update={"heartbeat_at": datetime.now(timezone.utc) - timedelta(seconds=5)}
    )
    with reg._lock:
        reg._workers["w1"] = old
    assert reg.is_stale("w1")
    assert reg.list(include_stale=False) == []
    assert len(reg.list(include_stale=True)) == 1
    # Heartbeat refreshes
    reg.heartbeat("w1", status="idle")
    assert not reg.is_stale("w1")


def test_queue_claim_eligibility():
    q = JobQueue()
    gpu_job = NodeJob(
        job_id="j1",
        run_id="r1",
        node_id="trainer_0",
        node_type="trainer",
        tags=["gpu"],
        require_gpu=True,
        placement=IRPlacement(mode="auto", tags=("gpu",), require_gpu=True),
    )
    q.enqueue(gpu_job)

    cpu_worker = WorkerInfo(worker_id="cpu", labels=["cpu"], resources=WorkerResources(gpu=False))
    assert q.claim(cpu_worker) is None

    gpu_worker = WorkerInfo(
        worker_id="gpu1",
        labels=["gpu"],
        resources=WorkerResources(gpu=True, vram_mib_free=8192),
    )
    claimed = q.claim(gpu_worker)
    assert claimed is not None
    assert claimed.job_id == "j1"
    assert claimed.claimed_by == "gpu1"
    assert claimed.status == "claimed"

    q.complete(
        JobResult(
            job_id="j1",
            status="succeeded",
            worker_id="gpu1",
            output_refs={},
            lease_generation=int(claimed.lease_generation or 0),
        )
    )
    assert q.get("j1").status == "succeeded"


def test_queue_cancel():
    q = JobQueue()
    job = q.enqueue(
        NodeJob(job_id="c1", run_id="r", node_id="n", node_type="x")
    )
    cancelled = q.cancel(job.job_id)
    assert cancelled.status == "cancelled"
