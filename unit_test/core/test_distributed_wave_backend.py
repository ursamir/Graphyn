"""P1 wave scheduler: remote jobs with artifact refs, no LocalPython rematerialize."""
from __future__ import annotations

from typing import ClassVar

import pytest

from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode, IRPlacement
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.core.runtime_backend import LocalPythonBackend, _reset_backend_registry

_PROCESS_COUNTS: dict[str, int] = {}


def _make_echo_node(nt: str, *, tag: str = "echo"):
    class _Echo(Node):
        input_ports: ClassVar[dict] = {
            "input": InputPort(name="input", data_type=object)
        }
        output_ports: ClassVar[dict] = {
            "output": OutputPort(name="output", data_type=object)
        }

        class Config(NodeConfig):
            suffix: str = "x"

        def process(self, data):
            _PROCESS_COUNTS[self.node_type] = _PROCESS_COUNTS.get(self.node_type, 0) + 1
            return {"value": data, "tag": self.config.suffix}

    _Echo.node_type = nt
    _Echo.metadata = NodeMetadata(
        node_type=nt,
        label=nt,
        description="test echo",
        category="Test",
    )

    class _Cfg(NodeConfig):
        suffix: str = tag

    _Echo.Config = _Cfg
    return _Echo


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
    monkeypatch.delenv("GRAPHYN_BACKEND", raising=False)
    monkeypatch.setenv("GRAPHYN_SKIP_PLUGIN_LOAD", "1")
    monkeypatch.setenv("GRAPHYN_DISTRIBUTED_JOB_TIMEOUT", "15")
    _reset_backend_registry()
    from app.core.distributed.queue import _reset_job_queue
    from app.core.distributed.registry import _reset_worker_registry

    _reset_worker_registry()
    _reset_job_queue()
    _PROCESS_COUNTS.clear()
    yield
    from app.core.nodes import registry

    for nt in ("dist_cpu", "dist_gpu", "dist_gpu_only"):
        try:
            registry.unregister(nt)
        except Exception:
            pass
    _reset_worker_registry()
    _reset_job_queue()
    _reset_backend_registry()


def _register_test_nodes(*types: str):
    from app.core.nodes import registry

    for nt in types:
        cls = _make_echo_node(nt, tag=nt)
        registry.register(
            nt,
            cls,
            NodeMetadata(
                node_type=nt,
                label=nt,
                description="test",
                category="Test",
            ),
        )
    return registry


def _install_sync_loopback(monkeypatch, worker_id: str) -> None:
    """Serve jobs inline when control waits — Thread.start is no-op'd by conftest."""
    from app.core.distributed.backend import run_loopback_worker_once
    from app.core.distributed.queue import JobQueue

    real_wait = JobQueue.wait_for_result

    def _wait(self, job_id, *, timeout_s=None):
        # Drain eligible jobs for this worker before blocking.
        for _ in range(8):
            if not run_loopback_worker_once(worker_id):
                break
        return real_wait(self, job_id, timeout_s=timeout_s)

    monkeypatch.setattr(JobQueue, "wait_for_result", _wait)


def test_compute_ir_waves_linear():
    from app.core.distributed.backend import compute_ir_waves

    graph = GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="w", seed=0),
        nodes=[
            IRNode(id="a", node_type="x", config={}),
            IRNode(id="b", node_type="x", config={}),
            IRNode(id="c", node_type="x", config={}),
        ],
        edges=[
            IREdge(src_id="a", src_port="output", dst_id="b", dst_port="input"),
            IREdge(src_id="b", src_port="output", dst_id="c", dst_port="input"),
        ],
    )
    waves = compute_ir_waves(graph)
    assert waves == [["a"], ["b"], ["c"]]


