# unit_test/plugins/audio/test_speech_synthesizer.py
"""Tests for the speech_synthesizer plugin.

Covers:
  - Registration (Req 7.15)
  - Metadata (Req 7.19)
  - Construction and smoke process
  - speech_synthesizer is SISO: process(list[str]) -> list[AudioSample]
    Input is a list of text strings, NOT AudioSample objects.
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/speech_synthesizer/"
NODE_TYPE = "speech_synthesizer"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("speech_synthesizer_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.15 — speech_synthesizer registers in a fresh registry."""
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
# speech_synthesizer input is list[str] (text to synthesize), not AudioSample.
# With backend="auto" it tries Coqui TTS first, then falls back to espeak-ng.
# If neither is installed, it raises ImportError — we skip gracefully.

def test_process_smoke(installed_cls):
    """Smoke test: SISO process with espeak backend returns output AudioSamples."""
    node = installed_cls(config={"backend": "espeak"}, seed=0)
    try:
        result = node.process({"input": ["Hello world"]})
    except ImportError:
        pytest.skip("espeak-ng not installed — speech_synthesizer backend unavailable")
    assert "output" in result
    assert isinstance(result["output"], list)
    assert len(result["output"]) == 1


def test_process_empty_input(installed_cls):
    """Empty text list produces empty output."""
    node = installed_cls(config={"backend": "espeak"}, seed=0)
    try:
        result = node.process({"input": []})
    except ImportError:
        pytest.skip("espeak-ng not installed — speech_synthesizer backend unavailable")
    assert result["output"] == []


def test_process_output_is_audio_sample(installed_cls):
    """Output items are AudioSample objects with sample_rate and data."""
    from app.models.audio_sample import AudioSample
    node = installed_cls(config={"backend": "espeak"}, seed=0)
    try:
        result = node.process({"input": ["Test"]})
    except ImportError:
        pytest.skip("espeak-ng not installed — speech_synthesizer backend unavailable")
    for sample in result["output"]:
        assert isinstance(sample, AudioSample)
        assert sample.sample_rate > 0
        assert sample.data is not None


def test_process_metadata_propagation(installed_cls):
    """Output samples have speech_synthesizer metadata key."""
    node = installed_cls(config={"backend": "espeak"}, seed=0)
    try:
        result = node.process({"input": ["Hello"]})
    except ImportError:
        pytest.skip("espeak-ng not installed — speech_synthesizer backend unavailable")
    for sample in result["output"]:
        assert "speech_synthesizer" in sample.metadata
        assert sample.metadata["speech_synthesizer"]["backend"] == "espeak"
