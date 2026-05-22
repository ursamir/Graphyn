# unit_test/core/nodes/test_compat.py
"""Tests for app/core/nodes/compat.py — Req 2 criteria 5–6 + reflexivity PBT."""
from __future__ import annotations

from typing import ClassVar, List

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.nodes.compat import CompatibilityChecker
from app.core.nodes.config import NodeConfig
from app.core.nodes.errors import NodeTypeError
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.core.nodes.base import Node


# ── Minimal nodes for check_connection tests ─────────────────────────────────

class _IntNode(Node):
    node_type: ClassVar[str] = "_compat_int_node"
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=int)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=int)}
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="_compat_int_node",
        label="IntNode",
        description="Int node.",
        category="Test",
    )
    class Config(NodeConfig):
        pass
    def process(self, data):
        return data


class _StrNode(Node):
    node_type: ClassVar[str] = "_compat_str_node"
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=str)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=str)}
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="_compat_str_node",
        label="StrNode",
        description="Str node.",
        category="Test",
    )
    class Config(NodeConfig):
        pass
    def process(self, data):
        return data


class TestAreCompatibleReflexivity:
    """Req 2.5 — are_compatible(T, T) returns True for any type (reflexivity)."""

    def test_reflexive_int(self):
        assert CompatibilityChecker.are_compatible(int, int) is True

    def test_reflexive_str(self):
        assert CompatibilityChecker.are_compatible(str, str) is True

    def test_reflexive_list(self):
        assert CompatibilityChecker.are_compatible(list, list) is True

    def test_reflexive_none_none(self):
        """are_compatible(None, None) returns True."""
        assert CompatibilityChecker.are_compatible(None, None) is True

    def test_incompatible_int_str(self):
        assert CompatibilityChecker.are_compatible(int, str) is False

    def test_one_none_returns_false(self):
        assert CompatibilityChecker.are_compatible(int, None) is False
        assert CompatibilityChecker.are_compatible(None, int) is False


class TestCheckConnectionRaisesOnMismatch:
    """Req 2.6 — check_connection() raises NodeTypeError on type mismatch."""

    def test_check_connection_raises_on_type_mismatch(self):
        """Req 2.6: check_connection() raises NodeTypeError when types are incompatible."""
        int_node = _IntNode(config={}, seed=0)
        str_node = _StrNode(config={}, seed=0)
        with pytest.raises(NodeTypeError):
            CompatibilityChecker.check_connection(int_node, "output", str_node, "input")

    def test_check_connection_succeeds_on_compatible_types(self):
        """check_connection() does not raise when types are compatible."""
        int_node_a = _IntNode(config={}, seed=0)
        int_node_b = _IntNode(config={}, seed=0)
        # Should not raise
        CompatibilityChecker.check_connection(int_node_a, "output", int_node_b, "input")

    def test_check_connection_raises_on_missing_output_port(self):
        int_node = _IntNode(config={}, seed=0)
        str_node = _StrNode(config={}, seed=0)
        with pytest.raises(NodeTypeError):
            CompatibilityChecker.check_connection(int_node, "nonexistent_port", str_node, "input")

    def test_check_connection_raises_on_missing_input_port(self):
        int_node = _IntNode(config={}, seed=0)
        str_node = _StrNode(config={}, seed=0)
        with pytest.raises(NodeTypeError):
            CompatibilityChecker.check_connection(int_node, "output", str_node, "nonexistent_port")


# ── Hypothesis strategies for plain Python types ─────────────────────────────

_PLAIN_TYPES = [int, str, float, bool, bytes, list, dict, tuple]
_plain_type_st = st.sampled_from(_PLAIN_TYPES)


class TestCompatibilityReflexivityProperty:
    """Req 2.5 — property-based reflexivity test.

    **Validates: Requirements 2.5**
    """

    @given(t=_plain_type_st)
    @settings(max_examples=100)
    def test_are_compatible_reflexive(self, t):
        """For any non-None type T, are_compatible(T, T) returns True."""
        assert CompatibilityChecker.are_compatible(t, t) is True
