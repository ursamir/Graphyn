# unit_test/core/ir/test_yaml_shim.py
"""Tests for app/core/ir/yaml_shim.py — YAML → GraphIR conversion."""
from __future__ import annotations

import pytest

from app.core.ir.yaml_shim import yaml_config_to_ir
from app.core.ir.models import GraphIR


# ── Helpers ───────────────────────────────────────────────────────────────────

def _raw(nodes: list[dict], edges: list[dict] | None = None, seed: int = 0, name: str = "test") -> dict:
    pipeline: dict = {"name": name, "seed": seed, "nodes": nodes}
    if edges is not None:
        pipeline["edges"] = edges
    return {"pipeline": pipeline}


# ── YAML dict → GraphIR with correct node count ───────────────────────────────

class TestYamlToIRNodeCount:
    def test_single_node(self):
        raw = _raw([{"type": "audio_conditioner"}])
        graph = yaml_config_to_ir(raw)
        assert isinstance(graph, GraphIR)
        assert len(graph.nodes) == 1

    def test_three_nodes(self):
        raw = _raw([
            {"type": "dataset_ingest"},
            {"type": "audio_conditioner"},
            {"type": "feature_frontend"},
        ])
        graph = yaml_config_to_ir(raw)
        assert len(graph.nodes) == 3

    def test_node_types_preserved(self):
        raw = _raw([
            {"type": "dataset_ingest"},
            {"type": "audio_conditioner"},
        ])
        graph = yaml_config_to_ir(raw)
        types = [n.node_type for n in graph.nodes]
        assert "dataset_ingest" in types
        assert "audio_conditioner" in types

    def test_empty_nodes_list(self):
        raw = _raw([])
        graph = yaml_config_to_ir(raw)
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0


# ── Auto-chained edges when no explicit edges given ───────────────────────────

class TestAutoChainedEdges:
    def test_two_nodes_auto_chain(self):
        raw = _raw([
            {"type": "dataset_ingest"},
            {"type": "audio_conditioner"},
        ])
        graph = yaml_config_to_ir(raw)
        assert len(graph.edges) == 1
        edge = graph.edges[0]
        assert edge.src_port == "output"
        assert edge.dst_port == "input"

    def test_three_nodes_auto_chain(self):
        raw = _raw([
            {"type": "dataset_ingest"},
            {"type": "audio_conditioner"},
            {"type": "feature_frontend"},
        ])
        graph = yaml_config_to_ir(raw)
        # 3 nodes → 2 edges
        assert len(graph.edges) == 2

    def test_auto_chain_connects_consecutive_nodes(self):
        raw = _raw([
            {"type": "node_a", "id": "n0"},
            {"type": "node_b", "id": "n1"},
            {"type": "node_c", "id": "n2"},
        ])
        graph = yaml_config_to_ir(raw)
        assert graph.edges[0].src_id == "n0"
        assert graph.edges[0].dst_id == "n1"
        assert graph.edges[1].src_id == "n1"
        assert graph.edges[1].dst_id == "n2"

    def test_single_node_no_edges(self):
        raw = _raw([{"type": "audio_conditioner"}])
        graph = yaml_config_to_ir(raw)
        assert len(graph.edges) == 0


# ── Seed is preserved ─────────────────────────────────────────────────────────

class TestSeedPreservation:
    def test_seed_preserved(self):
        raw = _raw([{"type": "audio_conditioner"}], seed=12345)
        graph = yaml_config_to_ir(raw)
        assert graph.metadata.seed == 12345

    def test_seed_zero_preserved(self):
        raw = _raw([{"type": "audio_conditioner"}], seed=0)
        graph = yaml_config_to_ir(raw)
        assert graph.metadata.seed == 0

    def test_seed_default_is_zero(self):
        # No seed key in pipeline dict
        raw = {"pipeline": {"name": "test", "nodes": [{"type": "audio_conditioner"}]}}
        graph = yaml_config_to_ir(raw)
        assert graph.metadata.seed == 0

    def test_large_seed_preserved(self):
        raw = _raw([{"type": "audio_conditioner"}], seed=999999)
        graph = yaml_config_to_ir(raw)
        assert graph.metadata.seed == 999999


# ── Explicit edges override auto-chain ────────────────────────────────────────

class TestExplicitEdges:
    def test_explicit_edges_used_instead_of_auto_chain(self):
        raw = _raw(
            nodes=[
                {"type": "dataset_ingest", "id": "src"},
                {"type": "audio_conditioner", "id": "mid"},
                {"type": "feature_frontend", "id": "dst"},
            ],
            edges=[
                {"src_id": "src", "src_port": "output", "dst_id": "dst", "dst_port": "input"}
            ],
        )
        graph = yaml_config_to_ir(raw)
        # Only 1 explicit edge, not 2 auto-chained
        assert len(graph.edges) == 1
        assert graph.edges[0].src_id == "src"
        assert graph.edges[0].dst_id == "dst"

    def test_explicit_edges_list_format(self):
        raw = _raw(
            nodes=[
                {"type": "dataset_ingest", "id": "src"},
                {"type": "audio_conditioner", "id": "dst"},
            ],
            edges=[
                {"from": ["src", "output"], "to": ["dst", "input"]}
            ],
        )
        graph = yaml_config_to_ir(raw)
        assert len(graph.edges) == 1
        assert graph.edges[0].src_id == "src"
        assert graph.edges[0].dst_id == "dst"
        assert graph.edges[0].src_port == "output"
        assert graph.edges[0].dst_port == "input"

    def test_explicit_empty_edges_list_falls_back_to_auto_chain(self):
        # The shim uses `if raw_edges:` which is falsy for an empty list,
        # so an empty explicit edges list triggers auto-chain (same as no edges key).
        raw = _raw(
            nodes=[
                {"type": "dataset_ingest", "id": "src"},
                {"type": "audio_conditioner", "id": "dst"},
            ],
            edges=[],
        )
        graph = yaml_config_to_ir(raw)
        # Empty list is falsy → auto-chain kicks in → 1 edge
        assert len(graph.edges) == 1

    def test_multiple_explicit_edges(self):
        raw = _raw(
            nodes=[
                {"type": "dataset_ingest", "id": "a"},
                {"type": "audio_conditioner", "id": "b"},
                {"type": "feature_frontend", "id": "c"},
            ],
            edges=[
                {"src_id": "a", "src_port": "output", "dst_id": "b", "dst_port": "input"},
                {"src_id": "b", "src_port": "output", "dst_id": "c", "dst_port": "input"},
            ],
        )
        graph = yaml_config_to_ir(raw)
        assert len(graph.edges) == 2
