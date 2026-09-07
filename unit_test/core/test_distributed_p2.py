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


def test_cancel_unblocks_wait_for_result():
    """cancel() sets the waiter Event so wait_for_result returns cancelled."""
    q = JobQueue(store=MemoryStateStore(), load_persisted=False)
    job = q.enqueue(NodeJob(job_id="cw1", run_id="r", node_id="n", node_type="x"))
    # Cancel without claim — waiters still wake.
    q.cancel(job.job_id)
    result = q.wait_for_result(job.job_id, timeout_s=1.0)
    assert result is not None
    assert result.status == "cancelled"


def test_cross_process_wait_via_disk_store(tmp_path: Path):
    """Queue A enqueues; B (same DiskStateStore) claims+completes; A observes via store poll.

    Simulates CLI↔API without sharing a process Event: the waiter queue never
    receives ``evt.set()`` from the completer — ``wait_for_result`` must reload
    results from disk. (conftest no-ops ``Thread.start``, so this is sequential.)
    """
    q_a = JobQueue(
        store=DiskStateStore(root=tmp_path), load_persisted=False, lease_ttl_s=60.0
    )
    job = q_a.enqueue(
        NodeJob(job_id="xp1", run_id="r", node_id="n", node_type="trainer", tags=["gpu"])
    )
    assert job.status == "pending"

    # CLI-like waiter: hydrated job, empty results, own Event (never set by B).
    q_wait = JobQueue(
        store=DiskStateStore(root=tmp_path), load_persisted=True, lease_ttl_s=60.0
    )
    assert q_wait.get("xp1") is not None
    assert q_wait.get_result("xp1") is None

    # API-like process
    q_b = JobQueue(
        store=DiskStateStore(root=tmp_path), load_persisted=True, lease_ttl_s=60.0
    )
    worker = WorkerInfo(
        worker_id="gpu-b",
        labels=["gpu"],
        resources=WorkerResources(gpu=True, vram_mib_free=8192),
        plugins=["trainer"],
    )
    claimed = q_b.claim(worker)
    assert claimed is not None
    assert claimed.job_id == "xp1"
    q_b.mark_running(claimed.job_id)
    q_b.complete(
        JobResult(
            job_id="xp1",
            status="succeeded",
            worker_id="gpu-b",
            output_refs={"output": "artifact://local/sha256/ab/cd/deadbeef"},
            lease_generation=int(claimed.lease_generation or 0),
        )
    )

    # q_wait's Event was never set — must discover result via durable store poll.
    result = q_wait.wait_for_result("xp1", timeout_s=2.0, poll_interval_s=0.05)
    assert result is not None
    assert result.status == "succeeded"
    assert result.worker_id == "gpu-b"


def test_complete_requires_claim_owner_and_lease_generation():
    q = JobQueue(store=MemoryStateStore(), load_persisted=False)
    q.enqueue(NodeJob(job_id="auth1", run_id="r", node_id="n", node_type="x"))
    worker = WorkerInfo(worker_id="w1", plugins=["x"])
    claimed = q.claim(worker)
    assert claimed is not None
    gen = int(claimed.lease_generation or 0)

    # Wrong worker
    with pytest.raises(ValueError, match="worker mismatch"):
        q.complete(
            JobResult(
                job_id="auth1",
                status="succeeded",
                worker_id="other",
                lease_generation=gen,
            )
        )

    # Wrong generation
    with pytest.raises(ValueError, match="lease_generation mismatch"):
        q.complete(
            JobResult(
                job_id="auth1",
                status="succeeded",
                worker_id="w1",
                lease_generation=gen + 99,
            )
        )

    # Missing generation
    with pytest.raises(ValueError, match="lease_generation mismatch"):
        q.complete(
            JobResult(
                job_id="auth1",
                status="succeeded",
                worker_id="w1",
                lease_generation=None,
            )
        )

    # Happy path
    q.complete(
        JobResult(
            job_id="auth1",
            status="succeeded",
            worker_id="w1",
            lease_generation=gen,
        )
    )
    assert q.get("auth1").status == "succeeded"


