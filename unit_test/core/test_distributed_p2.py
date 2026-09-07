"""P2 distributed execution: disk persistence, lease reclaim, cancel, plugin refuse."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.distributed.models import JobResult, NodeJob, WorkerInfo, WorkerResources
from app.core.distributed.placement import worker_eligible_for_job
from app.core.distributed.queue import JobQueue
from app.core.distributed.registry import WorkerRegistry
from app.core.distributed.store import DiskStateStore, MemoryStateStore
from app.core.ir.models import IRPlacement


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def test_disk_store_persists_workers_and_jobs(tmp_path: Path):
    store = DiskStateStore(root=tmp_path)
    reg = WorkerRegistry(store=store, load_persisted=False)
    reg.register(
        WorkerInfo(
            worker_id="gpu-1",
            labels=["gpu"],
            resources=WorkerResources(gpu=True, vram_mib_free=8000),
            plugins=["trainer"],
        )
    )
    q = JobQueue(store=store, load_persisted=False, lease_ttl_s=30.0)
    job = q.enqueue(
        NodeJob(job_id="j1", run_id="r", node_id="n", node_type="trainer", tags=["gpu"])
    )
    assert job.status == "pending"

    # New instances hydrate from the same disk root.
    reg2 = WorkerRegistry(store=DiskStateStore(root=tmp_path), load_persisted=True)
    q2 = JobQueue(store=DiskStateStore(root=tmp_path), load_persisted=True, lease_ttl_s=30.0)
    assert reg2.get("gpu-1") is not None
    assert reg2.get("gpu-1").plugins == ["trainer"]
    assert q2.get("j1") is not None
    assert q2.get("j1").status == "pending"
    assert (tmp_path / "workers.json").is_file()
    assert (tmp_path / "jobs.json").is_file()


def test_lease_reclaim_returns_job_to_pending():
    q = JobQueue(store=MemoryStateStore(), load_persisted=False, lease_ttl_s=1.0)
    q.enqueue(NodeJob(job_id="lease1", run_id="r", node_id="n", node_type="trainer"))
    worker = WorkerInfo(
        worker_id="w1",
        labels=["gpu"],
        resources=WorkerResources(gpu=True),
        plugins=["trainer"],
    )
    claimed = q.claim(worker)
    assert claimed is not None
    assert claimed.status == "claimed"
    assert claimed.lease_expires_at is not None

    # Force lease expiry.
    expired = claimed.model_copy(
        update={"lease_expires_at": _utcnow() - timedelta(seconds=5)}
    )
    with q._lock:
        q._jobs[claimed.job_id] = expired

    reclaimed = q.reclaim_expired_leases()
    assert claimed.job_id in reclaimed
    job = q.get(claimed.job_id)
    assert job is not None
    assert job.status == "pending"
    assert job.claimed_by is None

    # Another worker can claim it again.
    worker2 = WorkerInfo(
        worker_id="w2",
        labels=["gpu"],
        resources=WorkerResources(gpu=True),
        plugins=["trainer"],
    )
    again = q.claim(worker2)
    assert again is not None
    assert again.claimed_by == "w2"


def test_cancel_sets_status_visible_to_worker():
    q = JobQueue(store=MemoryStateStore(), load_persisted=False, lease_ttl_s=60.0)
    q.enqueue(NodeJob(job_id="c1", run_id="r", node_id="n", node_type="x"))
    worker = WorkerInfo(worker_id="w", plugins=["x"])
    claimed = q.claim(worker)
    assert claimed is not None
    assert not q.is_cancelled(claimed.job_id)

    cancelled = q.cancel(claimed.job_id)
    assert cancelled.status == "cancelled"
    assert q.is_cancelled(claimed.job_id)
    assert q.get_result(claimed.job_id) is not None
    assert q.get_result(claimed.job_id).status == "cancelled"


def test_claim_refuses_missing_plugin():
    q = JobQueue(store=MemoryStateStore(), load_persisted=False)
    q.enqueue(
        NodeJob(
            job_id="p1",
            run_id="r",
            node_id="n",
            node_type="trainer",
            tags=["gpu"],
            require_gpu=True,
            placement=IRPlacement(mode="auto", tags=("gpu",), require_gpu=True),
        )
    )
    # Worker advertises plugins but not trainer → hard refuse.
    worker = WorkerInfo(
        worker_id="gpu",
        labels=["gpu"],
        resources=WorkerResources(gpu=True, vram_mib_free=8192),
        plugins=["evaluator"],  # missing trainer
    )
    assert q.claim(worker) is None
    assert q.get("p1").status == "pending"

    # Eligible once trainer is advertised.
    ok = WorkerInfo(
        worker_id="gpu2",
        labels=["gpu"],
        resources=WorkerResources(gpu=True, vram_mib_free=8192),
        plugins=["trainer", "evaluator"],
    )
    claimed = q.claim(ok)
    assert claimed is not None
    assert claimed.claimed_by == "gpu2"


def test_worker_eligible_hard_refuse_missing_plugin():
    job = NodeJob(job_id="j", run_id="r", node_id="n", node_type="trainer")
    missing = WorkerInfo(worker_id="w", plugins=["other"])
    assert worker_eligible_for_job(missing, job) is False
    present = WorkerInfo(worker_id="w", plugins=["trainer"])
    assert worker_eligible_for_job(present, job) is True
    # Empty plugins → allow (unknown advertisement / tests).
    empty = WorkerInfo(worker_id="w", plugins=[])
    assert worker_eligible_for_job(empty, job) is True


def test_heartbeat_renews_lease():
    q = JobQueue(store=MemoryStateStore(), load_persisted=False, lease_ttl_s=60.0)
    q.enqueue(NodeJob(job_id="h1", run_id="r", node_id="n", node_type="x"))
    worker = WorkerInfo(worker_id="w", plugins=["x"])
    claimed = q.claim(worker)
    assert claimed.lease_expires_at is not None
    old_expiry = claimed.lease_expires_at
    # Force near-expiry then renew.
    with q._lock:
        q._jobs[claimed.job_id] = claimed.model_copy(
            update={"lease_expires_at": _utcnow() + timedelta(seconds=1)}
        )
    n = q.renew_leases_for_worker("w")
    assert n == 1
    renewed = q.get(claimed.job_id)
    assert renewed.lease_expires_at > old_expiry - timedelta(seconds=30)
