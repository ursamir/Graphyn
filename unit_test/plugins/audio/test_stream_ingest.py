# unit_test/plugins/audio/test_stream_ingest.py
"""Tests for the stream_ingest plugin.

Covers:
  - Registration (Req 7.4)
  - Metadata (Req 7.19)
  - Construction
  - Smoke process (file_stream source with a temp wav file)
"""
from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/stream_ingest/"
NODE_TYPE = "stream_ingest"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("stream_ingest_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.4 — stream_ingest registers in a fresh registry."""
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

def test_process_smoke_file_stream(installed_cls, tmp_path):
    """StreamIngestNode is a source node — process(inputs: dict) -> dict.

    Uses source='file_stream' to avoid requiring hardware.
    """
    # Create a minimal wav file
    wav_path = tmp_path / "stream_test.wav"
    sr = 16000
    data = np.random.default_rng(42).standard_normal(sr * 2).astype(np.float32) * 0.1
    sf.write(str(wav_path), data, sr)

    node = installed_cls(
        config={
            "source": "file_stream",
            "file_path": str(wav_path),
            "sample_rate": sr,
            "chunk_ms": 500,
            "duration_s": 2.0,
        },
        seed=0,
    )
    result = node.process({})
    assert "output" in result
    assert isinstance(result["output"], list)
