# unit_test/plugins/audio/test_environment_simulator.py
"""Tests for the environment_simulator plugin.

Covers:
  - Registration (Req 7.11)
  - Metadata (Req 7.19)
  - Construction and smoke process

Note: Requires pyroomacoustics. Test is skipped if not installed.
"""
from __future__ import annotations
from unit_test.plugins._helpers import materialize_isolated_class

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/environment_simulator/"
NODE_TYPE = "environment_simulator"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("environment_simulator_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return materialize_isolated_class(reg.get_class(NODE_TYPE))


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.11 — environment_simulator registers in a fresh registry."""
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

def test_process_smoke(installed_cls, make_audio_sample):
    """EnvironmentSimulatorNode is SISO — process({"input": [...]}) -> {"output": [...]}."""
    pytest.importorskip("pyroomacoustics", reason="pyroomacoustics not installed")
    node = installed_cls(
        config={"preset": "room", "copies_per_sample": 1, "snr_db": 0.0},
        seed=0,
    )
    result = node.process({"input": [make_audio_sample(sr=16000, n=8000)]})
    assert "output" in result
    assert isinstance(result["output"], list)
    assert len(result["output"]) >= 1


def test_copies_are_distinct_and_seeded(installed_cls):
    """copies_per_sample yields different rooms/noise per copy, reproducibly per seed."""
    pytest.importorskip("pyroomacoustics")
    import numpy as np

    from app.models.audio_sample import AudioSample

    sr = 16000
    t = np.arange(sr // 2) / sr
    s = AudioSample(path="/t.wav", sample_rate=sr, data=(0.3 * np.sin(2 * np.pi * 300 * t)).astype(np.float32))
    cfg = {"copies_per_sample": 3, "snr_db": 20}
    a = installed_cls(config=cfg, seed=7).process({"input": [s]})["output"]
    b = installed_cls(config=cfg, seed=7).process({"input": [s]})["output"]
    assert len(a) == 3
    assert [x.metadata["room_simulation"]["copy_index"] for x in a] == [0, 1, 2]
    assert len({round(x.metadata["room_simulation"]["rt60"], 6) for x in a}) == 3
    n = min(len(a[0].data), len(a[1].data))
    assert np.abs(a[0].data[:n] - a[1].data[:n]).max() > 1e-3
    assert all(np.allclose(x.data, y.data) for x, y in zip(a, b))
