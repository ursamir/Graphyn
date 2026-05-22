# unit_test/plugins/audio/test_dataset_ingest.py
"""Tests for the dataset_ingest plugin.

Covers:
  - Registration (Req 7.3)
  - Metadata (Req 7.19)
  - Construction
  - Smoke process (filesystem source with a temp directory)
"""
from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/dataset_ingest/"
NODE_TYPE = "dataset_ingest"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("dataset_ingest_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.3 — dataset_ingest registers in a fresh registry."""
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

def test_process_smoke_filesystem(installed_cls, tmp_path):
    """DatasetIngestNode is a source node — process(inputs: dict) -> dict."""
    # Create a minimal audio file in a temp directory
    audio_dir = tmp_path / "audio_data" / "label_a"
    audio_dir.mkdir(parents=True)
    wav_path = audio_dir / "sample.wav"
    sr = 16000
    data = np.zeros(sr, dtype=np.float32)
    sf.write(str(wav_path), data, sr)

    node = installed_cls(
        config={"source_type": "filesystem", "path": str(tmp_path / "audio_data")},
        seed=0,
    )
    result = node.process({})
    assert "output" in result
    assert isinstance(result["output"], list)
    assert len(result["output"]) >= 1
