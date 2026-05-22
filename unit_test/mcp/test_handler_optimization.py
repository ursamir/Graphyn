# unit_test/mcp/test_handler_optimization.py
"""Tests for app/mcp/handlers/optimization.py — Req 12."""
from __future__ import annotations

from app.mcp.handlers.optimization import optimize_execution_handler
from app.mcp.handlers.graph import generate_graph_handler


def _valid_graph():
    return generate_graph_handler({"nodes": [{"node_type": "audio_conditioner"}]})


class TestOptimizeExecution:
    def test_smoke_returns_dict(self):
        """optimize_execution returns a dict."""
        graph = _valid_graph()
        result = optimize_execution_handler({"graph": graph})
        assert isinstance(result, dict)

    def test_returns_expected_fields(self):
        """Result contains node_count, edge_count, execution_waves, recommendations."""
        graph = _valid_graph()
        result = optimize_execution_handler({"graph": graph})
        assert "node_count" in result
        assert "edge_count" in result
        assert "execution_waves" in result
        assert "recommendations" in result
        assert isinstance(result["recommendations"], list)

    def test_node_count_correct(self):
        """node_count matches the number of nodes in the graph."""
        graph = _valid_graph()
        result = optimize_execution_handler({"graph": graph})
        assert result["node_count"] == 1

    def test_two_node_graph(self):
        """Two-node graph returns correct node_count and edge_count."""
        graph = generate_graph_handler({
            "nodes": [
                {"node_type": "audio_conditioner"},
                {"node_type": "segmenter"},
            ]
        })
        result = optimize_execution_handler({"graph": graph})
        assert result["node_count"] == 2
        assert result["edge_count"] == 1

    def test_missing_graph_returns_error(self):
        """Missing graph argument returns error dict."""
        result = optimize_execution_handler({})
        assert result.get("error") is True
        assert result.get("error_type") == "missing_argument"

    def test_invalid_graph_returns_error(self):
        """Invalid graph returns error dict."""
        result = optimize_execution_handler({"graph": {"bad": "data"}})
        assert result.get("error") is True

    def test_can_parallelize_field_present(self):
        """can_parallelize field is present in result."""
        graph = _valid_graph()
        result = optimize_execution_handler({"graph": graph})
        assert "can_parallelize" in result

    def test_source_and_sink_nodes_present(self):
        """source_nodes and sink_nodes fields are present."""
        graph = _valid_graph()
        result = optimize_execution_handler({"graph": graph})
        assert "source_nodes" in result
        assert "sink_nodes" in result
