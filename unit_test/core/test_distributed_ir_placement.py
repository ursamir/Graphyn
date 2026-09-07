"""IRPlacement + IR 1.2 loader compatibility tests."""
from __future__ import annotations

import pytest

from app.core.ir.loader import CURRENT_IR_VERSION, dump_ir, load_ir
from app.core.ir.models import GraphIR, IRMetadata, IRNode, IRPlacement


def test_current_ir_version_is_1_2():
    assert CURRENT_IR_VERSION == "1.2"


def test_ir_placement_round_trip():
    placement = IRPlacement(
        mode="auto",
        tags=("gpu",),
        require_gpu=True,
        min_vram_mib=4096,
    )
    graph = GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="placed", seed=1),
        nodes=[
            IRNode(
                id="trainer_0",
                node_type="trainer",
                placement=placement,
            )
        ],
    )
    restored = load_ir(dump_ir(graph))
    assert restored.nodes[0].placement is not None
    assert restored.nodes[0].placement.mode == "auto"
    assert restored.nodes[0].placement.tags == ("gpu",)
    assert restored.nodes[0].placement.require_gpu is True
    assert restored.nodes[0].placement.min_vram_mib == 4096
    assert restored == graph


def test_ir_1_1_graph_still_loads_without_placement():
    data = {
        "schema_version": "1.1",
        "metadata": {"name": "legacy", "seed": 0},
        "nodes": [{"id": "n1", "node_type": "passthrough"}],
        "edges": [],
    }
    graph = load_ir(data)
    assert graph.schema_version == "1.1"
    assert graph.nodes[0].placement is None


def test_missing_placement_defaults_to_none():
    graph = GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="noplace", seed=0),
        nodes=[IRNode(id="a", node_type="x")],
    )
    assert graph.nodes[0].placement is None
    restored = load_ir(dump_ir(graph))
    assert restored.nodes[0].placement is None
