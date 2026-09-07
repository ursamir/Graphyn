"""Placement resolution tests."""
from __future__ import annotations

from app.core.distributed.models import WorkerInfo, WorkerResources
from app.core.distributed.placement import resolve_worker
from app.core.ir.models import IRCapabilityMetadata, IRPlacement


def _gpu_worker(worker_id: str = "server99-gpu") -> WorkerInfo:
    return WorkerInfo(
        worker_id=worker_id,
        labels=["gpu", "lab"],
        pools=["gpu-lab"],
        resources=WorkerResources(gpu=True, vram_mib_free=8000, vram_mib_total=16000),
        status="idle",
    )


def test_gpu_tag_resolves_to_gpu_worker():
    workers = [_gpu_worker(), WorkerInfo(worker_id="cpu-1", labels=["cpu"])]
    placement = IRPlacement(mode="auto", tags=("gpu",), require_gpu=True)
    assert resolve_worker(placement=placement, workers=workers) == "server99-gpu"


def test_no_placement_resolves_local():
    workers = [_gpu_worker()]
    assert resolve_worker(placement=None, workers=workers) == "local"


def test_require_gpu_capability_without_worker_returns_none():
    cap = IRCapabilityMetadata(requires_gpu=True)
    assert resolve_worker(capability=cap, workers=[]) is None


def test_mode_local_always_local():
    workers = [_gpu_worker()]
    placement = IRPlacement(mode="local", tags=("gpu",), require_gpu=True)
    assert resolve_worker(placement=placement, workers=workers) == "local"


def test_mode_worker_pin():
    workers = [_gpu_worker("a"), _gpu_worker("b")]
    placement = IRPlacement(mode="worker", worker="b")
    assert resolve_worker(placement=placement, workers=workers) == "b"


def test_mode_pool():
    workers = [
        WorkerInfo(worker_id="edge", labels=["edge"], pools=["edge"]),
        _gpu_worker(),
    ]
    placement = IRPlacement(mode="pool", pool="gpu-lab")
    assert resolve_worker(placement=placement, workers=workers) == "server99-gpu"


def test_effective_job_constraints_from_capability_requires_gpu():
    """Capability requires_gpu without placement.require_gpu still GPU-binds the job."""
    from app.core.distributed.models import NodeJob, WorkerInfo, WorkerResources
    from app.core.distributed.placement import (
        effective_job_constraints,
        worker_eligible_for_job,
    )

    cap = IRCapabilityMetadata(requires_gpu=True)
    # No placement.require_gpu / tags — capability alone must promote GPU constraints.
    constraints = effective_job_constraints(placement=None, capability=cap)
    assert constraints["require_gpu"] is True
    assert "gpu" in {t.lower() for t in constraints["tags"]}

    job = NodeJob(
        job_id="j",
        run_id="r",
        node_id="n",
        node_type="trainer",
        require_gpu=constraints["require_gpu"],
        tags=list(constraints["tags"]),
        min_vram_mib=constraints["min_vram_mib"],
        pool=constraints["pool"],
    )
    cpu = WorkerInfo(
        worker_id="cpu-only",
        labels=["cpu"],
        resources=WorkerResources(gpu=False),
        plugins=["trainer"],
    )
    gpu = _gpu_worker()
    gpu = gpu.model_copy(update={"plugins": ["trainer"]})
    assert worker_eligible_for_job(cpu, job) is False
    assert worker_eligible_for_job(gpu, job) is True


def test_resolve_worker_pin_fails_closed_on_missing_plugin():
    workers = [
        WorkerInfo(
            worker_id="pinned",
            labels=["gpu"],
            resources=WorkerResources(gpu=True, vram_mib_free=8000),
            plugins=["evaluator"],  # missing trainer
        )
    ]
    placement = IRPlacement(mode="worker", worker="pinned")
    assert (
        resolve_worker(placement=placement, workers=workers, node_type="trainer")
        is None
    )
    # Present plugin → ok
    workers[0] = workers[0].model_copy(update={"plugins": ["trainer"]})
    assert (
        resolve_worker(placement=placement, workers=workers, node_type="trainer")
        == "pinned"
    )
