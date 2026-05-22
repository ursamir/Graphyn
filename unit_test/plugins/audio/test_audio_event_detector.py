# unit_test/plugins/audio/test_audio_event_detector.py
"""Tests for the audio_event_detector plugin.

Covers:
  - Registration (Req 7.13)
  - Metadata (Req 7.19)
  - Construction and smoke process
  - audio_event_detector uses a multi-port process(inputs: dict) -> dict signature
    (not SISO), so the smoke test passes {"input": [...]} directly.
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/audio_event_detector/"
NODE_TYPE = "audio_event_detector"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("audio_event_detector_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.13 — audio_event_detector registers in a fresh registry."""
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
# audio_event_detector has a multi-port process(inputs: dict) -> dict signature.
# It returns {"output": list[AudioSample], "events": list[dict]}.

def test_process_smoke(installed_cls, make_audio_sample):
    """Smoke test: multi-port process returns output and events keys."""
    node = installed_cls(config={}, seed=0)
    # The node's process() receives the full inputs dict (not SISO)
    try:
        result = node.process({"input": [make_audio_sample()]})
    except ImportError:
        pytest.skip("tensorflow/tensorflow_hub not installed — YAMNet backend unavailable")
    assert isinstance(result, dict)
    assert "output" in result
    assert "events" in result
    assert isinstance(result["output"], list)
    assert isinstance(result["events"], list)


def test_process_empty_input(installed_cls):
    """Empty input list produces empty output and events."""
    node = installed_cls(config={}, seed=0)
    result = node.process({"input": []})
    assert result["output"] == []
    assert result["events"] == []


def test_process_output_has_events_metadata(installed_cls, make_audio_sample):
    """Output samples have 'events' key in their metadata."""
    node = installed_cls(config={}, seed=0)
    try:
        result = node.process({"input": [make_audio_sample()]})
    except ImportError:
        pytest.skip("tensorflow/tensorflow_hub not installed — YAMNet backend unavailable")
    for sample in result["output"]:
        assert "events" in sample.metadata
        assert isinstance(sample.metadata["events"], list)
