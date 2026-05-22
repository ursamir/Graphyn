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
