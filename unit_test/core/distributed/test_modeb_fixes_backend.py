"""Mode B fixes — DistributedBackend: no run-start pinning for pool/auto,
load-score spreading, run-end blob cleanup, output sha256 verification."""
from __future__ import annotations

from typing import ClassVar

import pytest

from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode, IRPlacement
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.core.execution.runtime_backend import _reset_backend_registry

_TYPES = ("mb_echo_a", "mb_echo_b")


def _make_node(nt: str):
    class _Echo(Node):
        input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=object)}
        output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=object)}

        class Config(NodeConfig):
            pass

        def process(self, data):
            return {"value": data}

    _Echo.node_type = nt
    _Echo.metadata = NodeMetadata(node_type=nt, label=nt, description="t", category="Test")
    return _Echo


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
    monkeypatch.delenv("GRAPHYN_BACKEND", raising=False)
    monkeypatch.setenv("GRAPHYN_SKIP_PLUGIN_LOAD", "1")
    monkeypatch.setenv("GRAPHYN_DISTRIBUTED_JOB_TIMEOUT", "15")
    monkeypatch.setenv("GRAPHYN_DISTRIBUTED_BLOB_GRACE_S", "0")
    _reset_backend_registry()
    from app.core.distributed.queue import _reset_job_queue
    from app.core.distributed.registry import _reset_worker_registry
    from app.core.nodes import registry

    _reset_worker_registry()
    _reset_job_queue()
    for nt in _TYPES:
        registry.register(nt, _make_node(nt), NodeMetadata(
            node_type=nt, label=nt, description="t", category="Test"))
    yield
    for nt in _TYPES:
        try:
            registry.unregister(nt)
        except Exception:
            pass
    _reset_worker_registry()
    _reset_job_queue()
    _reset_backend_registry()


def _gpu_worker(wid: str, active: int = 0):
    from app.core.distributed.models import WorkerInfo, WorkerResources

    return WorkerInfo(
        worker_id=wid,
        labels=["gpu"],
        resources=WorkerResources(gpu=True, vram_mib_free=8192),
        plugins=list(_TYPES),
        active_jobs=active,
    )


def _graph(placement: IRPlacement, n: int = 1) -> GraphIR:
    nodes = [
        IRNode(id=f"n{i}", node_type="mb_echo_a", config={}, placement=placement)
        for i in range(n)
    ]
    edges = [
        IREdge(src_id=f"n{i}", src_port="output", dst_id=f"n{i + 1}", dst_port="input")
        for i in range(n - 1)
    ]
    return GraphIR(schema_version="1.2", metadata=IRMetadata(name="mb", seed=0),
                   nodes=nodes, edges=edges)


def _capture_jobs(monkeypatch):
    """Record enqueued jobs; serve them with loopback worker 'w-b'."""
    from app.core.distributed.backend import run_loopback_worker_once
    from app.core.distributed.queue import JobQueue

    seen = []
    real_enqueue = JobQueue.enqueue
    real_wait = JobQueue.wait_for_result

    def enqueue(self, job):
        stored = real_enqueue(self, job)
        seen.append(stored)
        return stored

    def wait(self, job_id, *, timeout_s=None):
        from app.core.distributed.registry import get_worker_registry

        for wid in ("w-b", "w-a"):
            if get_worker_registry().get(wid) is not None:
                run_loopback_worker_once(wid)
        return real_wait(self, job_id, timeout_s=timeout_s)

    monkeypatch.setattr(JobQueue, "enqueue", enqueue)
    monkeypatch.setattr(JobQueue, "wait_for_result", wait)
    return seen


# ── 4. no pinning unless IR mode=worker ─────────────────────────────────────


def test_auto_placement_is_not_pinned_to_run_start_worker(monkeypatch):
    from app.core.distributed.backend import DistributedBackend
    from app.core.distributed.registry import get_worker_registry

    reg = get_worker_registry()
    reg.register(_gpu_worker("w-a"))   # least loaded at run start
    reg.register(_gpu_worker("w-b", active=3))
    seen = _capture_jobs(monkeypatch)
    out = DistributedBackend().execute(
        _graph(IRPlacement(mode="auto", tags=("gpu",), require_gpu=True)),
        input_overrides={"n0": {"input": 5}},
    )
    assert out["output"]["value"] == 5
    job = seen[0]
    assert job.placement is None or job.placement.mode != "worker"
    assert job.require_gpu is True and "gpu" in job.tags
    # Any eligible worker may claim — here the loopback served by w-b first.
    from app.core.distributed.queue import get_job_queue

    assert get_job_queue().get_result(job.job_id).worker_id == "w-b"


def test_pool_placement_enqueues_pool_constraint(monkeypatch):
    from app.core.distributed.backend import DistributedBackend
    from app.core.distributed.models import WorkerInfo
    from app.core.distributed.registry import get_worker_registry

    reg = get_worker_registry()
    reg.register(WorkerInfo(worker_id="w-a", pools=["lab"], plugins=list(_TYPES)))
    reg.register(WorkerInfo(worker_id="w-b", pools=["lab"], plugins=list(_TYPES)))
    seen = _capture_jobs(monkeypatch)
    DistributedBackend().execute(
        _graph(IRPlacement(mode="pool", pool="lab")),
        input_overrides={"n0": {"input": 1}},
    )
    assert seen[0].pool == "lab"
    assert seen[0].placement.mode == "pool"


