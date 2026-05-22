# unit_test/plugins/audio/test_speech_enhancer.py
"""Tests for the speech_enhancer plugin.

Covers:
  - Registration (Req 7.9)
  - Metadata (Req 7.19)
  - Construction and smoke process

Note: Uses spectral backend (noisereduce) which is CPU-only and doesn't
require GPU or heavy optional deps.
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/speech_enhancer/"
NODE_TYPE = "speech_enhancer"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("speech_enhancer_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.9 — speech_enhancer registers in a fresh registry."""
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
    """SpeechEnhancerNode is SISO — process({"input": [...]}) -> {"output": [...]}."""
    noisereduce = pytest.importorskip("noisereduce", reason="noisereduce not installed")
    node = installed_cls(
        config={"backend": "spectral", "denoise": True, "dereverb": False},
        seed=0,
    )
    result = node.process({"input": [make_audio_sample()]})
    assert "output" in result
    assert isinstance(result["output"], list)
    assert len(result["output"]) == 1


def test_process_output_shape_preserved(installed_cls, make_audio_sample):
    """Output audio has the same sample_rate as input."""
    pytest.importorskip("noisereduce", reason="noisereduce not installed")
    node = installed_cls(
        config={"backend": "spectral", "denoise": True},
        seed=0,
    )
    sample = make_audio_sample(sr=16000, n=8000)
    result = node.process({"input": [sample]})
    assert result["output"][0].sample_rate == 16000
