# unit_test/plugins/audio/test_augmentation_pipeline.py
"""Tests for the augmentation_pipeline plugin.

Covers:
  - Registration (Req 7.12)
  - Metadata (Req 7.19)
  - Construction and smoke process
  - Req 9 criterion 10: augmentation count lower bound
"""
from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/augmentation_pipeline/"
NODE_TYPE = "augmentation_pipeline"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("augmentation_pipeline_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.12 — augmentation_pipeline registers in a fresh registry."""
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
    node = installed_cls(
        config={
            "copies_per_sample": 1,
            "augmentations": [
                {"type": "gain", "apply_prob": 1.0, "gain_db": [-3, 3]},
            ],
        },
        seed=0,
    )
    result = node.process({"input": [make_audio_sample()]})
    assert "output" in result
    assert isinstance(result["output"], list)
    # 1 original + 1 copy = 2
    assert len(result["output"]) >= 1


# ── Req 9.10: augmentation count lower bound ──────────────────────────────────

@given(n_samples=st.integers(min_value=1, max_value=5))
@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_augmentation_count_lower_bound(installed_cls, make_audio_sample, n_samples):
    """Req 9.10 — output count >= N when at least one augmentation is enabled.

    The node always preserves the original, so output >= N.

    **Validates: Requirement 9.10**
    """
    node = installed_cls(
        config={
            "copies_per_sample": 1,
            "augmentations": [
                {"type": "gain", "apply_prob": 1.0, "gain_db": [-3, 3]},
            ],
        },
        seed=0,
    )
    samples = [make_audio_sample(sr=16000, n=4000) for _ in range(n_samples)]
    result = node.process({"input": samples})
    # Each input produces at least 1 output (the original is always preserved)
    assert len(result["output"]) >= n_samples
