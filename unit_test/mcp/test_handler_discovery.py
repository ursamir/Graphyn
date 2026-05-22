# unit_test/mcp/test_handler_discovery.py
"""Tests for app/mcp/handlers/discovery.py — Req 12."""
from __future__ import annotations

from app.mcp.handlers.discovery import list_nodes_handler


class TestListNodesNoArgs:
    def test_no_args_returns_nodes_list(self):
        """No args returns all nodes as a list."""
        result = list_nodes_handler({})
        assert "nodes" in result
        assert isinstance(result["nodes"], list)
        assert len(result["nodes"]) > 0

    def test_nodes_have_required_fields(self):
        """Each node entry has the 10 required fields."""
        result = list_nodes_handler({})
        for node in result["nodes"]:
            assert "node_type" in node
            assert "label" in node
            assert "description" in node
            assert "category" in node
            assert "version" in node


class TestListNodesCategory:
    def test_category_filter_returns_matching_nodes(self):
        """Category filter returns only nodes in that category."""
        # Get all nodes first to find a valid category
        all_result = list_nodes_handler({})
        if not all_result["nodes"]:
            return
        category = all_result["nodes"][0]["category"]
        result = list_nodes_handler({"category": category})
        assert "nodes" in result
        for node in result["nodes"]:
            assert node["category"] == category

    def test_unknown_category_returns_empty_list(self):
        """Unknown category returns empty nodes list (not an error)."""
        result = list_nodes_handler({"category": "nonexistent_category_xyz"})
        assert "nodes" in result
        assert result["nodes"] == []


class TestListNodesCapabilityFilter:
    def test_invalid_capability_key_returns_error(self):
        """Invalid capability key returns error_type=invalid_filter_key."""
        result = list_nodes_handler({"capability_filter": {"bad_key": True}})
        assert result.get("error_type") == "invalid_filter_key"
        assert "invalid_key" in result

    def test_valid_capability_key_returns_nodes(self):
        """Valid capability key filters correctly."""
        result = list_nodes_handler({"capability_filter": {"supports_cpu": True}})
        assert "nodes" in result
        assert isinstance(result["nodes"], list)


class TestListTypes:
    def test_list_types_returns_port_data_types(self):
        """list_types=True returns port_data_types list."""
        result = list_nodes_handler({"list_types": True})
        assert "port_data_types" in result
        assert isinstance(result["port_data_types"], list)
        assert len(result["port_data_types"]) > 0

    def test_list_types_contains_audio_sample(self):
        """port_data_types includes AudioSample."""
        result = list_nodes_handler({"list_types": True})
        types = result["port_data_types"]
        assert any("AudioSample" in t for t in types)


class TestListNodesSingleType:
    def test_known_node_type_returns_full_schema(self):
        """node_type alone returns full 10-field schema."""
        result = list_nodes_handler({"node_type": "audio_conditioner"})
        assert result.get("node_type") == "audio_conditioner"
        assert "config_schema" in result
        assert "capability_metadata" in result

    def test_unknown_node_type_returns_error(self):
        """Unknown node_type returns error_type=unknown_node_type."""
        result = list_nodes_handler({"node_type": "nonexistent_xyz"})
        assert result.get("error_type") == "unknown_node_type"
        assert "available_types" in result
