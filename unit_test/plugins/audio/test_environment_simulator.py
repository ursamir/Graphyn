# unit_test/plugins/audio/test_environment_simulator.py
"""Tests for the environment_simulator plugin.

Covers:
  - Registration (Req 7.11)
  - Metadata (Req 7.19)
  - Construction and smoke process

Note: Requires pyroomacoustics. Test is skipped if not installed.
"""
from __future__ import annotations

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
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.11 — environment_simulator registers in a fresh registry."""
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
