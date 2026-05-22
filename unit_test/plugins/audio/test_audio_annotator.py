# unit_test/plugins/audio/test_audio_annotator.py
"""Tests for the audio_annotator plugin.

Covers:
  - Registration (Req 7.7)
  - Metadata (Req 7.19)
  - Construction and smoke process
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/audio_annotator/"
NODE_TYPE = "audio_annotator"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("audio_annotator_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.7 — audio_annotator registers in a fresh registry."""
    mgr = PluginManager(registry=fresh_registry)
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


# ── metadata ─────────────────────────────────────────────────────────────────

def test_metadata(installed_cls):
    meta = installed_cls.metadata
    assert meta.label
    assert meta.category
    assert meta.version


# ── construction ─────────────────────────────────────────────────────────────

def test_construct(installed_cls):
    node = installed_cls(config={}, seed=0)
    assert node is not None


# ── smoke process ─────────────────────────────────────────────────────────────

def test_process_smoke(installed_cls, make_audio_sample):
    """AudioAnnotatorNode is SISO — process({"input": [...]}) -> {"output": [...]}."""
    node = installed_cls(config={"annotation_mode": "passthrough"}, seed=0)
    result = node.process({"input": [make_audio_sample()]})
    assert "output" in result
    assert isinstance(result["output"], list)
    assert len(result["output"]) == 1


def test_passthrough_preserves_label(installed_cls, make_audio_sample):
    """Passthrough mode preserves the original label."""
    node = installed_cls(config={"annotation_mode": "passthrough"}, seed=0)
    sample = make_audio_sample(label="speech")
    result = node.process({"input": [sample]})
    assert result["output"][0].label == "speech"
