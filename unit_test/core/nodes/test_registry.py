# unit_test/core/nodes/test_registry.py
"""Tests for app/core/nodes/registry.py — Req 3 criteria 1–5."""
from __future__ import annotations

import pytest

from app.core.nodes.errors import NodeNotFoundError
from app.core.nodes.registry import NodeRegistry


class TestRegistryRegisterAndLookup:
    """Req 3.1 — register/get/contains."""

    def test_register_makes_node_type_in_registry(self, fresh_registry, minimal_node_cls, minimal_meta):
        """Req 3.1: after register(), node_type in registry returns True."""
        fresh_registry.register("_minimal_test_node", minimal_node_cls, minimal_meta)
        assert "_minimal_test_node" in fresh_registry

    def test_get_class_returns_registered_class(self, fresh_registry, minimal_node_cls, minimal_meta):
        """Req 3.1: get_class() returns the registered class."""
        fresh_registry.register("_minimal_test_node", minimal_node_cls, minimal_meta)
        assert fresh_registry.get_class("_minimal_test_node") is minimal_node_cls

    def test_get_metadata_returns_registered_metadata(self, fresh_registry, minimal_node_cls, minimal_meta):
        fresh_registry.register("_minimal_test_node", minimal_node_cls, minimal_meta)
        meta = fresh_registry.get_metadata("_minimal_test_node")
        assert meta.node_type == "_minimal_test_node"
        assert meta.label == "Minimal"

    def test_len_increases_after_register(self, fresh_registry, minimal_node_cls, minimal_meta):
        assert len(fresh_registry) == 0
        fresh_registry.register("_minimal_test_node", minimal_node_cls, minimal_meta)
        assert len(fresh_registry) == 1


class TestRegistryUnregister:
    """Req 3.2 — unregister removes node type."""

    def test_unregister_makes_node_type_not_in_registry(self, fresh_registry, minimal_node_cls, minimal_meta):
        """Req 3.2: after unregister(), node_type in registry returns False."""
        fresh_registry.register("_minimal_test_node", minimal_node_cls, minimal_meta)
        fresh_registry.unregister("_minimal_test_node")
        assert "_minimal_test_node" not in fresh_registry

    def test_unregister_reduces_len(self, fresh_registry, minimal_node_cls, minimal_meta):
        fresh_registry.register("_minimal_test_node", minimal_node_cls, minimal_meta)
        fresh_registry.unregister("_minimal_test_node")
        assert len(fresh_registry) == 0


class TestRegistryUnregisterNoop:
    """Req 3.3 — unregister of nonexistent is no-op."""

    def test_unregister_nonexistent_does_not_raise(self, fresh_registry):
        """Req 3.3: unregister() for unregistered node_type is a no-op."""
        fresh_registry.unregister("nonexistent_node_type")  # must not raise

    def test_unregister_twice_does_not_raise(self, fresh_registry, minimal_node_cls, minimal_meta):
        fresh_registry.register("_minimal_test_node", minimal_node_cls, minimal_meta)
        fresh_registry.unregister("_minimal_test_node")
        fresh_registry.unregister("_minimal_test_node")  # second call must not raise


class TestRegistryGetUnregisteredRaises:
    """Req 3.4 — get_class() raises NodeNotFoundError for unregistered type."""

    def test_get_class_unregistered_raises_node_not_found(self, fresh_registry):
        """Req 3.4: get_class() raises NodeNotFoundError for unregistered node_type."""
        with pytest.raises(NodeNotFoundError):
            fresh_registry.get_class("nonexistent_node_type")

    def test_get_metadata_unregistered_raises_node_not_found(self, fresh_registry):
        with pytest.raises(NodeNotFoundError):
            fresh_registry.get_metadata("nonexistent_node_type")


class TestRegistryJsonRoundTrip:
    """Req 3.5 — to_json()/from_json() round-trip."""

    def test_to_json_from_json_round_trip(self, fresh_registry, minimal_node_cls, minimal_meta):
        """Req 3.5: to_json() output round-trips through from_json() producing equivalent metadata."""
        fresh_registry.register("_minimal_test_node", minimal_node_cls, minimal_meta)
        json_str = fresh_registry.to_json()
        restored = NodeRegistry.from_json(json_str)
        assert len(restored) == 1
        assert restored[0].node_type == "_minimal_test_node"
        assert restored[0].label == "Minimal"

    def test_to_json_empty_registry(self, fresh_registry):
        json_str = fresh_registry.to_json()
        restored = NodeRegistry.from_json(json_str)
        assert restored == []

    def test_from_json_invalid_raises_value_error(self):
        with pytest.raises(ValueError):
            NodeRegistry.from_json("not valid json {{{")


class TestRegistryFillsEmptyMetadataPorts:
    """register() copies class ports onto bare NodeMetadata (isolated stubs)."""

    def test_empty_meta_ports_filled_from_class(self, fresh_registry, minimal_node_cls, minimal_meta):
        assert minimal_meta.input_ports == {}
        assert minimal_meta.output_ports == {}
        fresh_registry.register("_minimal_test_node", minimal_node_cls, minimal_meta)
        meta = fresh_registry.get_metadata("_minimal_test_node")
        assert "input" in meta.input_ports
        assert "output" in meta.output_ports

    def test_multi_port_class_fills_named_ports(self, fresh_registry):
        from typing import ClassVar

        from app.core.nodes.base import Node
        from app.core.nodes.config import NodeConfig
        from app.core.nodes.metadata import NodeMetadata
        from app.core.nodes.ports import InputPort, OutputPort

        class _MultiPort(Node):
            node_type: ClassVar[str] = "_multi_port_test"
            input_ports: ClassVar[dict] = {
                "model": InputPort(name="model", data_type=object),
                "dataset": InputPort(name="dataset", data_type=object),
            }
            output_ports: ClassVar[dict] = {
                "output": OutputPort(name="output", data_type=object),
            }
            metadata: ClassVar[NodeMetadata] = NodeMetadata(
                node_type="_multi_port_test",
                label="Multi",
                description="Multi-port test node.",
                category="Test",
            )

            class Config(NodeConfig):
                pass

            def process(self, inputs):  # noqa: ARG002
                return {}

        bare = NodeMetadata(
            node_type="_multi_port_test",
            label="Multi",
            description="Multi-port test node.",
            category="Test",
        )
        fresh_registry.register("_multi_port_test", _MultiPort, bare)
        meta = fresh_registry.get_metadata("_multi_port_test")
        assert set(meta.input_ports) == {"model", "dataset"}
        assert set(meta.output_ports) == {"output"}
