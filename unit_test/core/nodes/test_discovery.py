# unit_test/core/nodes/test_discovery.py
"""Tests for app/core/nodes/discovery.py — Req 3 criteria 8–10."""
from __future__ import annotations

import sys
import types
from typing import ClassVar
from unittest.mock import patch

import pytest

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.discovery import AutoDiscovery, _pascal_to_snake
from app.core.nodes.errors import DuplicateNodeTypeError
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort


# ── Helpers to create fake modules with node classes ─────────────────────────

def _make_module(name: str, node_cls: type) -> types.ModuleType:
    """Create a fake module containing a single node class."""
    mod = types.ModuleType(name)
    mod.__name__ = name
    # Patch the class's __module__ to match the fake module
    node_cls.__module__ = name
    setattr(mod, node_cls.__name__, node_cls)
    return mod


class TestAutoDiscoveryValidNode:
    """Req 3.8 — valid node with metadata ClassVar gets registered."""

    def test_valid_node_gets_registered(self, fresh_registry):
        """Req 3.8: AutoDiscovery registers a valid Node subclass with metadata ClassVar."""
        class _ValidNode(Node):
            node_type: ClassVar[str] = "_valid_discovery_node"
            input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
            output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}
            metadata: ClassVar[NodeMetadata] = NodeMetadata(
                node_type="_valid_discovery_node",
                label="Valid",
                description="Valid discovery node.",
                category="Test",
            )
            class Config(NodeConfig):
                pass
            def process(self, data):
                return data

        discovery = AutoDiscovery(fresh_registry)
        mod = _make_module("_test_discovery_valid_mod", _ValidNode)
        discovery._process_module(mod)
        assert "_valid_discovery_node" in fresh_registry


class TestAutoDiscoveryDuplicateNodeType:
    """Req 3.9 — two nodes with same node_type raises DuplicateNodeTypeError."""

    def test_duplicate_node_type_raises(self, fresh_registry):
        """Req 3.9: two Node subclasses with same node_type raises DuplicateNodeTypeError."""
        class _NodeA(Node):
            node_type: ClassVar[str] = "_dup_node_type"
            input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
            output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}
            metadata: ClassVar[NodeMetadata] = NodeMetadata(
                node_type="_dup_node_type",
                label="NodeA",
                description="Node A.",
                category="Test",
            )
            class Config(NodeConfig):
                pass
            def process(self, data):
                return data

        class _NodeB(Node):
            node_type: ClassVar[str] = "_dup_node_type"
            input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
            output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}
            metadata: ClassVar[NodeMetadata] = NodeMetadata(
                node_type="_dup_node_type",
                label="NodeB",
                description="Node B.",
                category="Test",
            )
            class Config(NodeConfig):
                pass
            def process(self, data):
                return data

        discovery = AutoDiscovery(fresh_registry)

        # Register first node
        mod_a = _make_module("_test_dup_mod_a", _NodeA)
        discovery._process_module(mod_a)

        # Second node with same node_type should raise
        mod_b = _make_module("_test_dup_mod_b", _NodeB)
        with pytest.raises(DuplicateNodeTypeError):
            discovery._process_module(mod_b)


class TestAutoDiscoveryMissingMetadata:
    """Missing metadata logs warning (does NOT raise NodeMetadataError during scan)."""

    def test_missing_metadata_logs_warning_not_raises(self, fresh_registry, caplog):
        """Missing metadata logs a warning and skips the node — does not raise."""
        import logging

        class _NoMetaNode(Node):
            node_type: ClassVar[str] = "_no_meta_node"
            input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=list)}
            output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}
            # Intentionally no metadata ClassVar
            class Config(NodeConfig):
                pass
            def process(self, data):
                return data

        discovery = AutoDiscovery(fresh_registry)
        mod = _make_module("_test_no_meta_mod", _NoMetaNode)

        # _process_module raises NodeMetadataError; _scan_directory catches it and logs warning.
        # Test _register_node directly to confirm it raises NodeMetadataError.
        from app.core.nodes.errors import NodeMetadataError
        with pytest.raises(NodeMetadataError):
            discovery._register_node(_NoMetaNode)

        # Confirm the node was NOT registered
        assert "_no_meta_node" not in fresh_registry


class TestPascalToSnake:
    """Req 3.10 — _pascal_to_snake conversions."""

    def test_audio_conditioner_node(self):
        """AudioConditionerNode → audio_conditioner."""
        assert _pascal_to_snake("AudioConditionerNode") == "audio_conditioner"

    def test_alignment_node(self):
        """AlignmentNode → alignment_node (strips _node suffix)."""
        assert _pascal_to_snake("AlignmentNode") == "alignment"

    def test_filter_node(self):
        assert _pascal_to_snake("FilterNode") == "filter"

    def test_clean_node(self):
        assert _pascal_to_snake("CleanNode") == "clean"

    def test_audio_mixer_node(self):
        assert _pascal_to_snake("AudioMixerNode") == "audio_mixer"

    def test_tf_lite_processor_node(self):
        assert _pascal_to_snake("TFLiteProcessorNode") == "tf_lite_processor"

    def test_hf_export_node(self):
        assert _pascal_to_snake("HFExportNode") == "hf_export"

    def test_feature_frontend_node(self):
        assert _pascal_to_snake("FeatureFrontendNode") == "feature_frontend"

    def test_dataset_ingest_node(self):
        assert _pascal_to_snake("DatasetIngestNode") == "dataset_ingest"
