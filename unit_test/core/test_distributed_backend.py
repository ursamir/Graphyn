"""DistributedBackend + get_backend(GRAPHYN_BACKEND) tests."""
from __future__ import annotations

import pytest

from app.core.ir.models import GraphIR, IRMetadata, IRNode
from app.core.runtime_backend import (
    LocalPythonBackend,
    _reset_backend_registry,
    get_backend,
    list_backends,
)


@pytest.fixture(autouse=True)
def _clean_backends(monkeypatch):
    monkeypatch.delenv("GRAPHYN_BACKEND", raising=False)
    _reset_backend_registry()
    yield
    monkeypatch.delenv("GRAPHYN_BACKEND", raising=False)
    _reset_backend_registry()


def test_get_backend_respects_graphyn_backend_env(monkeypatch):
    assert isinstance(get_backend(), LocalPythonBackend)
    monkeypatch.setenv("GRAPHYN_BACKEND", "distributed")
    _reset_backend_registry()
    from app.core.distributed.backend import DistributedBackend

    backend = get_backend()
    assert isinstance(backend, DistributedBackend)
    assert backend.backend_id == "distributed"
    assert "distributed" in list_backends()


def test_get_backend_explicit_overrides_env(monkeypatch):
    monkeypatch.setenv("GRAPHYN_BACKEND", "distributed")
    _reset_backend_registry()
    assert isinstance(get_backend("local_python"), LocalPythonBackend)


def test_distributed_backend_no_workers_equals_local(monkeypatch):
    """With no remote workers and no placement, execute delegates to local."""
    from app.core.distributed.backend import DistributedBackend
    from app.core.distributed.queue import _reset_job_queue
    from app.core.distributed.registry import _reset_worker_registry

    _reset_worker_registry()
    _reset_job_queue()

    graph = GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="echo-graph", seed=0),
        nodes=[IRNode(id="e1", node_type="dist_echo", config={})],
        edges=[],
    )

    backend = DistributedBackend()
    called = {}

    def _fake_local(self, graph, **kwargs):
        called["yes"] = True
        return {"output": "local-ok"}

    monkeypatch.setattr(LocalPythonBackend, "execute", _fake_local)
    # resolve_capability may fail for unknown type — patch it to a CPU capability
    from app.core.ir.models import IRCapabilityMetadata

    monkeypatch.setattr(
        "app.core.registry_runtime.resolve_capability",
        lambda ir_node, registry: IRCapabilityMetadata(requires_gpu=False),
    )
    result = backend.execute(graph)
    assert called.get("yes") is True
    assert result == {"output": "local-ok"}


def test_distributed_all_local_still_short_circuits(monkeypatch):
    """Regression: unconstrained graph still hits LocalPythonBackend once."""
    from app.core.distributed.backend import DistributedBackend
    from app.core.distributed.queue import _reset_job_queue
    from app.core.distributed.registry import _reset_worker_registry
    from app.core.ir.models import IRCapabilityMetadata

    _reset_worker_registry()
    _reset_job_queue()
    graph = GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="local-only", seed=0),
        nodes=[IRNode(id="e1", node_type="anything", config={})],
        edges=[],
    )
    called = {"n": 0}

    def _fake(self, graph, **kwargs):
        called["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(LocalPythonBackend, "execute", _fake)
    monkeypatch.setattr(
        "app.core.registry_runtime.resolve_capability",
        lambda ir_node, registry: IRCapabilityMetadata(requires_gpu=False),
    )
    assert DistributedBackend().execute(graph) == {"ok": True}
    assert called["n"] == 1
