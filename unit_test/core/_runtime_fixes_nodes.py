"""Tiny test nodes + helpers shared by unit_test/core/test_runtime_fixes_*.py."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, ClassVar

import pytest

from app.core.artifacts.artifact_serializer import ArtifactTypeHandler, get_serializer_registry
from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode
from app.core.nodes import registry as global_registry
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.core.nodes.retry import RetryPolicy

CALLS: dict[str, int] = defaultdict(int)
TEARDOWNS: dict[str, int] = defaultdict(int)
SEEDS: dict[str, list[int]] = defaultdict(list)
HOOKS: dict[str, Any] = {}

ITEM_TYPE = "rtfix_items"


def _items(value: int) -> list[dict]:
    return [{"rt": True, "v": value}]


class RtSource(Node):
    node_type: ClassVar[str] = "rtfix_source"
    input_ports: ClassVar[dict] = {}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(NodeConfig):
        value: int = 1
        output_dir: str = ""

    def process(self, inputs):
        CALLS[self.node_type] += 1
        SEEDS[self.node_type].append(self.seed)
        hook = HOOKS.get(self.node_type)
        if hook:
            hook(self, inputs)
        return {"output": _items(self.config.value)}

    def teardown(self) -> None:
        TEARDOWNS[self.node_type] += 1


class RtAdd(Node):
    node_type: ClassVar[str] = "rtfix_add"
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(NodeConfig):
        inc: int = 1

    def process(self, inputs):
        CALLS[self.node_type] += 1
        hook = HOOKS.get(self.node_type)
        if hook:
            hook(self, inputs)
        return {"output": _items(inputs["input"][0]["v"] + self.config.inc)}

    def teardown(self) -> None:
        TEARDOWNS[self.node_type] += 1


class RtSink(Node):
    node_type: ClassVar[str] = "rtfix_sink"
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(NodeConfig):
        pass

    def process(self, inputs):
        CALLS[self.node_type] += 1
        hook = HOOKS.get(self.node_type)
        if hook:
            hook(self, inputs)
        return {"output": list(inputs["input"])}

    def teardown(self) -> None:
        TEARDOWNS[self.node_type] += 1


class RtFlaky(Node):
    """Always raises a retryable error; RetryPolicy with long back-off."""

    node_type: ClassVar[str] = "rtfix_flaky"
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}
    retry_policy: ClassVar[RetryPolicy | None] = RetryPolicy(
        max_attempts=5, backoff_seconds=30.0, backoff_multiplier=1.0, max_wait_seconds=30.0
    )

    class Config(NodeConfig):
        pass

    def process(self, inputs):
        CALLS[self.node_type] += 1
        hook = HOOKS.get(self.node_type)
        if hook:
            hook(self, inputs)
        raise RuntimeError("transient")


class RtBadSetup(RtSink):
    node_type: ClassVar[str] = "rtfix_badsetup"

    def setup(self) -> None:
        raise RuntimeError("setup exploded")


_NODE_CLASSES = [RtSource, RtAdd, RtSink, RtFlaky, RtBadSetup]


class _ItemsHandler(ArtifactTypeHandler):
    """Serializer for list[{"rt": True, ...}] so checkpoints can be written."""

    def serialize(self, data, dest_dir: Path) -> None:
        (dest_dir / "items.json").write_text(json.dumps(data), encoding="utf-8")

    def deserialize(self, src_dir: Path):
        path = src_dir / "items.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def compute_content_hash_input(self, data) -> str:
        return json.dumps(data, sort_keys=True)

    def infer_type(self, value):
        if isinstance(value, list) and value and isinstance(value[0], dict) and value[0].get("rt"):
            return ITEM_TYPE
        return None


@pytest.fixture
def rt_env(tmp_path, monkeypatch):
    """Isolated workspace + tiny nodes registered in the global registry."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(ws))
    CALLS.clear()
    TEARDOWNS.clear()
    SEEDS.clear()
    HOOKS.clear()
    for cls in _NODE_CLASSES:
        global_registry.register(
            cls.node_type,
            cls,
            NodeMetadata(
                node_type=cls.node_type,
                label=cls.node_type,
                description="runtime-fix test node",
                category="Test",
                cacheable=cls is not RtSink,
            ),
        )
    ser = get_serializer_registry()
    handler = _ItemsHandler()
    ser.register(ITEM_TYPE, handler)
    yield ws
    for cls in _NODE_CLASSES:
        global_registry.unregister(cls.node_type)
    with ser._lock:
        ser._handlers.pop(ITEM_TYPE, None)
        if handler in ser._ordered:
            ser._ordered.remove(handler)
    HOOKS.clear()


def make_graph(
    nodes: list[tuple[str, str, dict]],
    edges: list[tuple[str, str, str, str]] | None = None,
    *,
    name: str = "rtfix",
    seed: int = 0,
    triggers: dict[str, dict] | None = None,
) -> GraphIR:
    triggers = triggers or {}
    return GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name=name, seed=seed),
        nodes=[
            IRNode(id=nid, node_type=nt, config=cfg, event_trigger=triggers.get(nid))
            for nid, nt, cfg in nodes
        ],
        edges=[
            IREdge(src_id=a, src_port=ap, dst_id=b, dst_port=bp) for a, ap, b, bp in (edges or [])
        ],
    )


def chain_graph(name: str = "rtfix", output_dir: str = "") -> GraphIR:
    """a (source) → b (add) → c (sink)."""
    return make_graph(
        [
            ("a", "rtfix_source", {"value": 1, "output_dir": output_dir}),
            ("b", "rtfix_add", {"inc": 10}),
            ("c", "rtfix_sink", {}),
        ],
        [("a", "output", "b", "input"), ("b", "output", "c", "input")],
        name=name,
    )


def read_meta(run) -> dict:
    return json.loads((Path(run.base_path) / "meta.json").read_text(encoding="utf-8"))
