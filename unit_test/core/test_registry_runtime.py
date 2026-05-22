"""Unit tests for app/core/registry_runtime.py — Req 14 criterion 5."""
from __future__ import annotations

import pytest

from app.core.registry_runtime import get_registry


# ── get_registry ──────────────────────────────────────────────────────────────

def test_get_registry_returns_node_registry():
    """Req 14.5 — get_registry() returns a NodeRegistry instance."""
    from app.core.nodes.registry import NodeRegistry
    reg = get_registry()
    assert isinstance(reg, NodeRegistry)


def test_get_registry_is_populated():
    """get_registry() returns a registry with at least one node type registered."""
    reg = get_registry()
    nodes = reg.list_nodes()
    assert len(nodes) > 0


def test_get_registry_contains_audio_conditioner():
    """get_registry() contains the 'audio_conditioner' plugin node."""
    reg = get_registry()
    assert "audio_conditioner" in reg


def test_get_registry_contains_segmenter():
    """get_registry() contains the 'segmenter' plugin node."""
    reg = get_registry()
    assert "segmenter" in reg


def test_get_registry_contains_feature_frontend():
    """get_registry() contains the 'feature_frontend' plugin node."""
    reg = get_registry()
    assert "feature_frontend" in reg


def test_get_registry_contains_dataset_builder():
    """get_registry() contains the 'dataset_builder' plugin node."""
    reg = get_registry()
    assert "dataset_builder" in reg


def test_get_registry_contains_augmentation_pipeline():
    """get_registry() contains the 'augmentation_pipeline' plugin node."""
    reg = get_registry()
    assert "augmentation_pipeline" in reg


def test_get_registry_contains_audio_quality_gate():
    """get_registry() contains the 'audio_quality_gate' plugin node."""
    reg = get_registry()
    assert "audio_quality_gate" in reg


def test_get_registry_node_metadata_has_required_fields():
    """Each registered node has NodeMetadata with node_type, label, category."""
    reg = get_registry()
    for meta in reg.list_nodes():
        assert meta.node_type, f"node_type is empty for {meta}"
        assert meta.label, f"label is empty for {meta.node_type}"
        assert meta.category, f"category is empty for {meta.node_type}"


def test_get_registry_get_class_returns_node_subclass():
    """get_class() returns a Node subclass for a registered node type."""
    from app.core.nodes.base import Node
    reg = get_registry()
    cls = reg.get_class("audio_conditioner")
    assert issubclass(cls, Node)


def test_get_registry_returns_same_singleton():
    """get_registry() returns the same object on repeated calls."""
    reg1 = get_registry()
    reg2 = get_registry()
    assert reg1 is reg2


def test_get_registry_contains_at_least_18_audio_plugin_nodes():
    """Req 7.19 — registry contains at least 18 Audio plugin node types."""
    reg = get_registry()
    audio_plugin_types = {
        "audio_conditioner", "feature_frontend", "dataset_ingest", "stream_ingest",
        "audio_quality_gate", "segmenter", "audio_annotator", "alignment_node",
        "speech_enhancer", "speaker_separator", "environment_simulator",
        "augmentation_pipeline", "audio_event_detector", "audio_classifier",
        "speech_synthesizer", "voice_converter", "audio_generator", "stream_processor",
    }
    registered = {m.node_type for m in reg.list_nodes()}
    missing = audio_plugin_types - registered
    assert not missing, f"Missing audio plugin node types: {missing}"


def test_get_registry_contains_common_plugin_nodes():
    """Registry contains the expected Common plugin node types."""
    reg = get_registry()
    common_plugin_types = {
        "dataset_builder", "trainer", "evaluator", "edge_optimizer",
        "realtime_inference", "dataset_balancer", "dataset_versioner",
        "experiment_tracker", "deployment_packager", "embedding_generator",
        "multimodal_fusion",
    }
    registered = {m.node_type for m in reg.list_nodes()}
    missing = common_plugin_types - registered
    assert not missing, f"Missing common plugin node types: {missing}"
