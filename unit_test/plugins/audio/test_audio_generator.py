# unit_test/plugins/audio/test_audio_generator.py
"""Tests for the audio_generator plugin.

Covers:
  - Registration (Req 7.17)
  - Metadata (Req 7.19)
  - Construction and smoke process
  - audio_generator is SISO: process(list[str]) -> list[AudioSample]
    Input is a list of text prompts (optional — uses config.prompt if empty).
    Requires AudioCraft (musicgen/audiogen) — raises ImportError if not installed.
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/audio_generator/"
NODE_TYPE = "audio_generator"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("audio_generator_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.17 — audio_generator registers in a fresh registry."""
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
# audio_generator requires AudioCraft (audiocraft package).
# If not installed, _resolve_backend() raises ImportError — skip gracefully.

def test_process_smoke(installed_cls):
    """Smoke test: SISO process with text prompt returns output AudioSamples."""
    node = installed_cls(config={"prompt": "test sound"}, seed=0)
    try:
        result = node.process({"input": ["test sound"]})
    except ImportError:
        pytest.skip("audiocraft not installed — audio_generator backend unavailable")
    assert "output" in result
    assert isinstance(result["output"], list)
    assert len(result["output"]) >= 1


def test_process_empty_input_uses_config_prompt(installed_cls):
    """Empty input list falls back to config.prompt."""
    node = installed_cls(config={"prompt": "ambient music"}, seed=0)
    try:
        result = node.process({"input": []})
    except ImportError:
        pytest.skip("audiocraft not installed — audio_generator backend unavailable")
    assert "output" in result
    assert isinstance(result["output"], list)
    assert len(result["output"]) >= 1


def test_process_output_is_audio_sample(installed_cls):
    """Output items are AudioSample objects with sample_rate and data."""
    from app.models.audio_sample import AudioSample
    node = installed_cls(config={"prompt": "test"}, seed=0)
    try:
        result = node.process({"input": ["test"]})
    except ImportError:
        pytest.skip("audiocraft not installed — audio_generator backend unavailable")
    for sample in result["output"]:
        assert isinstance(sample, AudioSample)
        assert sample.sample_rate > 0
        assert sample.data is not None
