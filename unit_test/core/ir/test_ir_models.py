# unit_test/core/ir/test_ir_models.py
"""Tests for app/core/ir/models.py — Req 4 criteria 1–4, Req 16 criterion 2."""
from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode
from app.core.ir.loader import dump_ir, load_ir


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_node(node_id: str = "node_a", node_type: str = "audio_conditioner") -> IRNode:
    return IRNode(id=node_id, node_type=node_type)


def _make_graph(nodes: list[IRNode], edges: list[IREdge] | None = None) -> GraphIR:
    return GraphIR(
        schema_version="1.1",
        metadata=IRMetadata(name="test_graph", seed=42),
        nodes=nodes,
        edges=edges or [],
    )


# ── Req 4.2: Duplicate node ID raises ValueError ──────────────────────────────

class TestDuplicateNodeId:
    def test_duplicate_id_raises_value_error(self):
        node_a1 = _make_node("node_a")
        node_a2 = _make_node("node_a")
        with pytest.raises(ValueError, match="Duplicate node id"):
            _make_graph([node_a1, node_a2])

    def test_unique_ids_do_not_raise(self):
        node_a = _make_node("node_a")
        node_b = _make_node("node_b")
        graph = _make_graph([node_a, node_b])
        assert len(graph.nodes) == 2

    def test_three_nodes_with_one_duplicate_raises(self):
        nodes = [_make_node("a"), _make_node("b"), _make_node("a")]
        with pytest.raises(ValueError, match="Duplicate node id"):
            _make_graph(nodes)


# ── Req 4.3: Bad edge reference raises ValueError ─────────────────────────────

class TestEdgeReferenceIntegrity:
    def test_unknown_src_id_raises(self):
        node_a = _make_node("node_a")
        bad_edge = IREdge(src_id="nonexistent", src_port="output", dst_id="node_a", dst_port="input")
        with pytest.raises(ValueError, match="unknown source node id"):
            _make_graph([node_a], [bad_edge])

    def test_unknown_dst_id_raises(self):
        node_a = _make_node("node_a")
        bad_edge = IREdge(src_id="node_a", src_port="output", dst_id="nonexistent", dst_port="input")
        with pytest.raises(ValueError, match="unknown destination node id"):
            _make_graph([node_a], [bad_edge])

    def test_valid_edge_does_not_raise(self):
        node_a = _make_node("node_a")
        node_b = _make_node("node_b")
        edge = IREdge(src_id="node_a", src_port="output", dst_id="node_b", dst_port="input")
        graph = _make_graph([node_a, node_b], [edge])
        assert len(graph.edges) == 1

    def test_both_src_and_dst_unknown_raises(self):
        node_a = _make_node("node_a")
        bad_edge = IREdge(src_id="x", src_port="output", dst_id="y", dst_port="input")
        with pytest.raises(ValueError):
            _make_graph([node_a], [bad_edge])


# ── Req 4.4: Invalid node ID chars raise ValueError ───────────────────────────

class TestNodeIdValidation:
    @pytest.mark.parametrize("bad_id", [
        "node a",       # space
        "node.a",       # dot
        "node/a",       # slash
        "node@1",       # at-sign
        "nöde",         # non-ASCII
        "node!",        # exclamation
        "",             # empty string (also caught by pydantic)
    ])
    def test_invalid_id_chars_raise(self, bad_id: str):
        with pytest.raises((ValueError, Exception)):
            IRNode(id=bad_id, node_type="audio_conditioner")

    @pytest.mark.parametrize("good_id", [
        "node_a",
        "node-b",
        "NodeA",
        "node123",
        "A",
        "a-b_c-D1",
    ])
    def test_valid_id_chars_accepted(self, good_id: str):
        node = IRNode(id=good_id, node_type="audio_conditioner")
        assert node.id == good_id


# ── Req 4.1 / Req 16.2: Idempotent round-trip property (Hypothesis) ──────────

# Strategies for generating valid GraphIR objects
_valid_id = st.from_regex(r"[A-Za-z][A-Za-z0-9_-]{0,15}", fullmatch=True)
_valid_node_type = st.from_regex(r"[a-z][a-z0-9_]{0,19}", fullmatch=True)
_valid_name = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_- "),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip())


@st.composite
def valid_graph_ir(draw: st.DrawFn) -> GraphIR:
    """Generate a valid GraphIR with 1–5 nodes and auto-chained edges."""
    n_nodes = draw(st.integers(min_value=1, max_value=5))

    # Generate unique node IDs
    ids = draw(
        st.lists(
            _valid_id,
            min_size=n_nodes,
            max_size=n_nodes,
            unique=True,
        )
    )
    node_types = draw(
        st.lists(_valid_node_type, min_size=n_nodes, max_size=n_nodes)
    )
    nodes = [IRNode(id=ids[i], node_type=node_types[i]) for i in range(n_nodes)]

    # Auto-chain edges (linear pipeline)
    edges = [
        IREdge(
            src_id=ids[i],
            src_port="output",
            dst_id=ids[i + 1],
            dst_port="input",
        )
        for i in range(n_nodes - 1)
    ]

    name = draw(_valid_name)
    seed = draw(st.integers(min_value=0, max_value=2**31 - 1))

    return GraphIR(
        schema_version="1.1",
        metadata=IRMetadata(name=name, seed=seed),
        nodes=nodes,
        edges=edges,
    )


class TestRoundTripProperty:
    """Req 4.1: load_ir(dump_ir(graph)) == graph for all valid graphs."""

    @given(graph=valid_graph_ir())
    @settings(max_examples=100)
    def test_round_trip_idempotent(self, graph: GraphIR):
        """Validates: Requirements 4.1"""
        restored = load_ir(dump_ir(graph))
        assert restored == graph

    @given(graph=valid_graph_ir())
    @settings(max_examples=100)
    def test_round_trip_preserves_node_count(self, graph: GraphIR):
        """Validates: Requirements 4.1"""
        restored = load_ir(dump_ir(graph))
        assert len(restored.nodes) == len(graph.nodes)

    @given(graph=valid_graph_ir())
    @settings(max_examples=100)
    def test_round_trip_preserves_edge_count(self, graph: GraphIR):
        """Validates: Requirements 4.1"""
        restored = load_ir(dump_ir(graph))
        assert len(restored.edges) == len(graph.edges)

    @given(graph=valid_graph_ir())
    @settings(max_examples=100)
    def test_round_trip_preserves_seed(self, graph: GraphIR):
        """Validates: Requirements 4.1"""
        restored = load_ir(dump_ir(graph))
        assert restored.metadata.seed == graph.metadata.seed
