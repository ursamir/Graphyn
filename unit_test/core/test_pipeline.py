"""Unit tests for app/core/pipeline.py — Req 4 criteria 5–9."""
from __future__ import annotations

import pytest

from app.core.nodes.errors import PipelineGraphError
from app.core.planner import (
    EdgeSpec,
    NodeSpec,
    PipelineConfig,
    PipelineGraph,
)
from app.core.validation import validate_pipeline


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_linear_config(*node_types: str) -> PipelineConfig:
    """Build a linear PipelineConfig from a sequence of node types."""
    nodes = [
        NodeSpec(node_id=f"{nt}_{i}", node_type=nt, config={})
        for i, nt in enumerate(node_types)
    ]
    edges = [
        EdgeSpec(
            src_id=nodes[i].node_id,
            src_port="output",
            dst_id=nodes[i + 1].node_id,
            dst_port="input",
        )
        for i in range(len(nodes) - 1)
    ]
    return PipelineConfig(seed=42, nodes=nodes, edges=edges)


# ── Topological order ─────────────────────────────────────────────────────────

def test_execution_order_contains_every_node_exactly_once():
    """Req 4.5 — execution_order contains every node exactly once."""
    cfg = _make_linear_config("audio_conditioner", "segmenter")
    graph = PipelineGraph(cfg)
    order = graph.execution_order
    assert len(order) == 2
    assert set(order) == {"audio_conditioner_0", "segmenter_1"}


def test_execution_order_single_node():
    """Single-node pipeline: execution_order has exactly one entry."""
    cfg = _make_linear_config("audio_conditioner")
    graph = PipelineGraph(cfg)
    order = graph.execution_order
    assert order == ["audio_conditioner_0"]


def test_execution_order_respects_dependency():
    """Req 4.6 — for edge A→B, A appears before B in execution_order."""
    cfg = _make_linear_config("audio_conditioner", "segmenter")
    graph = PipelineGraph(cfg)
    order = graph.execution_order
    assert order.index("audio_conditioner_0") < order.index("segmenter_1")


def test_execution_order_three_nodes_linear():
    """Three-node linear pipeline: all nodes present, order respected."""
    cfg = _make_linear_config("audio_conditioner", "segmenter", "audio_conditioner")
    # Rename to avoid duplicate ids
    cfg.nodes[2].node_id = "audio_conditioner_2"
    cfg.edges[1].dst_id = "audio_conditioner_2"
    graph = PipelineGraph(cfg)
    order = graph.execution_order
    assert len(order) == 3
    assert order[0] == "audio_conditioner_0"
    assert order[1] == "segmenter_1"
    assert order[2] == "audio_conditioner_2"


# ── Cycle detection ───────────────────────────────────────────────────────────

def test_cycle_raises_pipeline_graph_error():
    """Req 4.7 — a cycle in the graph raises PipelineGraphError."""
    nodes = [
        NodeSpec(node_id="a", node_type="audio_conditioner", config={}),
        NodeSpec(node_id="b", node_type="segmenter", config={}),
    ]
    # Create a cycle: a→b and b→a
    edges = [
        EdgeSpec(src_id="a", src_port="output", dst_id="b", dst_port="input"),
        EdgeSpec(src_id="b", src_port="output", dst_id="a", dst_port="input"),
    ]
    cfg = PipelineConfig(seed=42, nodes=nodes, edges=edges)
    with pytest.raises(PipelineGraphError):
        PipelineGraph(cfg)


# ── validate_pipeline ─────────────────────────────────────────────────────────

def test_validate_pipeline_accepts_valid_config():
    """Req 4.9 — validate_pipeline returns validated node list for valid config."""
    from app.core.nodes import registry
    config = {
        "pipeline": {
            "seed": 42,
            "nodes": [
                {"type": "audio_conditioner", "config": {}},
            ],
        }
    }
    result = validate_pipeline(config, registry)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["type"] == "audio_conditioner"


def test_validate_pipeline_raises_for_unknown_node_type():
    """Req 4.9 — validate_pipeline raises ValueError for unknown node type."""
    from app.core.nodes import registry
    config = {
        "pipeline": {
            "seed": 42,
            "nodes": [
                {"type": "this_node_does_not_exist_xyz", "config": {}},
            ],
        }
    }
    with pytest.raises(ValueError, match="Unknown node type"):
        validate_pipeline(config, registry)


def test_validate_pipeline_raises_for_invalid_node_config():
    """validate_pipeline raises ValueError for invalid node config."""
    from app.core.nodes import registry
    config = {
        "pipeline": {
            "seed": 42,
            "nodes": [
                {"type": "audio_conditioner", "config": {"target_sample_rate": "not_an_int"}},
            ],
        }
    }
    with pytest.raises(ValueError, match="Invalid config"):
        validate_pipeline(config, registry)


def test_validate_pipeline_raises_for_missing_pipeline_section():
    """validate_pipeline raises ValueError when 'pipeline' key is missing."""
    from app.core.nodes import registry
    with pytest.raises(ValueError, match="Missing 'pipeline'"):
        validate_pipeline({"not_pipeline": {}}, registry)


def test_validate_pipeline_raises_for_missing_seed():
    """validate_pipeline raises ValueError when seed is missing."""
    from app.core.nodes import registry
    config = {
        "pipeline": {
            "nodes": [{"type": "audio_conditioner", "config": {}}],
        }
    }
    with pytest.raises(ValueError):
        validate_pipeline(config, registry)


def test_validate_pipeline_raises_for_empty_nodes():
    """validate_pipeline raises ValueError when nodes list is empty."""
    from app.core.nodes import registry
    config = {
        "pipeline": {
            "seed": 42,
            "nodes": [],
        }
    }
    with pytest.raises(ValueError):
        validate_pipeline(config, registry)


def test_validate_pipeline_two_valid_nodes():
    """validate_pipeline returns two entries for a two-node config."""
    from app.core.nodes import registry
    config = {
        "pipeline": {
            "seed": 42,
            "nodes": [
                {"type": "audio_conditioner", "config": {}},
                {"type": "segmenter", "config": {}},
            ],
        }
    }
    result = validate_pipeline(config, registry)
    assert len(result) == 2
    assert result[0]["type"] == "audio_conditioner"
    assert result[1]["type"] == "segmenter"
