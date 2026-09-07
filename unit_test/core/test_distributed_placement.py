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
