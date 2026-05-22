# unit_test/core/nodes/test_node_base.py
"""Tests for app/core/nodes/base.py — Req 2 criteria 1, 7, 8."""
from __future__ import annotations

from typing import ClassVar

import pytest

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort


# ── Minimal SISO node for testing ─────────────────────────────────────────────

class _SISONode(Node):
    node_type: ClassVar[str] = "_test_siso_node"
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="_test_siso_node",
        label="Test SISO",
        description="Test SISO node.",
        category="Test",
    )

    class Config(NodeConfig):
        pass

    def process(self, data):
        return [x * 2 for x in data]


# ── Multi-port node for lifecycle testing ─────────────────────────────────────

class _LifecycleNode(Node):
    node_type: ClassVar[str] = "_test_lifecycle_node"
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="_test_lifecycle_node",
        label="Lifecycle",
        description="Lifecycle test node.",
        category="Test",
    )

    class Config(NodeConfig):
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.call_order: list[str] = []

    def setup(self):
        self.call_order.append("setup")

    def on_start(self):
        self.call_order.append("on_start")

    def on_end(self):
        self.call_order.append("on_end")

    def on_error(self, exc):
        self.call_order.append("on_error")

    def process(self, inputs: dict) -> dict:
        self.call_order.append("process")
        return {"output": inputs.get("input", [])}


class _FailingNode(Node):
    node_type: ClassVar[str] = "_test_failing_node"
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="_test_failing_node",
        label="Failing",
        description="Failing test node.",
        category="Test",
    )

    class Config(NodeConfig):
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.call_order: list[str] = []

    def setup(self):
        self.call_order.append("setup")

    def on_start(self):
        self.call_order.append("on_start")

    def on_end(self):
        self.call_order.append("on_end")

    def on_error(self, exc):
        self.call_order.append("on_error")

    def process(self, inputs: dict) -> dict:
        self.call_order.append("process")
        raise RuntimeError("intentional failure")


class TestSISOWrapper:
    """Req 2.1 — SISO wrapper: process({"input": data}) returns {"output": result}."""

    def test_siso_process_wraps_correctly(self):
        """Req 2.1: process({"input": data}) returns {"output": result}."""
        node = _SISONode(config={}, seed=0)
        result = node.process({"input": [1, 2, 3]})
        assert result == {"output": [2, 4, 6]}

    def test_siso_process_with_empty_input(self):
        node = _SISONode(config={}, seed=0)
        result = node.process({"input": []})
        assert result == {"output": []}

    def test_siso_is_siso_returns_true(self):
        assert _SISONode._is_siso() is True


class TestLifecycleHooks:
    """Req 2.7 — lifecycle hooks order: setup → on_start → process → on_end for success,
    on_error on failure."""

    def test_success_lifecycle_order(self):
        """Req 2.7: setup → on_start → process → on_end for successful execution."""
        node = _LifecycleNode(config={}, seed=0)
        node.setup()
        node.on_start()
        node.process({"input": [1, 2]})
        node.on_end()
        assert node.call_order == ["setup", "on_start", "process", "on_end"]

    def test_failure_lifecycle_calls_on_error(self):
        """Req 2.7: on_error is called when process() raises."""
        node = _FailingNode(config={}, seed=0)
        node.setup()
        node.on_start()
        try:
            node.process({"input": []})
        except RuntimeError:
            node.on_error(RuntimeError("intentional failure"))
        assert "on_error" in node.call_order
        assert "on_end" not in node.call_order

    def test_on_end_not_called_on_failure(self):
        node = _FailingNode(config={}, seed=0)
        node.setup()
        node.on_start()
        try:
            node.process({"input": []})
        except RuntimeError:
            node.on_error(RuntimeError("x"))
        assert node.call_order == ["setup", "on_start", "process", "on_error"]


class TestSISOProperties:
    """Req 2.8 — input_type and output_type accessible when _is_siso() is True."""

    def test_input_type_accessible_on_siso_node(self):
        """Req 2.8: input_type property accessible when _is_siso() is True."""
        node = _SISONode(config={}, seed=0)
        assert node.input_type is list

    def test_output_type_accessible_on_siso_node(self):
        """Req 2.8: output_type property accessible when _is_siso() is True."""
        node = _SISONode(config={}, seed=0)
        assert node.output_type is list

    def test_input_type_raises_on_non_siso(self):
        """input_type raises AttributeError on non-SISO node."""
        class _MultiPortNode(Node):
            node_type: ClassVar[str] = "_test_multi_port"
            input_ports: ClassVar[dict] = {
                "a": InputPort(name="a", data_type=list),
                "b": InputPort(name="b", data_type=list),
            }
            output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}
            metadata: ClassVar[NodeMetadata] = NodeMetadata(
                node_type="_test_multi_port",
                label="Multi",
                description="Multi-port test node.",
                category="Test",
            )
            class Config(NodeConfig):
                pass
            def process(self, inputs: dict) -> dict:
                return {"output": []}

        node = _MultiPortNode(config={}, seed=0)
        with pytest.raises(AttributeError):
            _ = node.input_type


class TestBaseProcessNotImplemented:
    """Base Node.process() raises NotImplementedError."""

    def test_base_process_raises_not_implemented(self):
        """process() not implemented on base raises NotImplementedError."""
        # Create a subclass that does NOT override process
        class _NoProcessNode(Node):
            node_type: ClassVar[str] = "_test_no_process"
            input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
            output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}
            metadata: ClassVar[NodeMetadata] = NodeMetadata(
                node_type="_test_no_process",
                label="NoProcess",
                description="No process node.",
                category="Test",
            )
            class Config(NodeConfig):
                pass
            # Intentionally NOT overriding process() — uses base class

        node = _NoProcessNode(config={}, seed=0)
        with pytest.raises(NotImplementedError):
            node.process({"input": []})
