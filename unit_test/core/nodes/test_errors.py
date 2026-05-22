# unit_test/core/nodes/test_errors.py
"""Tests for app/core/nodes/errors.py — Req 18 criteria 1–3."""
from __future__ import annotations

import pytest

from app.core.nodes.errors import (
    DuplicateNodeTypeError,
    DuplicatePortTypeError,
    NodeMetadataError,
    NodeNotFoundError,
    NodeSystemError,
    NodeTypeError,
    PipelineGraphError,
    PortTypeNotFoundError,
)

# All 8 error classes to test
ALL_ERROR_CLASSES = [
    NodeSystemError,
    NodeNotFoundError,
    DuplicateNodeTypeError,
    NodeMetadataError,
    NodeTypeError,
    PortTypeNotFoundError,
    DuplicatePortTypeError,
    PipelineGraphError,
]


class TestErrorImportability:
    """Req 18.1 — all 8 error classes are importable and subclass Exception."""

    @pytest.mark.parametrize("error_cls", ALL_ERROR_CLASSES)
    def test_is_importable(self, error_cls):
        """Each error class can be imported and is a type."""
        assert isinstance(error_cls, type)

    @pytest.mark.parametrize("error_cls", ALL_ERROR_CLASSES)
    def test_is_subclass_of_exception(self, error_cls):
        """Each error class is a subclass of Exception."""
        assert issubclass(error_cls, Exception)

    @pytest.mark.parametrize("error_cls", ALL_ERROR_CLASSES)
    def test_can_be_raised_and_caught(self, error_cls):
        """Each error class can be raised and caught as Exception."""
        with pytest.raises(Exception):
            raise error_cls("test message")


class TestInheritanceChain:
    """Req 18.2–3 — inheritance chain is correct."""

    def test_node_not_found_error_is_subclass_of_node_system_error(self):
        """Req 18.2: NodeNotFoundError is a subclass of NodeSystemError."""
        assert issubclass(NodeNotFoundError, NodeSystemError)

    def test_pipeline_graph_error_is_subclass_of_node_system_error(self):
        """Req 18.3: PipelineGraphError is a subclass of NodeSystemError."""
        assert issubclass(PipelineGraphError, NodeSystemError)

    def test_duplicate_node_type_error_is_subclass_of_node_system_error(self):
        """DuplicateNodeTypeError is a subclass of NodeSystemError."""
        assert issubclass(DuplicateNodeTypeError, NodeSystemError)

    def test_node_metadata_error_is_subclass_of_node_system_error(self):
        """NodeMetadataError is a subclass of NodeSystemError."""
        assert issubclass(NodeMetadataError, NodeSystemError)

    def test_node_type_error_is_subclass_of_node_system_error(self):
        """NodeTypeError is a subclass of NodeSystemError."""
        assert issubclass(NodeTypeError, NodeSystemError)

    def test_port_type_not_found_error_is_subclass_of_node_system_error(self):
        """PortTypeNotFoundError is a subclass of NodeSystemError."""
        assert issubclass(PortTypeNotFoundError, NodeSystemError)

    def test_duplicate_port_type_error_is_subclass_of_node_system_error(self):
        """DuplicatePortTypeError is a subclass of NodeSystemError."""
        assert issubclass(DuplicatePortTypeError, NodeSystemError)

    def test_node_not_found_error_caught_as_node_system_error(self):
        """NodeNotFoundError can be caught as NodeSystemError."""
        with pytest.raises(NodeSystemError):
            raise NodeNotFoundError("not found")

    def test_pipeline_graph_error_caught_as_node_system_error(self):
        """PipelineGraphError can be caught as NodeSystemError."""
        with pytest.raises(NodeSystemError):
            raise PipelineGraphError("cycle detected")
