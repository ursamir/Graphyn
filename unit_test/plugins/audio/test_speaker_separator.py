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
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.10 — speaker_separator registers in a fresh registry."""
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
    """SpeakerSeparatorNode is SISO — process({"input": [...]}) -> {"output": [...]}."""
    # Skip if neither pyannote nor speechbrain is available
    try:
        import pyannote.audio  # noqa: F401
    except ImportError:
        try:
            import speechbrain  # noqa: F401
        except ImportError:
            pytest.skip("Neither pyannote.audio nor speechbrain is installed")

    node = installed_cls(config={}, seed=0)
    result = node.process({"input": [make_audio_sample()]})
    assert "output" in result
    assert isinstance(result["output"], list)
