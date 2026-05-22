# unit_test/plugins/audio/test_voice_converter.py
"""Tests for the voice_converter plugin.

Covers:
  - Registration (Req 7.16)
  - Metadata (Req 7.19)
  - Construction and smoke process
  - voice_converter is SISO: process(list[AudioSample]) -> list[AudioSample]
    Falls back to pitch-shift-only when no backend (speechbrain/knnvc) is installed.
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/voice_converter/"
NODE_TYPE = "voice_converter"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("voice_converter_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.16 — voice_converter registers in a fresh registry."""
    mgr = PluginManager(registry=fresh_registry)
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


# ── metadata ─────────────────────────────────────────────────────────────────

def test_metadata(installed_cls):
    """Req 7.19 — metadata fields are non-empty."""
    meta = installed_cls.metadata
    assert meta.label
    assert meta.category
    assert meta.version


# ── construction ─────────────────────────────────────────────────────────────

def test_construct(installed_cls):
    node = installed_cls(config={}, seed=0)
    assert node is not None


# ── smoke process ─────────────────────────────────────────────────────────────
# voice_converter falls back to pitch_only when no backend is available.
# pitch_only with pitch_shift_semitones=0.0 is a no-op (returns sample unchanged).

def test_process_smoke(installed_cls, make_audio_sample):
    """Smoke test: SISO process returns output AudioSamples."""
    node = installed_cls(config={}, seed=0)
    result = node.process({"input": [make_audio_sample()]})
    assert "output" in result
    assert isinstance(result["output"], list)
    assert len(result["output"]) == 1


def test_process_empty_input(installed_cls):
    """Empty input list produces empty output."""
    node = installed_cls(config={}, seed=0)
    result = node.process({"input": []})
    assert result["output"] == []


def test_process_output_is_audio_sample(installed_cls, make_audio_sample):
    """Output items are AudioSample objects."""
    from app.models.audio_sample import AudioSample
    node = installed_cls(config={}, seed=0)
    result = node.process({"input": [make_audio_sample()]})
    for sample in result["output"]:
        assert isinstance(sample, AudioSample)


def test_process_metadata_propagation(installed_cls, make_audio_sample):
    """Output samples have voice_converter metadata key."""
    node = installed_cls(config={}, seed=0)
    result = node.process({"input": [make_audio_sample()]})
    for sample in result["output"]:
        assert "voice_converter" in sample.metadata
        assert "conversion_type" in sample.metadata["voice_converter"]


def test_process_output_count_matches_input(installed_cls, make_audio_sample):
    """Output count equals input count."""
    node = installed_cls(config={}, seed=0)
    samples = [make_audio_sample() for _ in range(3)]
    result = node.process({"input": samples})
    assert len(result["output"]) == 3
