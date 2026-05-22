# unit_test/plugins/audio/test_segmenter.py
"""Tests for the segmenter plugin.

Covers:
  - Registration (Req 7.6)
  - Metadata (Req 7.19)
  - Construction and smoke process
  - Req 9 criteria 8–9: segment metadata invariant, parent reference invariant
"""
from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/segmenter/"
NODE_TYPE = "segmenter"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("segmenter_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.6 — segmenter registers in a fresh registry."""
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
    # 3 seconds at 16kHz = 48000 samples; window_ms=1000 → 3 segments
    node = installed_cls(config={"mode": "fixed", "window_ms": 1000}, seed=0)
    sample = make_audio_sample(sr=16000, n=48000)
    result = node.process({"input": [sample]})
    assert "output" in result
    assert isinstance(result["output"], list)
    assert len(result["output"]) >= 1


# ── Req 9.8: segment metadata invariant ──────────────────────────────────────

@given(
    window_ms=st.integers(min_value=200, max_value=1000),
    duration_s=st.floats(min_value=1.5, max_value=4.0),
)
@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_segment_metadata_invariant(installed_cls, make_audio_sample, window_ms, duration_s):
    """Req 9.8 — each segment has 'start' and 'end' keys in metadata.

    **Validates: Requirement 9.8**
    """
    sr = 16000
    n = int(sr * duration_s)
    node = installed_cls(
        config={"mode": "fixed", "window_ms": window_ms, "min_segment_ms": 50},
        seed=0,
    )
    sample = make_audio_sample(sr=sr, n=n)
    result = node.process({"input": [sample]})
    segments = result["output"]
    assert len(segments) >= 1
    for seg in segments:
        assert "start" in seg.metadata, f"Missing 'start' in segment metadata: {seg.metadata}"
        assert "end" in seg.metadata, f"Missing 'end' in segment metadata: {seg.metadata}"


# ── Req 9.9: parent reference invariant ──────────────────────────────────────

def test_parent_reference_invariant(installed_cls, make_audio_sample):
    """Req 9.9 — segment metadata['parent'] equals the original sample's path.

    **Validates: Requirement 9.9**
    """
    sr = 16000
    node = installed_cls(
        config={"mode": "fixed", "window_ms": 500, "min_segment_ms": 50},
        seed=0,
    )
    sample = make_audio_sample(sr=sr, n=sr * 3, path="/fake/test_audio.wav")
    result = node.process({"input": [sample]})
    segments = result["output"]
    assert len(segments) >= 1
    for seg in segments:
        assert seg.metadata["parent"] == str(sample.path)
