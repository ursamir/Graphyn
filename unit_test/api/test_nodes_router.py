# unit_test/api/test_nodes_router.py
"""Tests for /api/v1/nodes router (Req 11, Req 24)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_meta(node_type: str = "clean"):
    """Return a minimal NodeMetadata-like mock."""
    m = MagicMock()
    m.node_type = node_type
    m.label = "Clean"
    m.description = "Cleans audio"
    m.category = "Preprocessing"
    m.version = "1.0.0"
    m.tags = []
    m.input_ports = {}
    m.output_ports = {}
    m.requires_gpu = False
    m.supports_cpu = True
    m.supports_edge = False
    m.deterministic = True
    m.cacheable = True
    m.streaming_support = False
    m.realtime_support = False
    m.memory_requirements = None
    m.dependency_requirements = []
    m.batch_support = False
    return m


def _make_registry(node_type: str = "clean"):
    """Return a mock registry with one registered node."""
    from app.core.nodes.errors import NodeNotFoundError

    meta = _make_meta(node_type)
    reg = MagicMock()
    reg.list_nodes.return_value = [meta]
    reg.get_metadata.return_value = meta
    reg.get_config_schema.return_value = {"type": "object", "properties": {}}
    reg.get_port_schema.return_value = {"input_ports": {}, "output_ports": {}}

    # Simulate NodeNotFoundError for unknown types
    def _get_meta_side_effect(nt):
        if nt == node_type:
            return meta
        raise NodeNotFoundError(f"Node type '{nt}' not found")

    reg.get_metadata.side_effect = _get_meta_side_effect

    # Config class that accepts empty dict
    config_cls = MagicMock()
    config_cls.model_validate.return_value = MagicMock()

    node_cls = MagicMock()
    node_cls.Config = config_cls

    def _get_class_side_effect(nt):
        if nt == node_type:
            return node_cls
        raise NodeNotFoundError(f"Node type '{nt}' not found")

    reg.get_class.side_effect = _get_class_side_effect
    return reg


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestListNodes:
    def test_returns_200_with_list(self, api_client):
        """GET /api/v1/nodes returns 200 with a list shape."""
        reg = _make_registry()
        with patch("app.api.routers.nodes.get_registry", return_value=reg):
            resp = api_client.get("/api/v1/nodes")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_contains_node_type_field(self, api_client):
        """Each item in the list has a node_type field."""
        reg = _make_registry("clean")
        with patch("app.api.routers.nodes.get_registry", return_value=reg):
            resp = api_client.get("/api/v1/nodes")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 1
        assert "node_type" in items[0]

    def test_category_filter_passed_to_registry(self, api_client):
        """?category= query param is forwarded to registry.list_nodes."""
        reg = _make_registry()
        with patch("app.api.routers.nodes.get_registry", return_value=reg):
            api_client.get("/api/v1/nodes?category=Preprocessing")
        reg.list_nodes.assert_called_once_with(category="Preprocessing")


class TestGetNode:
    def test_known_type_returns_200(self, api_client):
        """GET /api/v1/nodes/{type} returns 200 for a known type."""
        reg = _make_registry("clean")
        with patch("app.api.routers.nodes.get_registry", return_value=reg):
            resp = api_client.get("/api/v1/nodes/clean")
        assert resp.status_code == 200
        assert resp.json()["node_type"] == "clean"

    def test_unknown_type_returns_404(self, api_client):
        """GET /api/v1/nodes/{type} returns 404 for an unknown type."""
        reg = _make_registry("clean")
        with patch("app.api.routers.nodes.get_registry", return_value=reg):
            resp = api_client.get("/api/v1/nodes/nonexistent_node_xyz")
        assert resp.status_code == 404

    def test_response_has_capability_metadata(self, api_client):
        """Node response includes capability_metadata object."""
        reg = _make_registry("clean")
        with patch("app.api.routers.nodes.get_registry", return_value=reg):
            resp = api_client.get("/api/v1/nodes/clean")
        assert resp.status_code == 200
        assert "capability_metadata" in resp.json()


class TestValidateNodeConfig:
    def test_valid_config_returns_200(self, api_client):
        """POST /api/v1/nodes/{type}/validate-config with valid config returns 200."""
        reg = _make_registry("clean")
        with patch("app.api.routers.nodes.get_registry", return_value=reg):
            resp = api_client.post(
                "/api/v1/nodes/clean/validate-config",
                json={"config": {}},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True

    def test_invalid_config_returns_error_response(self, api_client):
        """POST /api/v1/nodes/{type}/validate-config with invalid config returns valid=False."""
        import pydantic

        reg = _make_registry("clean")
        # Get the node_cls that _get_class_side_effect returns for "clean"
        # and set the ValidationError on its Config.model_validate
        node_cls = reg.get_class("clean")
        node_cls.Config.model_validate.side_effect = (
            pydantic.ValidationError.from_exception_data(
                title="Config",
                input_type="python",
                line_errors=[
                    {
                        "type": "missing",
                        "loc": ("required_field",),
                        "msg": "Field required",
                        "input": {},
                        "url": "https://errors.pydantic.dev/2.0/v/missing",
                    }
                ],
            )
        )
        with patch("app.api.routers.nodes.get_registry", return_value=reg):
            resp = api_client.post(
                "/api/v1/nodes/clean/validate-config",
                json={"config": {"bad_field": "x"}},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False

    def test_unknown_node_type_returns_404(self, api_client):
        """POST /api/v1/nodes/{type}/validate-config returns 404 for unknown type."""
        reg = _make_registry("clean")
        with patch("app.api.routers.nodes.get_registry", return_value=reg):
            resp = api_client.post(
                "/api/v1/nodes/nonexistent_xyz/validate-config",
                json={"config": {}},
            )
        assert resp.status_code == 404
