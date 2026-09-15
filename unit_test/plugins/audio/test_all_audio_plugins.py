# unit_test/plugins/audio/test_all_audio_plugins.py
"""Aggregate test: all 19 Audio plugins register and have valid metadata.

Installs all 19 Audio plugins into a single module-scoped tmp directory
and asserts that every node_type is present with non-empty label, category,
and version fields.

Requirements: Req 7.19
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager
from app.core.nodes.registry import NodeRegistry

ALL_AUDIO_PLUGINS = [
    ("PluginPackage/Audio/audio_conditioner/", "audio_conditioner"),
    ("PluginPackage/Audio/feature_frontend/", "feature_frontend"),
    ("PluginPackage/Audio/dataset_ingest/", "dataset_ingest"),
    ("PluginPackage/Audio/stream_ingest/", "stream_ingest"),
    ("PluginPackage/Audio/audio_quality_gate/", "audio_quality_gate"),
    ("PluginPackage/Audio/segmenter/", "segmenter"),
    ("PluginPackage/Audio/audio_annotator/", "audio_annotator"),
    ("PluginPackage/Audio/alignment_node/", "alignment_node"),
    ("PluginPackage/Audio/speech_enhancer/", "speech_enhancer"),
    ("PluginPackage/Audio/speaker_separator/", "speaker_separator"),
    ("PluginPackage/Audio/environment_simulator/", "environment_simulator"),
    ("PluginPackage/Audio/augmentation_pipeline/", "augmentation_pipeline"),
    ("PluginPackage/Audio/audio_event_detector/", "audio_event_detector"),
    ("PluginPackage/Audio/audio_classifier/", "audio_classifier"),
    ("PluginPackage/Audio/speech_synthesizer/", "speech_synthesizer"),
    ("PluginPackage/Audio/voice_converter/", "voice_converter"),
    ("PluginPackage/Audio/audio_generator/", "audio_generator"),
    ("PluginPackage/Audio/stream_processor/", "stream_processor"),
    ("PluginPackage/Audio/audio_exporter/", "audio_exporter"),
]


@pytest.fixture(scope="module")
def all_audio_registry(tmp_path_factory):
    """Install all 19 Audio plugins into a single shared tmp directory."""
    import os

    # Allow pip-install of declared plugin deps (e.g. noisereduce) during registry smoke.
    prev = os.environ.get("GRAPHYN_PLUGIN_AUTO_INSTALL")
    os.environ["GRAPHYN_PLUGIN_AUTO_INSTALL"] = "1"
    try:
        tmp_dir = tmp_path_factory.mktemp("all_audio_plugins")
        reg = NodeRegistry()
        mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
        mgr._plugins_dir = str(tmp_dir)
        for source, _ in ALL_AUDIO_PLUGINS:
            mgr.install(source)
        return reg
    finally:
        if prev is None:
            os.environ.pop("GRAPHYN_PLUGIN_AUTO_INSTALL", None)
        else:
            os.environ["GRAPHYN_PLUGIN_AUTO_INSTALL"] = prev


def test_all_19_node_types_registered(all_audio_registry):
    """Req 7.19 — all 19 Audio node types are present in the registry."""
    for _, node_type in ALL_AUDIO_PLUGINS:
        assert node_type in all_audio_registry, f"{node_type} not registered"


def test_all_19_have_valid_metadata(all_audio_registry):
    """Req 7.19 — all 19 Audio node types have non-empty label, category, version."""
    for _, node_type in ALL_AUDIO_PLUGINS:
        meta = all_audio_registry.get_metadata(node_type)
        assert meta.label, f"{node_type} has empty label"
        assert meta.category, f"{node_type} has empty category"
        assert meta.version, f"{node_type} has empty version"


def test_registry_contains_at_least_19_audio_plugins(all_audio_registry):
    """Registry has at least 19 entries after installing all Audio plugins."""
    registered_types = [node_type for _, node_type in ALL_AUDIO_PLUGINS
                        if node_type in all_audio_registry]
    assert len(registered_types) >= 19, (
        f"Expected at least 19 Audio plugins, found {len(registered_types)}: "
        f"{registered_types}"
    )