def test_lease_reclaim_increments_generation_and_fences_old_complete():
    q = JobQueue(store=MemoryStateStore(), load_persisted=False, lease_ttl_s=1.0)
    q.enqueue(NodeJob(job_id="fence1", run_id="r", node_id="n", node_type="trainer"))
    w1 = WorkerInfo(
        worker_id="w1",
        labels=["gpu"],
        resources=WorkerResources(gpu=True),
        plugins=["trainer"],
    )
    claimed = q.claim(w1)
    old_gen = int(claimed.lease_generation or 0)

    # Expire + reclaim
    with q._lock:
        q._jobs[claimed.job_id] = claimed.model_copy(
            update={"lease_expires_at": _utcnow() - timedelta(seconds=5)}
        )
    reclaimed = q.reclaim_expired_leases()
    assert "fence1" in reclaimed
    job = q.get("fence1")
    assert job.status == "pending"
    assert int(job.lease_generation) == old_gen + 1

    # Old worker cannot complete with stale generation
    with pytest.raises(ValueError):
        q.complete(
            JobResult(
                job_id="fence1",
                status="succeeded",
                worker_id="w1",
                lease_generation=old_gen,
            )
        )

    # New claim can complete with new generation
    w2 = WorkerInfo(
        worker_id="w2",
        labels=["gpu"],
        resources=WorkerResources(gpu=True),
        plugins=["trainer"],
    )
    again = q.claim(w2)
    assert again is not None
    q.complete(
        JobResult(
            job_id="fence1",
            status="succeeded",
            worker_id="w2",
            lease_generation=int(again.lease_generation or 0),
        )
    )
    assert q.get("fence1").status == "succeeded"


def test_reclaim_clears_preferred_worker_pin():
    """After reclaim, mode=worker pin is widened so another GPU worker can claim."""
    from app.core.distributed.placement import widen_placement_after_reclaim

    q = JobQueue(store=MemoryStateStore(), load_persisted=False, lease_ttl_s=1.0)
    pinned = IRPlacement(
        mode="worker",
        worker="gpu-dead",
        tags=("gpu",),
        require_gpu=True,
        min_vram_mib=4096,
    )
    q.enqueue(
        NodeJob(
            job_id="pin1",
            run_id="r",
            node_id="n",
            node_type="trainer",
            tags=["gpu"],
            require_gpu=True,
            min_vram_mib=4096,
            placement=pinned,
        )
    )
    # Only the pinned worker can claim initially.
    other = WorkerInfo(
        worker_id="gpu-alive",
        labels=["gpu"],
        resources=WorkerResources(gpu=True, vram_mib_free=8192),
        plugins=["trainer"],
    )
    assert q.claim(other) is None

    dead = WorkerInfo(
        worker_id="gpu-dead",
        labels=["gpu"],
        resources=WorkerResources(gpu=True, vram_mib_free=8192),
        plugins=["trainer"],
    )
    claimed = q.claim(dead)
    assert claimed is not None
    assert claimed.placement is not None
    assert claimed.placement.mode == "worker"
    assert claimed.placement.worker == "gpu-dead"
    old_gen = int(claimed.lease_generation or 0)

    with q._lock:
        q._jobs[claimed.job_id] = claimed.model_copy(
            update={"lease_expires_at": _utcnow() - timedelta(seconds=5)}
        )
    reclaimed = q.reclaim_expired_leases()
    assert "pin1" in reclaimed

    job = q.get("pin1")
    assert job is not None
    assert job.status == "pending"
    assert int(job.lease_generation) == old_gen + 1
    assert job.placement is not None
    assert job.placement.mode == "auto"
    assert job.placement.worker is None
    assert job.placement.require_gpu is True
    assert "gpu" in {t.lower() for t in job.placement.tags}
    assert job.require_gpu is True
    assert job.tags == ["gpu"]

    # Another eligible GPU worker can now claim (pin cleared, fencing kept).
    again = q.claim(other)
    assert again is not None
    assert again.claimed_by == "gpu-alive"
    assert int(again.lease_generation) == old_gen + 1


def test_widen_placement_after_reclaim_helper_only_touches_worker_mode():
    from app.core.distributed.placement import widen_placement_after_reclaim

    auto = IRPlacement(mode="auto", tags=("gpu",), require_gpu=True)
    assert widen_placement_after_reclaim(auto) is auto
    assert widen_placement_after_reclaim(None) is None

    pool = IRPlacement(mode="pool", pool="gpu-lab", require_gpu=True)
    assert widen_placement_after_reclaim(pool) is pool

    pinned = IRPlacement(
        mode="worker", worker="w1", tags=("gpu",), require_gpu=True, min_vram_mib=2048
    )
    widened = widen_placement_after_reclaim(
        pinned, tags=["gpu"], require_gpu=True, min_vram_mib=2048
    )
    assert widened is not None
    assert widened.mode == "auto"
    assert widened.worker is None
    assert widened.require_gpu is True
    assert widened.min_vram_mib == 2048
    assert widened.tags == ("gpu",)


# ---------------------------------------------------------------------------
# DIST-001 — atomic cross-process claim (module-level workers for spawn/fork)
# ---------------------------------------------------------------------------


