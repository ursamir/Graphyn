"""Leftover fixes: Mode B (DistributedBackend) logical vs materialized graph.

Same contract as the local orchestrator: outputs are scoped to the run, but
graph_hash, per-node seeds and cache keys come from the logical graph so they
are stable across runs (resume / checkpoint lookup / provenance / seeds).
"""
from __future__ import annotations

import json
import os
from typing import ClassVar

import pytest
from pydantic import Field

from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode, IRPlacement
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.core.execution.runtime_backend import _reset_backend_registry

_NT = "lo_seed_echo"


class _SeedEcho(Node):
    node_type: ClassVar[str] = _NT
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type=_NT, label=_NT, description="t", category="Test"
    )
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=object)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=object)}

    class Config(NodeConfig):
        output_dir: str = Field(default="")

    def process(self, data):
        return {"value": data, "seed": self.seed, "output_dir": self.config.output_dir}


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
    registry.register(_NT, _SeedEcho, _SeedEcho.metadata)
    yield
    try:
        registry.unregister(_NT)
    except Exception:
        pass
    _reset_worker_registry()
    _reset_job_queue()
    _reset_backend_registry()


def _graph() -> GraphIR:
    placement = IRPlacement(mode="auto", tags=("gpu",), require_gpu=True)
    return GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="leftover", seed=7),
        nodes=[
            IRNode(id="a", node_type=_NT,
                   config={"output_dir": "workspace/artifacts/leftover/out"},
                   placement=placement),
            IRNode(id="b", node_type=_NT, config={}),  # local on the control plane
        ],
        edges=[IREdge(src_id="a", src_port="output", dst_id="b", dst_port="input")],
    )


def _worker():
    from app.core.distributed.models import WorkerInfo, WorkerResources
    from app.core.distributed.registry import get_worker_registry

    get_worker_registry().register(WorkerInfo(
        worker_id="w-1", labels=["gpu"],
        resources=WorkerResources(gpu=True, vram_mib_free=8192),
        plugins=[_NT],
    ))


def _capture_jobs(monkeypatch):
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
        run_loopback_worker_once("w-1")
        return real_wait(self, job_id, timeout_s=timeout_s)

    monkeypatch.setattr(JobQueue, "enqueue", enqueue)
    monkeypatch.setattr(JobQueue, "wait_for_result", wait)
    return seen


def _meta(run) -> dict:
    with open(os.path.join(run.base_path, "meta.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _run_once(monkeypatch):
    from app.core.distributed.backend import DistributedBackend
    from app.core.runs.run_journal import RunManager

    seen = _capture_jobs(monkeypatch)
    run = RunManager()
    DistributedBackend().execute(
        _graph(), input_overrides={"a": {"input": 1}}, run_manager=run, use_cache=True,
    )
    return run, seen


def test_modeb_graph_hash_is_logical_and_stable(monkeypatch):
    from app.core.execution.orchestrator import _logical_graph_hash

    _worker()
    run1, jobs1 = _run_once(monkeypatch)
    run2, jobs2 = _run_once(monkeypatch)

    logical = _logical_graph_hash(_graph())
    m1, m2 = _meta(run1), _meta(run2)
    assert m1["graph_hash"] == m2["graph_hash"] == logical
    # The materialized graph (run-scoped paths) is recorded separately.
    assert m1.get("materialized_graph_hash") and m1["materialized_graph_hash"] != logical
    assert m1["materialized_graph_hash"] != m2.get("materialized_graph_hash")
    assert run1._graph_hash == logical
    # Cache keys come from the logical config: run 2 hits the cache for the
    # remote node instead of re-enqueueing it.
    assert len(jobs1) == 1
    assert jobs2 == []


def test_modeb_jobs_run_scoped_and_seeded_from_logical_config(monkeypatch):
    from app.core.execution.planner import derive_node_seed

    _worker()
    run, jobs = _run_once(monkeypatch)
    assert len(jobs) == 1
    job = jobs[0]
    # Execution config is run-scoped (outputs under runs/<run_id>/) ...
    assert f"/runs/{run.run_id}/" in job.config["output_dir"]
    # ... but the seed derives from the logical config, identical to Mode A.
    expected = derive_node_seed(7, _NT, 0, {"output_dir": "workspace/artifacts/leftover/out"})
    assert job.seed == expected
    assert _meta(run).get("artifacts_dir")


def test_modeb_node_seed_matches_mode_a_pipeline_graph():
    """PipelineGraph (Mode A) and the distributed backend share derive_node_seed."""
    from app.core.execution.planner import PipelineGraph, _ir_to_pipeline_config, derive_node_seed
    from app.core.paths.workspace_paths import scope_outputs_to_run

    graph = _graph()
    logical = {n.id: dict(n.config) for n in graph.nodes}
    scoped = scope_outputs_to_run(graph, "rid123")
    pg = PipelineGraph(_ir_to_pipeline_config(scoped), seed_configs=logical)
    for i, n in enumerate(graph.nodes):
        assert pg.get_node(n.id).seed == derive_node_seed(7, _NT, i, logical[n.id])


def test_modeb_custom_run_manager_without_logical_hash_kw(monkeypatch):
    """Run managers whose save_graph_ir lacks logical_hash still work."""
    from app.core.distributed.backend import DistributedBackend
    from app.core.runs.run_journal import RunManager

    class _Legacy(RunManager):
        def save_graph_ir(self, graph_data):  # type: ignore[override]
            return super().save_graph_ir(graph_data)

    _worker()
    _capture_jobs(monkeypatch)
    run = _Legacy()
    DistributedBackend().execute(_graph(), input_overrides={"a": {"input": 1}}, run_manager=run)
    assert _meta(run).get("graph_hash")