def test_wave_path_remote_no_local_rematerialize(monkeypatch):
    """Remote node executes once via worker; LocalPythonBackend.execute is NOT called."""
    from app.core.distributed.backend import DistributedBackend
    from app.core.distributed.models import WorkerInfo, WorkerResources
    from app.core.distributed.registry import get_worker_registry
    from app.core.ir.models import IRCapabilityMetadata

    _register_test_nodes("dist_cpu", "dist_gpu")

    calls = {"local_execute": 0}

    def _spy(self, graph, **kwargs):
        calls["local_execute"] += 1
        raise AssertionError("LocalPythonBackend.execute must not run on mixed path")

    monkeypatch.setattr(LocalPythonBackend, "execute", _spy)
    monkeypatch.setattr(
        "app.core.registry_runtime.resolve_capability",
        lambda ir_node, registry: (
            IRCapabilityMetadata(requires_gpu=True)
            if ir_node.node_type == "dist_gpu"
            else IRCapabilityMetadata(requires_gpu=False)
        ),
    )

    get_worker_registry().register(
        WorkerInfo(
            worker_id="gpu-w",
            labels=["gpu"],
            resources=WorkerResources(gpu=True, vram_mib_free=8192),
            plugins=["dist_gpu", "dist_cpu"],
        )
    )
    _install_sync_loopback(monkeypatch, "gpu-w")

    graph = GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="mixed", seed=1),
        nodes=[
            IRNode(
                id="cpu0",
                node_type="dist_cpu",
                config={},
                placement=IRPlacement(mode="local"),
            ),
            IRNode(
                id="gpu0",
                node_type="dist_gpu",
                config={},
                placement=IRPlacement(
                    mode="auto", tags=("gpu",), require_gpu=True
                ),
            ),
        ],
        edges=[
            IREdge(
                src_id="cpu0",
                src_port="output",
                dst_id="gpu0",
                dst_port="input",
            )
        ],
    )

    backend = DistributedBackend()
    result = backend.execute(
        graph,
        input_overrides={"cpu0": {"input": "hello"}},
    )

    assert calls["local_execute"] == 0
    assert _PROCESS_COUNTS.get("dist_cpu") == 1
    assert _PROCESS_COUNTS.get("dist_gpu") == 1
    assert result["output"]["tag"] == "dist_gpu"
    assert result["output"]["value"]["tag"] == "dist_cpu"
    assert backend.last_node_workers.get("gpu0") == "gpu-w"


def test_worker_input_refs_end_to_end_in_process(monkeypatch):
    """Loopback worker hydrates input_refs and uploads output_refs."""
    from app.core.distributed.backend import DistributedBackend
    from app.core.distributed.models import WorkerInfo, WorkerResources
    from app.core.distributed.registry import get_worker_registry
    from app.core.distributed.transfer import get_port_value
    from app.core.distributed.queue import get_job_queue
    from app.core.ir.models import IRCapabilityMetadata

    _register_test_nodes("dist_gpu")
    monkeypatch.setattr(
        "app.core.registry_runtime.resolve_capability",
        lambda ir_node, registry: IRCapabilityMetadata(requires_gpu=True),
    )
    get_worker_registry().register(
        WorkerInfo(
            worker_id="gpu-w2",
            labels=["gpu"],
            resources=WorkerResources(gpu=True, vram_mib_free=8192),
            plugins=["dist_gpu"],
        )
    )
    _install_sync_loopback(monkeypatch, "gpu-w2")
    graph = GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="remote-only", seed=0),
        nodes=[
            IRNode(
                id="g0",
                node_type="dist_gpu",
                config={},
                placement=IRPlacement(
                    mode="auto", tags=("gpu",), require_gpu=True
                ),
            )
        ],
        edges=[],
    )
    result = DistributedBackend().execute(
        graph, input_overrides={"g0": {"input": 7}}
    )

    assert result["output"]["value"] == 7
    assert result["output"]["tag"] == "dist_gpu"
    results = [
        r for r in get_job_queue()._results.values() if r.worker_id == "gpu-w2"
    ]
    assert results
    assert results[-1].output_refs
    for uri in results[-1].output_refs.values():
        assert uri.startswith("artifact://local/")
        assert get_port_value(uri) is not None


def test_fail_closed_when_no_gpu_worker(monkeypatch):
    from app.core.distributed.backend import DistributedBackend
    from app.core.ir.models import IRCapabilityMetadata

    _register_test_nodes("dist_gpu_only")
    monkeypatch.setattr(
        "app.core.registry_runtime.resolve_capability",
        lambda ir_node, registry: IRCapabilityMetadata(requires_gpu=True),
    )
    graph = GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="need-gpu", seed=0),
        nodes=[
            IRNode(
                id="g",
                node_type="dist_gpu_only",
                config={},
                placement=IRPlacement(
                    mode="auto", tags=("gpu",), require_gpu=True
                ),
            )
        ],
        edges=[],
    )
    with pytest.raises(RuntimeError, match="No eligible worker"):
        DistributedBackend().execute(graph)