def _dist001_claim_worker(root: str, wid: str, out_path: str) -> None:
    """Claim once against shared DiskStateStore; write ``wid:job_id`` (or empty)."""
    import time
    from pathlib import Path as P

    from app.core.distributed.models import WorkerInfo, WorkerResources
    from app.core.distributed.queue import JobQueue
    from app.core.distributed.store import DiskStateStore

    time.sleep(0.02)
    wq = JobQueue(
        store=DiskStateStore(root=P(root)),
        load_persisted=True,
        lease_ttl_s=60.0,
    )
    worker = WorkerInfo(
        worker_id=wid,
        labels=["cpu"],
        resources=WorkerResources(gpu=False),
        plugins=["x"],
    )
    claimed = wq.claim(worker)
    P(out_path).write_text(
        f"{wid}:{'' if claimed is None else claimed.job_id}\n",
        encoding="utf-8",
    )


def _dist001_claim_loop_worker(
    root: str, wid: str, out_path: str, max_rounds: int
) -> None:
    """Claim until empty; write ``wid:job1,job2,...``."""
    import time
    from pathlib import Path as P

    from app.core.distributed.models import WorkerInfo, WorkerResources
    from app.core.distributed.queue import JobQueue
    from app.core.distributed.store import DiskStateStore

    wq = JobQueue(
        store=DiskStateStore(root=P(root)),
        load_persisted=True,
        lease_ttl_s=60.0,
    )
    worker = WorkerInfo(
        worker_id=wid,
        labels=["cpu"],
        resources=WorkerResources(gpu=False),
        plugins=["x"],
    )
    claimed_ids: list[str] = []
    for _ in range(max_rounds):
        c = wq.claim(worker)
        if c is None:
            time.sleep(0.005)
            c = wq.claim(worker)
        if c is None:
            break
        claimed_ids.append(c.job_id)
    P(out_path).write_text(
        f"{wid}:{','.join(claimed_ids)}\n", encoding="utf-8"
    )


def test_atomic_claim_across_processes(tmp_path: Path):
    """DIST-001: independent JobQueue clients + shared DiskStateStore → one claim."""
    import multiprocessing as mp

    store = DiskStateStore(root=tmp_path)
    q = JobQueue(store=store, load_persisted=False, lease_ttl_s=60.0)
    q.enqueue(NodeJob(job_id="race1", run_id="r", node_id="n", node_type="x"))

    n = 8
    outs = [tmp_path / f"out{i}.txt" for i in range(n)]
    procs = [
        mp.Process(
            target=_dist001_claim_worker,
            args=(str(tmp_path), f"w{i}", str(outs[i])),
        )
        for i in range(n)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=20)
        assert p.exitcode == 0, f"worker exited {p.exitcode}"

    results = [o.read_text(encoding="utf-8").strip() for o in outs]
    wins = [r for r in results if r.endswith(":race1")]
    assert len(wins) == 1, f"expected exactly one claim, got {results!r}"

    final = JobQueue(store=DiskStateStore(root=tmp_path), load_persisted=True)
    job = final.get("race1")
    assert job is not None
    assert job.status == "claimed"
    assert job.claimed_by == wins[0].split(":", 1)[0]


