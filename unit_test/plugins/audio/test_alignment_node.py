# unit_test/plugins/audio/test_alignment_node.py
"""Tests for the alignment_node plugin.

Covers:
  - Registration (Req 7.8)
  - Metadata (Req 7.19)
  - Construction and smoke process

Note: alignment_node uses multi-port process(inputs: dict) -> dict.
Input ports: audio (list[AudioSample]), transcripts (list[dict]).
When no transcript is provided, the node passes through with empty alignment.
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/alignment_node/"
NODE_TYPE = "alignment_node"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("alignment_node_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.8 — alignment_node registers in a fresh registry."""
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

def test_process_smoke_no_transcript(installed_cls, make_audio_sample):
    """AlignmentNode passes through samples with empty alignment when no transcript given."""
    node = installed_cls(config={"backend": "ctc"}, seed=0)
    sample = make_audio_sample()
    # No transcripts provided — node should pass through with empty alignment metadata
    result = node.process({"audio": [sample], "transcripts": []})
    assert "output" in result
    assert isinstance(result["output"], list)
    assert len(result["output"]) == 1
    # Should have alignment metadata even without a transcript
    assert "alignment" in result["output"][0].metadata
