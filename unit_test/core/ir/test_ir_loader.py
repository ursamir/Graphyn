# unit_test/core/ir/test_ir_loader.py
"""Tests for app/core/ir/loader.py — Req 4 criteria 1–4."""
from __future__ import annotations

import pytest

from app.core.ir.loader import (
    IRVersionError,
    dump_ir,
    load_ir,
    CURRENT_IR_VERSION,
    SUPPORTED_MAJOR,
)
from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode


# ── Helpers ───────────────────────────────────────────────────────────────────

def _minimal_graph(schema_version: str = "1.1") -> GraphIR:
    return GraphIR(
        schema_version=schema_version,
        metadata=IRMetadata(name="test", seed=0),
        nodes=[IRNode(id="node_a", node_type="audio_conditioner")],
        edges=[],
    )


def _two_node_graph() -> GraphIR:
    return GraphIR(
        schema_version="1.1",
        metadata=IRMetadata(name="two_node", seed=99),
        nodes=[
            IRNode(id="src", node_type="dataset_ingest"),
            IRNode(id="dst", node_type="audio_conditioner"),
        ],
        edges=[
            IREdge(src_id="src", src_port="output", dst_id="dst", dst_port="input")
        ],
    )


# ── IR round-trip ─────────────────────────────────────────────────────────────

class TestIRRoundTrip:
    def test_load_dump_round_trip_minimal(self):
        graph = _minimal_graph()
        restored = load_ir(dump_ir(graph))
        assert restored == graph

    def test_load_dump_round_trip_two_nodes(self):
        graph = _two_node_graph()
        restored = load_ir(dump_ir(graph))
        assert restored == graph

    def test_round_trip_preserves_metadata(self):
        graph = _minimal_graph()
        restored = load_ir(dump_ir(graph))
        assert restored.metadata.name == graph.metadata.name
        assert restored.metadata.seed == graph.metadata.seed

    def test_round_trip_preserves_node_ids(self):
        graph = _two_node_graph()
        restored = load_ir(dump_ir(graph))
        original_ids = {n.id for n in graph.nodes}
        restored_ids = {n.id for n in restored.nodes}
        assert original_ids == restored_ids

    def test_round_trip_preserves_edges(self):
        graph = _two_node_graph()
        restored = load_ir(dump_ir(graph))
        assert len(restored.edges) == len(graph.edges)
        assert restored.edges[0].src_id == graph.edges[0].src_id
        assert restored.edges[0].dst_id == graph.edges[0].dst_id

    def test_dump_returns_dict(self):
        graph = _minimal_graph()
        data = dump_ir(graph)
        assert isinstance(data, dict)
        assert "schema_version" in data
        assert "nodes" in data

    def test_load_from_dict_returns_graph_ir(self):
        graph = _minimal_graph()
        data = dump_ir(graph)
        restored = load_ir(data)
        assert isinstance(restored, GraphIR)


# ── Version validation ────────────────────────────────────────────────────────

class TestVersionValidation:
    def test_wrong_major_version_raises_ir_version_error(self):
        """Req 4: wrong major version raises IRVersionError."""
        graph = _minimal_graph()
        data = dump_ir(graph)
        data["schema_version"] = "2.0"
        with pytest.raises(IRVersionError):
            load_ir(data)

    def test_major_version_zero_raises_ir_version_error(self):
        graph = _minimal_graph()
        data = dump_ir(graph)
        data["schema_version"] = "0.9"
        with pytest.raises(IRVersionError):
            load_ir(data)

    def test_major_version_99_raises_ir_version_error(self):
        graph = _minimal_graph()
        data = dump_ir(graph)
        data["schema_version"] = "99.0"
        with pytest.raises(IRVersionError):
            load_ir(data)

    def test_minor_version_difference_is_accepted(self):
        """Req 4: minor version difference does not raise."""
        graph = _minimal_graph()
        data = dump_ir(graph)
        # Use a lower minor version (1.0 is still supported)
        data["schema_version"] = "1.0"
        # Should not raise
        restored = load_ir(data)
        assert isinstance(restored, GraphIR)

    def test_current_version_is_accepted(self):
        graph = _minimal_graph()
        data = dump_ir(graph)
        assert data["schema_version"] == CURRENT_IR_VERSION
        restored = load_ir(data)
        assert isinstance(restored, GraphIR)

    def test_ir_version_error_is_value_error_subclass(self):
        assert issubclass(IRVersionError, ValueError)
