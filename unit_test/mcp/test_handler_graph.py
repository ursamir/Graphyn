# unit_test/mcp/test_handler_graph.py
"""Tests for app/mcp/handlers/graph.py — Req 12."""
from __future__ import annotations

import pytest

from app.mcp.handlers.graph import (
    generate_graph_handler,
    validate_graph_handler,
    get_graph_schema_handler,
    get_graph_capability_summary_handler,
    get_event_schema_handler,
)


class TestGenerateGraph:
    def test_valid_single_node_returns_graph(self):
        """generate_graph with a known node type returns a graph dict."""
        result = generate_graph_handler({"nodes": [{"node_type": "audio_conditioner"}]})
        assert "error" not in result or not result.get("error")
        assert "nodes" in result
        assert "schema_version" in result

    def test_unknown_node_type_returns_error(self):
        """Unknown node_type returns error_type=unknown_node_type."""
        result = generate_graph_handler({"nodes": [{"node_type": "nonexistent_xyz"}]})
        assert result.get("error") is True
        assert result.get("error_type") == "unknown_node_type"
        assert "available_types" in result

    def test_invalid_config_returns_error(self):
        """Invalid node config returns error_type=invalid_node_config."""
        result = generate_graph_handler({
            "nodes": [{"node_type": "audio_conditioner", "config": {"target_sample_rate": "bad"}}]
        })
        assert result.get("error") is True
        assert result.get("error_type") == "invalid_node_config"

    def test_two_nodes_auto_chained(self):
        """Two nodes without explicit edges are auto-chained."""
        result = generate_graph_handler({
            "nodes": [
                {"node_type": "audio_conditioner"},
                {"node_type": "segmenter"},
            ]
        })
        assert "error" not in result or not result.get("error")
        assert len(result["nodes"]) == 2
        assert len(result["edges"]) == 1

    def test_seed_preserved(self):
        """Seed value is preserved in the generated graph."""
        result = generate_graph_handler({
            "nodes": [{"node_type": "audio_conditioner"}],
            "seed": 99,
        })
        assert result["metadata"]["seed"] == 99


class TestValidateGraph:
    def _make_valid_graph(self):
        return generate_graph_handler({"nodes": [{"node_type": "audio_conditioner"}]})

    def test_valid_graph_returns_valid_true(self):
        """validate_graph with valid IR returns valid=True."""
        graph = self._make_valid_graph()
        result = validate_graph_handler({"graph": graph})
        assert result["valid"] is True
        assert result["node_count"] == 1
        assert result["errors"] == []

    def test_invalid_graph_returns_valid_false(self):
        """validate_graph with invalid IR returns valid=False."""
        result = validate_graph_handler({"graph": {"bad": "data"}})
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_missing_graph_returns_valid_false(self):
        """validate_graph with no graph argument returns valid=False."""
        result = validate_graph_handler({})
        assert result["valid"] is False

    def test_wrong_major_version_returns_valid_false(self):
        """validate_graph with wrong major version returns valid=False."""
        graph = self._make_valid_graph()
        graph["schema_version"] = "99.0"
        result = validate_graph_handler({"graph": graph})
        assert result["valid"] is False


class TestGetGraphSchema:
    def test_returns_dict_with_title(self):
        """get_graph_schema returns a dict with title containing 'GraphIR'."""
        result = get_graph_schema_handler({})
        assert isinstance(result, dict)
        title = result.get("title", "")
        assert "GraphIR" in title or "Graph" in title

    def test_returns_json_schema(self):
        """get_graph_schema returns a valid JSON Schema dict."""
        result = get_graph_schema_handler({})
        assert "properties" in result or "$defs" in result or "type" in result


class TestGetGraphCapabilitySummary:
    def test_returns_capability_fields(self):
        """get_graph_capability_summary returns the 5 expected capability fields."""
        graph = generate_graph_handler({"nodes": [{"node_type": "audio_conditioner"}]})
        result = get_graph_capability_summary_handler({"graph": graph})
        assert "any_requires_gpu" in result
        assert "all_support_cpu" in result
        assert "all_support_edge" in result
        assert "all_deterministic" in result
        assert "any_batch_support" in result

    def test_missing_graph_returns_error(self):
        """Missing graph argument returns error dict."""
        result = get_graph_capability_summary_handler({})
        assert result.get("error") is True


class TestGetEventSchema:
    def test_returns_6_event_types(self):
        """get_event_schema returns exactly 6 event type entries."""
        result = get_event_schema_handler({})
        assert "event_types" in result
        assert len(result["event_types"]) == 6

    def test_event_types_have_type_field(self):
        """Each event type entry has a 'type' field."""
        result = get_event_schema_handler({})
        for entry in result["event_types"]:
            assert "type" in entry

    def test_event_types_include_pipeline_start(self):
        """Event types include pipeline_start."""
        result = get_event_schema_handler({})
        types = [e["type"] for e in result["event_types"]]
        assert "pipeline_start" in types

    def test_event_types_include_done_and_error(self):
        """Event types include done and error."""
        result = get_event_schema_handler({})
        types = [e["type"] for e in result["event_types"]]
        assert "done" in types
        assert "error" in types


def _ensure_dummy_node():
    """Register a tiny SISO node on the global registry for generate_graph tests."""
    from typing import ClassVar
    from app.core.nodes import registry
    from app.core.nodes.base import Node
    from app.core.nodes.config import NodeConfig
    from app.core.nodes.metadata import NodeMetadata
    from app.core.nodes.ports import InputPort, OutputPort

    if "wf_dummy" in registry:
        return

    class WfDummy(Node):
        node_type: ClassVar[str] = "wf_dummy"
        input_ports: ClassVar[dict] = {
            "input": InputPort(name="input", data_type=object | None, required=False),
        }
        output_ports: ClassVar[dict] = {
            "output": OutputPort(name="output", data_type=object),
            "true": OutputPort(name="true", data_type=object),
            "false": OutputPort(name="false", data_type=object),
        }
        metadata: ClassVar[NodeMetadata] = NodeMetadata(
            node_type="wf_dummy",
            label="WF Dummy",
            description="Dummy node for MCP generate_graph tests.",
            category="Test",
        )

        class Config(NodeConfig):
            pass

        def process(self, inputs):
            return {"output": inputs.get("input"), "true": None, "false": None}

    registry.register("wf_dummy", WfDummy, WfDummy.metadata)


class TestGenerateGraphConditionAndTrigger:
    def test_preserves_edge_condition(self):
        _ensure_dummy_node()
        result = generate_graph_handler({
            "nodes": [
                {"node_type": "wf_dummy", "id": "src"},
                {"node_type": "wf_dummy", "id": "dst"},
            ],
            "edges": [{
                "src_id": "src",
                "src_port": "output",
                "dst_id": "dst",
                "dst_port": "input",
                "condition": "output['output'] is not None",
            }],
        })
        assert not result.get("error"), result
        assert result["edges"][0]["condition"] == "output['output'] is not None"
        assert result["nodes"][0]["id"] == "src"
        assert result["nodes"][1]["id"] == "dst"

    def test_preserves_event_trigger(self):
        _ensure_dummy_node()
        trigger = {"source_type": "timer", "source_config": {"cron": "0 * * * *"}}
        result = generate_graph_handler({
            "nodes": [{"node_type": "wf_dummy", "id": "sched", "event_trigger": trigger}],
        })
        assert not result.get("error"), result
        assert result["nodes"][0]["event_trigger"]["source_type"] == "timer"
        assert result["nodes"][0]["id"] == "sched"
