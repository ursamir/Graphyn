# unit_test/plugins/audio/test_stream_processor.py
"""Tests for the stream_processor plugin.

Covers:
  - Registration (Req 7.18)
  - Metadata (Req 7.19)
  - Construction and smoke process
  - stream_processor is SISO: process(list[AudioSample]) -> list[AudioSample]
    Implements rolling window buffering; output count depends on window/hop config.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/stream_processor/"
NODE_TYPE = "stream_processor"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("stream_processor_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.18 — stream_processor registers in a fresh registry."""
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

def test_process_smoke(installed_cls, make_audio_sample):
    """Smoke test: SISO process returns output list."""
    # Use a 2-second chunk at 16kHz with 1000ms window / 500ms hop
    # → expect at least 1 window emitted
    node = installed_cls(
        config={"window_ms": 1000, "hop_ms": 500, "sample_rate": 16000},
        seed=0,
    )
    node.setup()
    sample = make_audio_sample(sr=16000, n=32000)  # 2 seconds
    result = node.process({"input": [sample]})
    assert "output" in result
    assert isinstance(result["output"], list)


def test_process_window_size(installed_cls, make_audio_sample):
    """Each output chunk has exactly window_samples samples (Req 10.8 window size invariant)."""
    sr = 16000
    window_ms = 500
    window_samples = int(sr * window_ms / 1000)  # 8000

    node = installed_cls(
        config={"window_ms": window_ms, "hop_ms": 250, "sample_rate": sr},
        seed=0,
    )
    node.setup()
    # 3 seconds of audio → multiple windows
    sample = make_audio_sample(sr=sr, n=sr * 3)
    result = node.process({"input": [sample]})

    assert len(result["output"]) >= 1
    for chunk in result["output"]:
        assert len(chunk.data) == window_samples, (
            f"Expected {window_samples} samples, got {len(chunk.data)}"
        )


def test_process_output_metadata(installed_cls, make_audio_sample):
    """Output chunks have stream_processor metadata key."""
    node = installed_cls(
        config={"window_ms": 500, "hop_ms": 250, "sample_rate": 16000},
        seed=0,
    )
    node.setup()
    sample = make_audio_sample(sr=16000, n=16000 * 2)
    result = node.process({"input": [sample]})

    for chunk in result["output"]:
        assert "stream_processor" in chunk.metadata
        sp_meta = chunk.metadata["stream_processor"]
        assert "window_idx" in sp_meta
        assert "window_ms" in sp_meta
        assert "hop_ms" in sp_meta


def test_process_empty_input(installed_cls):
    """Empty input list produces empty output (no buffered data)."""
    node = installed_cls(
        config={"window_ms": 1000, "hop_ms": 500, "sample_rate": 16000},
        seed=0,
    )
    node.setup()
    result = node.process({"input": []})
    assert result["output"] == []


def test_process_sample_rate_preserved(installed_cls, make_audio_sample):
    """Output chunks preserve the configured sample_rate."""
    sr = 16000
    node = installed_cls(
        config={"window_ms": 500, "hop_ms": 250, "sample_rate": sr},
        seed=0,
    )
    node.setup()
    sample = make_audio_sample(sr=sr, n=sr * 2)
    result = node.process({"input": [sample]})

    for chunk in result["output"]:
        assert chunk.sample_rate == sr
