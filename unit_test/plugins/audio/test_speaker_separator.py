# unit_test/plugins/audio/test_speaker_separator.py
"""Tests for the speaker_separator plugin.

Covers:
  - Registration (Req 7.10)
  - Metadata (Req 7.19)
  - Construction

Note: The actual process() requires pyannote.audio or speechbrain (heavy deps).
The smoke test is skipped if neither is available.
"""
from __future__ import annotations
from unit_test.plugins._helpers import materialize_isolated_class

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/speaker_separator/"
NODE_TYPE = "speaker_separator"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("speaker_separator_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return materialize_isolated_class(reg.get_class(NODE_TYPE))


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.10 — speaker_separator registers in a fresh registry."""
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
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

def test_process_requires_setup(installed_cls, make_audio_sample):
    """process() before setup() is a clear error (the executor always calls setup())."""
    node = installed_cls(config={}, seed=0)
    with pytest.raises(RuntimeError, match="setup"):
        node.process({"input": [make_audio_sample()]})


@pytest.mark.heavy
def test_process_smoke(installed_cls, make_audio_sample):
    """SepFormer (speechbrain, no credentials) separates a mixture into 2 sources."""
    pytest.importorskip("speechbrain")
    node = installed_cls(config={"backend": "speechbrain"}, seed=0)
    node.setup()
    result = node.process({"input": [make_audio_sample()]})
    assert "output" in result
    assert isinstance(result["output"], list)
    assert len(result["output"]) >= 2
