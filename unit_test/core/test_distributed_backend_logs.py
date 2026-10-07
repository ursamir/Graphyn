"""Mode B Execution log: DistributedBackend must emit journal/stream events."""
from __future__ import annotations

from typing import ClassVar

import pytest

from app.core.execution.runtime_backend import LocalPythonBackend, _reset_backend_registry
from app.core.ir.models import (
    GraphIR,
    IRCapabilityMetadata,
    IREdge,
    IRMetadata,
    IRNode,
    IRPlacement,
)
from app.core.logger import PipelineLogger
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort


def _make_echo(nt: str):
    class _Echo(Node):
        input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=object)}
        output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=object)}

        class Config(NodeConfig):
            suffix: str = "x"

        def process(self, data):
            return {"value": data, "tag": self.config.suffix}

    _Echo.node_type = nt
    _Echo.metadata = NodeMetadata(node_type=nt, label=nt, description="t", category="Test")
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
    yield
    from app.core.nodes import registry

    for nt in ("log_cpu", "log_gpu"):
        try:
            registry.unregister(nt)
        except Exception:
            pass
    _reset_worker_registry()
    _reset_job_queue()
    _reset_backend_registry()


def _install_sync_loopback(monkeypatch, worker_id: str) -> None:
    from app.core.distributed.backend import run_loopback_worker_once
    from app.core.distributed.queue import JobQueue

    real_wait = JobQueue.wait_for_result

    def _wait(self, job_id, *, timeout_s=None, poll_interval_s=None, **_kwargs):
        for _ in range(8):
            if not run_loopback_worker_once(worker_id=worker_id):
                break
        return real_wait(self, job_id, timeout_s=timeout_s)

    monkeypatch.setattr(JobQueue, "wait_for_result", _wait)


def test_distributed_backend_emits_lifecycle_logs(tmp_path, monkeypatch):
    """Remote Mode B runs must write node_start/node_end into logger + logs.json."""
    import json
    from pathlib import Path

    from app.core.distributed.backend import DistributedBackend
    from app.core.distributed.models import WorkerInfo, WorkerResources
    from app.core.distributed.registry import get_worker_registry
    from app.core.nodes import registry
    from app.core.runs.run_journal import RunManager

    for nt in ("log_cpu", "log_gpu"):
        registry.register(
            nt,
            _make_echo(nt),
            NodeMetadata(node_type=nt, label=nt, description="t", category="Test"),
        )

    monkeypatch.setattr(
        "app.core.host.registry_runtime.resolve_capability",
        lambda ir_node, registry: (
            IRCapabilityMetadata(requires_gpu=True)
            if ir_node.node_type == "log_gpu"
            else IRCapabilityMetadata(requires_gpu=False)
        ),
    )
    get_worker_registry().register(
        WorkerInfo(
            worker_id="w-gpu",
            labels=["gpu"],
            pools=["gpu-lab"],
            resources=WorkerResources(gpu=True, vram_mib_free=8192),
            plugins=["log_gpu", "log_cpu"],
        )
    )
    _install_sync_loopback(monkeypatch, "w-gpu")

    graph = GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="log-graph", seed=0),
        nodes=[
            IRNode(id="a", node_type="log_cpu", config={}, placement=IRPlacement(mode="local")),
            IRNode(
                id="b",
                node_type="log_gpu",
                config={},
                placement=IRPlacement(mode="auto", tags=("gpu",), pool="gpu-lab", require_gpu=True),
            ),
        ],
        edges=[IREdge(src_id="a", src_port="output", dst_id="b", dst_port="input")],
    )

    logger = PipelineLogger()
    run = RunManager()
    DistributedBackend().execute(
        graph,
        logger=logger,
        run_manager=run,
        input_overrides={"a": {"input": "hello"}},
    )

    types = [e.get("type") for e in logger.logs if isinstance(e, dict) and e.get("type")]
    assert "pipeline_start" in types
    assert types.count("node_start") >= 2
    assert types.count("node_end") >= 2
    assert "done" in types

    logs_file = Path(run.base_path) / "logs.json"
    assert logs_file.exists()
    disk = json.loads(logs_file.read_text())
    disk_types = [e.get("type") for e in disk if isinstance(e, dict)]
    assert "pipeline_start" in disk_types
    assert "node_start" in disk_types
    meta = json.loads((Path(run.base_path) / "meta.json").read_text())
    assert meta.get("status") == "succeeded"
