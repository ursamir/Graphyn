# unit_test/core/nodes/test_metadata.py
"""Tests for app/core/nodes/metadata.py — Req 18 (metadata validation)."""
from __future__ import annotations

import pytest
import pydantic

from app.core.nodes.metadata import NodeMetadata


VALID_KWARGS = dict(
    node_type="my_node",
    label="My Node",
    description="Does something useful.",
    category="Audio",
)


class TestNodeMetadataValidation:
    """Empty required string fields must raise pydantic.ValidationError."""

    def test_empty_node_type_raises(self):
        with pytest.raises(pydantic.ValidationError):
            NodeMetadata(**{**VALID_KWARGS, "node_type": ""})

    def test_whitespace_node_type_raises(self):
        with pytest.raises(pydantic.ValidationError):
            NodeMetadata(**{**VALID_KWARGS, "node_type": "   "})

    def test_empty_label_raises(self):
        with pytest.raises(pydantic.ValidationError):
            NodeMetadata(**{**VALID_KWARGS, "label": ""})

    def test_whitespace_label_raises(self):
        with pytest.raises(pydantic.ValidationError):
            NodeMetadata(**{**VALID_KWARGS, "label": "   "})

    def test_empty_description_raises(self):
        with pytest.raises(pydantic.ValidationError):
            NodeMetadata(**{**VALID_KWARGS, "description": ""})

    def test_whitespace_description_raises(self):
        with pytest.raises(pydantic.ValidationError):
            NodeMetadata(**{**VALID_KWARGS, "description": "   "})

    def test_empty_category_raises(self):
        with pytest.raises(pydantic.ValidationError):
            NodeMetadata(**{**VALID_KWARGS, "category": ""})

    def test_whitespace_category_raises(self):
        with pytest.raises(pydantic.ValidationError):
            NodeMetadata(**{**VALID_KWARGS, "category": "   "})


class TestNodeMetadataConstruction:
    """Valid NodeMetadata constructs and round-trips correctly."""

    def test_valid_construction(self):
        meta = NodeMetadata(**VALID_KWARGS)
        assert meta.node_type == "my_node"
        assert meta.label == "My Node"
        assert meta.description == "Does something useful."
        assert meta.category == "Audio"

    def test_defaults_applied(self):
        meta = NodeMetadata(**VALID_KWARGS)
        assert meta.version == "1.0.0"
        assert meta.tags == []
        assert meta.input_ports == {}
        assert meta.output_ports == {}
        assert meta.requires_gpu is False
        assert meta.supports_cpu is True
        assert meta.cacheable is True

    def test_model_dump_round_trip(self):
        meta = NodeMetadata(**VALID_KWARGS)
        data = meta.model_dump()
        restored = NodeMetadata.model_validate(data)
        assert restored.node_type == meta.node_type
        assert restored.label == meta.label
        assert restored.description == meta.description
        assert restored.category == meta.category
        assert restored.version == meta.version

    def test_model_dump_contains_required_keys(self):
        meta = NodeMetadata(**VALID_KWARGS)
        data = meta.model_dump()
        for key in ("node_type", "label", "description", "category", "version"):
            assert key in data

    def test_optional_fields_can_be_set(self):
        meta = NodeMetadata(
            **VALID_KWARGS,
            requires_gpu=True,
            supports_edge=True,
            tags=["speech", "classification"],
            version="2.0.0",
        )
        assert meta.requires_gpu is True
        assert meta.supports_edge is True
        assert meta.tags == ["speech", "classification"]
        assert meta.version == "2.0.0"