def test_explicit_worker_mode_still_pins(monkeypatch):
    from app.core.distributed.backend import DistributedBackend
    from app.core.distributed.registry import get_worker_registry

    reg = get_worker_registry()
    reg.register(_gpu_worker("w-a"))
    reg.register(_gpu_worker("w-b"))
    seen = _capture_jobs(monkeypatch)
    DistributedBackend().execute(
        _graph(IRPlacement(mode="worker", worker="w-a")),
        input_overrides={"n0": {"input": 1}},
    )
    assert seen[0].placement.mode == "worker"
    assert seen[0].placement.worker == "w-a"
    from app.core.distributed.queue import get_job_queue

    assert get_job_queue().get_result(seen[0].job_id).worker_id == "w-a"


def test_resolution_spreads_load_across_nodes(monkeypatch):
    from app.core.distributed.backend import DistributedBackend
    from app.core.distributed.registry import get_worker_registry

    reg = get_worker_registry()
    reg.register(_gpu_worker("w-a"))
    reg.register(_gpu_worker("w-b"))
    captured = {}

    def fake(self, graph, *, placements, **kw):
        captured.update(placements)
        return {}

    monkeypatch.setattr(DistributedBackend, "_execute_with_jobs", fake)
    DistributedBackend().execute(
        _graph(IRPlacement(mode="auto", tags=("gpu",), require_gpu=True), n=4)
    )
    assert sorted(captured.values()) == ["w-a", "w-a", "w-b", "w-b"]


# ── 8. run-end blob cleanup ─────────────────────────────────────────────────


def test_run_end_deletes_job_and_input_blobs(monkeypatch):
    from app.core.distributed.backend import DistributedBackend
    from app.core.distributed.registry import get_worker_registry
    from app.core.distributed.transfer import blob_root

    get_worker_registry().register(_gpu_worker("w-b"))
    seen = _capture_jobs(monkeypatch)
    DistributedBackend().execute(
        _graph(IRPlacement(mode="auto", tags=("gpu",), require_gpu=True), n=2),
        input_overrides={"n0": {"input": 9}},
    )
    assert len(seen) == 2
    root = blob_root()
    leftovers = [p for p in root.rglob("*") if p.is_file()]
    assert leftovers == []


def test_keep_blobs_env_disables_cleanup(monkeypatch):
    from app.core.distributed.backend import DistributedBackend
    from app.core.distributed.registry import get_worker_registry
    from app.core.distributed.transfer import blob_root

    monkeypatch.setenv("GRAPHYN_DISTRIBUTED_KEEP_BLOBS", "1")
    get_worker_registry().register(_gpu_worker("w-b"))
    _capture_jobs(monkeypatch)
    DistributedBackend().execute(
        _graph(IRPlacement(mode="auto", tags=("gpu",), require_gpu=True)),
        input_overrides={"n0": {"input": 9}},
    )
    assert any(p.is_file() for p in blob_root().rglob("*"))


def test_input_blob_shared_with_active_job_is_kept(monkeypatch):
    from app.core.distributed.backend import _cleanup_run_blobs, _blob_mtime_ns
    from app.core.distributed.models import NodeJob
    from app.core.distributed.queue import get_job_queue
    from app.core.distributed.transfer import _safe_path, put_port_value, uri_to_key

    uri = put_port_value({"shared": True})
    other = put_port_value({"mine": True})
    get_job_queue().enqueue(NodeJob(job_id="other-run-job", run_id="other",
                                    node_id="n", node_type="x", input_refs={"i": uri}))
    _cleanup_run_blobs(get_job_queue(), run_id="this", job_ids=[],
                       input_uploads={uri: _blob_mtime_ns(uri), other: _blob_mtime_ns(other)})
    assert _safe_path(uri_to_key(uri)).is_file()
    assert not _safe_path(uri_to_key(other)).is_file()


# ── 9. control plane verifies output sha256 ─────────────────────────────────


def test_tampered_output_blob_fails_run(monkeypatch):
    from app.core.distributed import backend as backend_mod
    from app.core.distributed.backend import DistributedBackend
    from app.core.distributed.queue import JobQueue
    from app.core.distributed.registry import get_worker_registry
    from app.core.distributed.transfer import _safe_path, uri_to_key

    get_worker_registry().register(_gpu_worker("w-b"))
    real_wait = JobQueue.wait_for_result

    def wait(self, job_id, *, timeout_s=None):
        backend_mod.run_loopback_worker_once("w-b")
        res = real_wait(self, job_id, timeout_s=timeout_s)
        if res is not None:
            assert res.output_sha256  # loopback reports digests
            for uri in res.output_refs.values():
                _safe_path(uri_to_key(uri)).write_bytes(b"tampered")
        return res

    monkeypatch.setattr(JobQueue, "wait_for_result", wait)
    with pytest.raises(ValueError, match="hash mismatch"):
        DistributedBackend().execute(
            _graph(IRPlacement(mode="auto", tags=("gpu",), require_gpu=True)),
            input_overrides={"n0": {"input": 3}},
        )
