# unit_test/plugins/audio/test_audio_generator.py
"""Tests for the audio_generator plugin.

Covers:
  - Registration (Req 7.17)
  - Metadata (Req 7.19)
  - Construction and smoke process
  - audio_generator is SISO: process(list[str]) -> list[AudioSample]
    Input is a list of text prompts (optional — uses config.prompt if empty).
  - Real MusicGen generation (transformers, facebook/musicgen-small, ~2.4 GB
    weights) is ``heavy`` (GRAPHYN_RUN_HEAVY=1). The AudioCraft skips that
    used to hide a missing backend are gone: audiogen was removed and MusicGen
    runs through transformers.
"""
from __future__ import annotations
from unit_test.plugins._helpers import materialize_isolated_class

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
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return materialize_isolated_class(reg.get_class(NODE_TYPE))


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.17 — audio_generator registers in a fresh registry."""
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
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


# ── validation (no model needed) ─────────────────────────────────────────────

def test_no_prompt_is_a_clear_error(installed_cls, tmp_path):
    node = installed_cls(config={"output_dir": str(tmp_path)}, seed=0)
    with pytest.raises(ValueError, match="prompt"):
        node.process({"input": []})


def test_schema_has_only_working_options(installed_cls):
    from typing import get_args

    fields = installed_cls.Config.model_fields
    assert "backend" not in fields  # MusicGen is the only engine; audiogen was removed (needs audiocraft)
    with pytest.raises(Exception):
        installed_cls.Config(duration_s=60)


# ── real generation (heavy) ───────────────────────────────────────────────────

@pytest.mark.heavy
def test_musicgen_generates_and_writes_wav(installed_cls, tmp_path):
    pytest.importorskip("transformers")
    import soundfile as sf

    from app.models.audio_sample import AudioSample

    node = installed_cls(config={"prompt": "calm piano", "duration_s": 1.0, "output_dir": str(tmp_path)}, seed=0)
    out = node.process({"input": []})["output"]
    assert len(out) == 1 and isinstance(out[0], AudioSample)
    assert out[0].sample_rate == 32000 and out[0].data.size > 20000
    data, sr = sf.read(tmp_path / "generated_0.wav")
    assert sr == 32000 and len(data) == out[0].data.size
    trees = node.take_published_file_trees()
    assert trees and trees[0]["files"][0]["path"] == "generated_0.wav"