def test_atomic_claim_stress_multiprocess(tmp_path: Path):
    """DIST-001 stress: N jobs, M workers, total successful claims == N (no dupes)."""
    import multiprocessing as mp

    n_jobs = 20
    n_workers = 12
    store = DiskStateStore(root=tmp_path)
    q = JobQueue(store=store, load_persisted=False, lease_ttl_s=60.0)
    for i in range(n_jobs):
        q.enqueue(
            NodeJob(job_id=f"j{i}", run_id="r", node_id=f"n{i}", node_type="x")
        )

    outs = [tmp_path / f"stress{i}.txt" for i in range(n_workers)]
    procs = [
        mp.Process(
            target=_dist001_claim_loop_worker,
            args=(str(tmp_path), f"w{i}", str(outs[i]), n_jobs + 5),
        )
        for i in range(n_workers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=40)
        assert p.exitcode == 0, f"worker exited {p.exitcode}"

    all_claims: list[str] = []
    for o in outs:
        line = o.read_text(encoding="utf-8").strip()
        _wid, _, ids = line.partition(":")
        if ids:
            all_claims.extend([x for x in ids.split(",") if x])

    assert len(all_claims) == n_jobs, (
        f"expected {n_jobs} claims, got {len(all_claims)}: {sorted(all_claims)}"
    )
    assert len(set(all_claims)) == n_jobs, (
        f"duplicate claims detected: {sorted(all_claims)}"
    )



def test_atomic_claim_two_queues_shared_memory_store():
    """Two JobQueue clients on one MemoryStateStore: second claim loses (CAS path).

    Cross-thread stress is covered by DiskStateStore multiprocess tests; the
    suite's autouse ``patch_threads`` no-ops ``Thread.start``.
    """
    store = MemoryStateStore()
    q_a = JobQueue(store=store, load_persisted=False, lease_ttl_s=60.0)
    q_a.enqueue(NodeJob(job_id="t1", run_id="r", node_id="n", node_type="x"))

    q_b = JobQueue(store=store, load_persisted=True, lease_ttl_s=60.0)
    worker_a = WorkerInfo(
        worker_id="wa",
        labels=["cpu"],
        resources=WorkerResources(gpu=False),
        plugins=["x"],
    )
    worker_b = WorkerInfo(
        worker_id="wb",
        labels=["cpu"],
        resources=WorkerResources(gpu=False),
        plugins=["x"],
    )
    c1 = q_a.claim(worker_a)
    c2 = q_b.claim(worker_b)
    assert c1 is not None and c1.job_id == "t1" and c1.claimed_by == "wa"
    assert c2 is None
    # Store truth
    snap = store.load_queue()
    assert snap["jobs"]["t1"]["status"] == "claimed"
    assert snap["jobs"]["t1"]["claimed_by"] == "wa"


def test_disk_mutate_queue_cas_helper(tmp_path: Path):
    """DiskStateStore.mutate_queue serializes RMW and returns mutator result."""
    store = DiskStateStore(root=tmp_path)
    store.save_queue(
        {
            "jobs": {"a": {"job_id": "a", "status": "pending"}},
            "order": ["a"],
            "results": {},
            "events": {},
        }
    )

    def mutator(snap):
        jobs = dict(snap.get("jobs") or {})
        jobs["a"] = {**jobs["a"], "status": "claimed", "claimed_by": "w"}
        order = [j for j in snap.get("order") or [] if j != "a"]
        return {**snap, "jobs": jobs, "order": order}, "ok"

    assert store.mutate_queue(mutator) == "ok"
    snap = store.load_queue()
    assert snap["jobs"]["a"]["status"] == "claimed"
    assert "a" not in snap["order"]


def _dist002_append_worker(root: str, job_id: str, out_path: str) -> None:
    from pathlib import Path as P
    from app.core.distributed.queue import JobQueue
    from app.core.distributed.store import DiskStateStore

    q = JobQueue(store=DiskStateStore(root=P(root)), load_persisted=True, lease_ttl_s=60.0)
    n = q.append_events(job_id, [{"type": "log", "msg": "from-append"}])
    P(out_path).write_text(str(n), encoding="utf-8")


def _dist002_renew_worker(root: str, job_id: str, worker_id: str, out_path: str) -> None:
    from pathlib import Path as P
    from app.core.distributed.queue import JobQueue
    from app.core.distributed.store import DiskStateStore

    q = JobQueue(store=DiskStateStore(root=P(root)), load_persisted=True, lease_ttl_s=60.0)
    job = q.renew_lease(job_id, worker_id=worker_id)
    P(out_path).write_text(
        "ok" if job is not None and job.lease_expires_at is not None else "fail",
        encoding="utf-8",
    )


def test_concurrent_append_and_renew_no_lost_update(tmp_path: Path):
    """DIST-002: append_events and renew_lease against shared disk must both land."""
    import multiprocessing as mp

    store = DiskStateStore(root=tmp_path)
    q = JobQueue(store=store, load_persisted=False, lease_ttl_s=60.0)
    q.enqueue(NodeJob(job_id="cu1", run_id="r", node_id="n", node_type="x"))
    worker = WorkerInfo(
        worker_id="w1",
        labels=["cpu"],
        resources=WorkerResources(gpu=False),
        plugins=["x"],
    )
    claimed = q.claim(worker)
    assert claimed is not None

    out_a = tmp_path / "append.txt"
    out_r = tmp_path / "renew.txt"
    pa = mp.Process(
        target=_dist002_append_worker, args=(str(tmp_path), "cu1", str(out_a))
    )
    pr = mp.Process(
        target=_dist002_renew_worker,
        args=(str(tmp_path), "cu1", "w1", str(out_r)),
    )
    pa.start()
    pr.start()
    pa.join(timeout=15)
    pr.join(timeout=15)
    assert pa.exitcode == 0 and pr.exitcode == 0
    assert out_a.read_text(encoding="utf-8").strip() == "1"
    assert out_r.read_text(encoding="utf-8").strip() == "ok"

    final = JobQueue(store=DiskStateStore(root=tmp_path), load_persisted=True)
    snap = DiskStateStore(root=tmp_path).load_queue()
    assert any(
        ev.get("msg") == "from-append" for ev in (snap.get("events") or {}).get("cu1", [])
    ), snap.get("events")
    job = final.get("cu1")
    assert job is not None and job.status == "claimed"
    assert job.claimed_by == "w1"
    assert job.lease_expires_at is not None
